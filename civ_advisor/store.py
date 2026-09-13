"""Owns the current snapshot; rebuilds, archives, and fans out change events.

A rebuild publishes one immutable `Snapshot`: the state, the ranked insights, the source
coverage and the session/revision identity that produced them, all captured together. Every
reader — serializers, the API, the commentary worker — takes its numbers from one snapshot,
so nothing can mix turn 80's insights with turn 81's state.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from civ_advisor.advisors import Insight, run_all
from civ_advisor.archive import UNKNOWN_GAME, archive_logs, game_key
from civ_advisor.games.base import GameProfile
from civ_advisor.ingest.load import RawLogs, load_logs
from civ_advisor.state.build import build_state
from civ_advisor.state.models import GameState
from civ_advisor.tuner.base import NullTuner, TUNER_OFF, TunerUnavailable

if TYPE_CHECKING:
    from civ_advisor.llm.worker import CommentaryWorker

log = logging.getLogger(__name__)

ARCHIVE_SUFFIXES = {".csv", ".log"}  # mirror every log the game writes, not just the ones we parse

SCHEMA_VERSION = 1

# Log files grouped by the capability they feed, so the dashboard can say "tactical
# intelligence is unavailable" instead of listing eight unreadable AI logs. `required`
# marks a domain the advisor cannot work without; everything else is optional and its
# absence must disable its capability quietly rather than raise a warning.
# `turn_scoped` marks a domain whose rows are dated by game turn, and so can meaningfully
# be behind the analysis turn. Identity is written once when a save loads, so measuring
# its age against the turn counter would report a 99-turn lag on a perfectly current file.
#
def _unattributed_queue_rows(state: GameState, profile: GameProfile) -> int | None:
    """Build-queue rows with no owner, or None when this profile has no such concept.

    Civ VI recovers ownership by joining City name against AI_CityBuild.csv (spec 3.2);
    a city absent from that join is attributed to nobody rather than defaulted to the
    human, and `city_ownership` is the attribute that join reader feeds. Civ VII's own
    CityBuildQueue.csv carries the player as a column directly -- its reader always
    produces an int (`ingest/production.py`), so the gap cannot occur there at all, not
    merely "did not occur this time." Whether the concept applies is read from the
    profile's own declared readers, not the game id, so a future game gains or lacks it
    by what it declares, not by name. `state.build_queues` mirrors `RawLogs.build_queue`
    row for row (state/build.py), so nothing is discarded before this count -- it is not
    inferred from a row-count difference, which would silently absorb a parse failure too.
    """
    if not any(r.attr == "city_ownership" for r in profile.readers):
        return None
    return sum(1 for row in state.build_queues if row.player is None)


# The fifth element names RawLogs/reader ATTRIBUTES, not filenames: two games can feed the
# same attribute from differently-named files (Civ VII's build queue is CityBuildQueue.csv,
# Civ VI's is City_BuildQueue.csv), and only the profile's own reader table knows which file
# backs an attribute for THIS game. Resolving through the attribute, in `_coverage`, is what
# lets a domain be reported correctly regardless of which profile built the state.
#
# The sixth element is an optional counter over `(GameState, GameProfile)`, for a domain
# that can read successfully and still leave some of its own rows unaccounted for -- it
# returns None itself when the profile has no such concept at all (every domain but
# production, today; and production itself, for Civ VII).
DOMAINS: tuple[tuple[str, str, bool, bool, tuple[str, ...],
                     Callable[[GameState, GameProfile], int | None] | None], ...] = (
    ("empire", "Empire yields and standings", True, True, ("stats",), None),
    ("treasury", "Treasury and maintenance", False, True, ("treasury",), None),
    ("happiness", "Happiness and celebrations", False, True, ("happiness",), None),
    ("strategy", "Rival victory strategies", False, True, ("victories",), None),
    ("diplomacy", "Rival diplomatic intent", False, True,
     ("diplomacy", "diplomacy_summary", "deals"), None),
    ("targets", "Rival target plots", False, True, ("targets",), None),
    ("history", "Age and historian events", False, True, ("historian",), None),
    ("production", "Settlement build queues", False, True, ("build_queue",),
     _unattributed_queue_rows),
    ("combat", "Combat results", False, True, ("combat",), None),
    ("gossip", "Observed world events", False, True, ("gossip",), None),
    ("tactical", "Tactical unit positions and plans", False, True,
     ("unit_operations", "tactical", "operations", "combat_orders",
      "operation_evals", "unit_efficiency", "mayhem", "commander_promotions"), None),
    ("identity", "Leader and civilization identity", False, False, ("player_identities",), None),
)

# Why the advisor decided it is looking at a different game than before. Anything other
# than a plain continuation must not silently inherit the previous session's state.
FIRST_LOAD = "first_load"
LOGS_WIPED = "logs_wiped"
DIFFERENT_SAVE = "different_save"
TURN_WENT_BACKWARDS = "turn_went_backwards"
GAME_SWITCHED = "game_switched"


@dataclass(frozen=True)
class DomainCoverage:
    """How well one capability's log files covered the turn we analyzed.

    `status` separates the failures the player needs told apart:
      not_applicable — this game's profile declares no reader that could ever produce
                       this domain's data at all; the concept does not exist for this
                       game, distinct from it existing but failing to read;
      unavailable    — a reader for this domain IS declared, but nothing came of it
                       (missing or malformed);
      partial        — some of what the domain needs is readable, but not all of it —
                       either a declared file failed to read, or (for a domain built
                       from several attributes) this game's profile has no reader at
                       all for one of them;
      empty          — readable, but the game has written no rows yet;
      stale          — rows exist, but none of them reach the analysis turn;
      ok             — rows reach the analysis turn, or the domain is not turn-scoped.

    "stale" is a statement about coverage, not a fault: episodic logs such as commander
    promotions legitimately have nothing to say on most turns, which is why
    `latest_turn` and `lag` ship alongside so the UI can date the gap instead of
    alarming about it.

    `partial` has two distinct causes that `missing` alone cannot tell apart: a
    declared file that failed to read, or (via `unbacked`) an attribute this domain
    needs for which the profile has no reader at all. `missing` can be empty while
    `unbacked` is not -- exactly Civ VI's diplomacy domain, which reads its one
    declared file fine but has no reader for `deals` at all. Reporting that as "0 of 1
    logs unreadable" would state a false reason for the gap; the renderer must consult
    `unbacked` to say the true one.
    """

    name: str
    label: str
    required: bool
    turn_scoped: bool
    status: str
    files: tuple[str, ...]
    missing: tuple[str, ...]
    rows: int
    latest_turn: int | None
    lag: int | None
    errors: tuple[str, ...]
    unbacked: tuple[str, ...] = ()       # attrs this domain needs that the profile has no reader for
    unattributed: int | None = None      # rows this domain's own counter could not attribute; None = no such concept


@dataclass(frozen=True)
class Snapshot:
    """One coherent capture. Never mutated after publication."""

    schema_version: int
    game_id: str            # which game's readers produced this; never inferred downstream
    session: str            # this epoch's id; changes whenever we may be looking at another game
    epoch: int              # how many epochs this process has seen, 1-based
    epoch_reason: str       # why this epoch started
    game_key: str | None    # the save's seeds, when GameCore.log recorded them
    revision: int           # monotonic across the process; higher always means newer
    captured_at: float      # time.time() when the rebuild finished
    latest_turn: int        # newest turn any row mentions, possibly still in progress
    analysis_turn: int      # the complete turn every insight was computed on
    state: GameState
    insights: tuple[Insight, ...]
    coverage: tuple[DomainCoverage, ...]
    # Never None. A caller that had to check for absence would eventually forget,
    # and a missing figure would read as a zero.
    tuner: object = TUNER_OFF

    @property
    def in_progress(self) -> bool:
        return self.latest_turn > self.analysis_turn

    def domain(self, name: str) -> DomainCoverage | None:
        return next((c for c in self.coverage if c.name == name), None)


def _coverage(state: GameState, analysis_turn: int, profile: GameProfile) -> tuple[DomainCoverage, ...]:
    # attr -> filename, for whichever readers THIS profile actually declares. A domain's
    # attrs are resolved through this map rather than checked against a literal filename,
    # so the same domain definition means the right thing for every game.
    attr_to_file = {r.attr: r.filename for r in profile.readers}
    out = []
    for name, label, required, turn_scoped, attrs, counter in DOMAINS:
        backed = [attr_to_file[a] for a in attrs if a in attr_to_file]
        unbacked = tuple(a for a in attrs if a not in attr_to_file)
        if not backed:
            # No reader this profile declares could ever produce any of this domain's
            # data: the concept does not exist for this game, not merely unreadable.
            out.append(DomainCoverage(
                name=name, label=label, required=required, turn_scoped=turn_scoped,
                status="not_applicable", files=(), missing=(), rows=0,
                latest_turn=None, lag=None, errors=(), unbacked=unbacked,
            ))
            continue
        names = tuple(backed)
        statuses = [state.files[n] for n in names if n in state.files]
        readable = [f for f in statuses if f.ok]
        missing = tuple(f.name for f in statuses if not f.ok)
        errors = tuple(f.error for f in statuses if not f.ok and f.error)
        rows = sum(f.rows for f in readable)
        turns = [f.latest_turn for f in readable if f.latest_turn is not None]
        latest = max(turns) if turns else None
        if not readable:
            status = "unavailable"
        elif missing or unbacked:
            # `unbacked`: this domain is built from several attributes and at least one
            # of them has no reader at all for this profile. A domain must not report
            # itself whole when this game cannot supply part of what it claims to cover.
            # `missing` and `unbacked` are different reasons and both ship on the record
            # (rather than being collapsed into one "partial"), because "some logs could
            # not be read" and "this game does not log part of this" are different
            # statements to a player and the renderer must be able to tell them apart.
            status = "partial"
        elif not rows:
            status = "empty"
        elif not turn_scoped:
            status = "ok"
        elif latest is None or latest < analysis_turn:
            status = "stale"
        else:
            status = "ok"
        out.append(DomainCoverage(
            name=name, label=label, required=required, turn_scoped=turn_scoped,
            status=status, files=names, missing=missing, rows=rows,
            latest_turn=latest if turn_scoped else None,
            lag=None if latest is None or not turn_scoped else max(analysis_turn - latest, 0),
            errors=errors, unbacked=unbacked,
            unattributed=None if counter is None else counter(state, profile),
        ))
    return tuple(out)


class Store:
    def __init__(self, logs_dir: Path | None, archive_root: Path | None = None,
                 commentary_worker: CommentaryWorker | None = None,
                 identity_provider: Callable[[Snapshot], dict] | None = None,
                 *, profile: GameProfile | None) -> None:
        # `identity_provider` supplies the decision, context and catalog revisions that
        # complete a generation's identity. It is a hook rather than an import so this
        # module stays free of the decisions package, and so a store with no decision
        # layer still works — the identity is then simply less specific.
        self.identity_provider = identity_provider
        self.logs_dir = logs_dir
        self.profile = profile
        self.archive_root = archive_root
        self._pending_switch = False   # a game switch forces the next snapshot to a new epoch
        # Bumped on every ACTUAL switch_to (not a no-op one). `profile`/`logs_dir` alone
        # cannot detect an A->B->A sequence: profile objects are per-game singletons, so
        # a rebuild started in the first A period and a switch back to A later would look
        # identical on those two fields even though a whole B sitting happened in between.
        # A stale in-flight rebuild from that first A period must still be discarded.
        self._generation = 0
        self.snapshot: Snapshot | None = None
        self._lock = threading.Lock()
        self._subscribers: set[asyncio.Queue] = set()
        self._revision = 0
        self._epoch = 0
        self._session: str | None = None
        self._session_reason = FIRST_LOAD
        self._session_has_data = False   # has this session ever seen a Player_Stats row?
        self._observed_key: str | None = None  # newest seeds this session read
        self._session_seq = 0            # distinguishes sessions within this store
        self._pending_reason: str | None = None  # why the next data-bearing snapshot starts an epoch
        self.commentary_worker = commentary_worker

    # `state` and `insights` stay readable for the legacy endpoints, but always come from
    # the same snapshot so two reads inside one request cannot straddle a rebuild.
    @property
    def state(self) -> GameState | None:
        snapshot = self.snapshot
        return snapshot.state if snapshot is not None else None

    @property
    def insights(self) -> list[Insight]:
        snapshot = self.snapshot
        return list(snapshot.insights) if snapshot is not None else []

    @property
    def active(self) -> bool:
        """Whether a game is selected at all. False is a real state, not a failure."""
        return self.profile is not None and self.logs_dir is not None

    def switch_to(self, profile: GameProfile, logs_dir: Path) -> None:
        """Point the store at another game.

        Everything computed under the previous game is dropped here rather than
        left to expire: the reader table, the capability matrix and the context
        namespace all change at once, so the previous snapshot is not this game's
        past in any sense. Subscribers survive -- the browser is still connected --
        but the next snapshot starts a new epoch, which is what makes the change
        tracker and the player's record treat this as another sitting.
        """
        with self._lock:
            if self.profile is not None and self.profile.id == profile.id \
                    and self.logs_dir == logs_dir:
                return
            had_game = self.profile is not None
            self.profile = profile
            self.logs_dir = logs_dir
            self.snapshot = None
            self._observed_key = None
            self._session_has_data = False
            self._pending_reason = None
            # Activating an idle store is not a switch; it is this store's first load.
            self._pending_switch = had_game
            self._generation += 1

    def rebuild(self) -> Snapshot | None:
        """Re-read every log, archive it, and recompute advice. Safe to call from a
        worker thread. Returns None while no game is selected.

        Reading the logs happens outside the lock, so `switch_to` can run while this
        read is in flight. If it does, `self.profile`/`self.logs_dir` will have moved
        on by the time this rebuild reaches the lock, and the raw/state/insights
        already computed belong to the game just switched away from -- publishing
        them would either resurrect that game's content under the new game's epoch,
        or (if switched back) misattribute it to a game it was never read for. Such a
        rebuild is discarded rather than published; the next scheduled rebuild picks
        up whichever game is actually active by then.

        `profile`/`logs_dir` alone cannot catch every such case: an A->B->A sequence
        (a player pinning away and back before this read finishes) restores the same
        profile object and directory, so those two fields match again even though this
        read belongs to a sitting that already ended. `generation`, bumped on every
        real `switch_to`, catches that: it can only equal the current value if no
        switch happened at all while this read was in flight.
        """
        profile, logs_dir, generation = self.profile, self.logs_dir, self._generation
        if profile is None or logs_dir is None:
            return None
        raw = load_logs(logs_dir, profile)
        state = build_state(raw)
        insights = run_all(state, profile)
        key = game_key(logs_dir)
        # Outside the lock, and never fatal: a socket problem must not discard a
        # poll that read every log correctly. Opened once per rebuild, not once
        # per question the snapshot is later asked.
        tuner = TUNER_OFF
        factory = getattr(profile, "tuner", None)
        if factory is not None:
            try:
                tuner = factory()
            except Exception:       # a third-party socket has many failure shapes
                tuner = NullTuner(
                    TunerUnavailable.NOT_ANSWERING,
                    "the tuner socket could not be reached this turn")
        with self._lock:
            if self.profile is not profile or self.logs_dir != logs_dir \
                    or self._generation != generation:
                # This rebuild's own tuner reading is discarded along with everything
                # else it read; nothing will ever publish it, so its socket must not
                # be left open.
                self._close_tuner(tuner)
                return None
            snapshot = self._capture_locked(raw, state, insights, key, profile, tuner)
            previous = self.snapshot
            self.snapshot = snapshot
            # Captured under the same lock as the snapshot itself: a switch_to landing
            # in the gap between releasing this lock and _archive() running must not be
            # able to mirror one game's logs into another's archive root under a session
            # id that belongs to neither -- the same hazard this method's own docstring
            # already guards the snapshot against, applied to archiving too.
            archive_root = self.archive_root
            observed_key = self._observed_key
        # Only after the new snapshot has been published and the lock released: a
        # reader that fetched `previous` just before this rebuild took the lock may
        # still be reading through its tuner, and closing it any earlier would pull
        # the socket out from under that read -- the same swap-before-safe ordering
        # hazard that has bitten this project before, applied to a tuner socket
        # instead of a file or a snapshot field.
        if previous is not None:
            self._close_tuner(previous.tuner)
        self._archive(raw, snapshot.session, logs_dir, archive_root, observed_key)
        if self.commentary_worker is not None:
            self.commentary_worker.schedule(snapshot, revisions=self.revisions(snapshot))
        return snapshot

    @staticmethod
    def _close_tuner(tuner: object) -> None:
        """Close a tuner's socket if it has one. TUNER_OFF and every NullTuner do not."""
        close = getattr(tuner, "close", None)
        if callable(close):
            try:
                close()
            except Exception:   # closing a socket must never break a rebuild
                log.exception("closing the previous tuner failed; continuing")

    def revisions(self, snapshot: Snapshot) -> dict:
        """The decision/context/catalog revisions for this snapshot, if anything supplies them."""
        if self.identity_provider is None:
            return {}
        try:
            return self.identity_provider(snapshot)
        except Exception:   # an optional identity must never break a rebuild
            log.exception("decision identity provider failed; commentary identity will be partial")
            return {}

    def _capture_locked(self, raw: RawLogs, state: GameState, insights: list[Insight],
                        key: str | None, profile: GameProfile, tuner: object) -> Snapshot:
        self._revision += 1
        reason = self._session_reason_locked(raw, key)  # compares `key` against the session's own
        if reason is not None:
            self._epoch += 1
            self._session_seq += 1
            # The timestamp and counter alone are not unique: two advisors started in
            # the same second, or two stores in one process, would collide — and the
            # session id is what the player's saved acknowledgements are filed under, so
            # a collision could apply one game's record to another.
            self._session = (f"{time.strftime('%Y%m%dT%H%M%S')}-{self._session_seq}"
                             f"-{secrets.token_hex(3)}")
            self._session_reason = reason
            self._session_has_data = False
            self._observed_key = key   # a new epoch never inherits the old save's seeds
        elif key is not None:
            self._observed_key = key
        if raw.stats:
            self._session_has_data = True
        assert self._session is not None
        return Snapshot(
            schema_version=SCHEMA_VERSION,
            game_id=profile.id,
            session=self._session, epoch=self._epoch, epoch_reason=self._session_reason,
            game_key=self._observed_key, revision=self._revision, captured_at=time.time(),
            latest_turn=state.latest_turn, analysis_turn=state.complete_through_turn,
            state=state, insights=tuple(insights),
            coverage=_coverage(state, state.complete_through_turn, profile),
            tuner=tuner,
        )

    def _session_reason_locked(self, raw: RawLogs, key: str | None) -> str | None:
        """The reason a new epoch starts with this snapshot, or None to continue the current one.

        Civ VII deletes its Logs/ directory on launch, so an empty read after we had data
        means the game relaunched and whatever arrives next belongs to a different sitting
        — even when it reports the same seeds, because one save can be branched. A turn
        that moves backwards is the same story from a reload we never caught mid-wipe.
        Ambiguity resolves towards a new epoch: silently carrying acknowledgements across
        a reload is worse than asking for them again.
        """
        if self._pending_switch:
            self._pending_switch = False
            return GAME_SWITCHED
        if not raw.stats:
            if self._session is None:
                return FIRST_LOAD          # provisional session so every snapshot has an id
            if self._session_has_data:
                self._pending_reason = LOGS_WIPED
            return None
        if self._pending_reason is not None:
            reason, self._pending_reason = self._pending_reason, None
            return reason
        if self._session is None:
            return FIRST_LOAD
        if key is not None and self._observed_key is not None and key != self._observed_key:
            return DIFFERENT_SAVE
        previous = self.snapshot
        if previous is not None and previous.latest_turn > 0:
            if max(r.turn for r in raw.stats) < previous.latest_turn:
                return TURN_WENT_BACKWARDS
        return None

    def _archive(self, raw: RawLogs, session: str, logs_dir: Path,
                archive_root: Path | None, observed_key: str | None) -> None:
        """Mirror this rebuild's own logs under this rebuild's own archive root.

        `logs_dir`/`archive_root`/`observed_key` are the caller's locked-section
        snapshot of `self.logs_dir`/`self.archive_root`/`self._observed_key`, not a
        fresh read of the live attributes: by the time this runs the lock is released,
        and a `switch_to` that landed in that gap must not redirect an in-flight
        rebuild's own logs into the archive root (or under the game_key) of whatever
        the store has moved on to.
        """
        if archive_root is None:
            return
        if not raw.stats:
            return
        try:
            key = observed_key or UNKNOWN_GAME
            names = sorted(p.name for p in logs_dir.iterdir() if p.suffix in ARCHIVE_SUFFIXES)
            archive_logs(logs_dir, archive_root / key / session, names)
        except Exception:            # archiving must never cost the player their advice
            log.exception("archiving failed; continuing without it")

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict) -> None:
        """Deliver an event to every subscriber. Call on the event-loop thread."""
        for q in list(self._subscribers):
            q.put_nowait(event)


__all__ = ["DOMAINS", "SCHEMA_VERSION", "DomainCoverage", "Snapshot", "Store"]
