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
from civ_advisor.ingest.load import RawLogs, load_logs
from civ_advisor.state.build import build_state
from civ_advisor.state.models import GameState

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
DOMAINS: tuple[tuple[str, str, bool, bool, tuple[str, ...]], ...] = (
    ("empire", "Empire yields and standings", True, True, ("Player_Stats.csv",)),
    ("treasury", "Treasury and maintenance", False, True, ("Player_Treasury.csv",)),
    ("happiness", "Happiness and celebrations", False, True, ("Player_Happiness.csv",)),
    ("strategy", "Rival victory strategies", False, True, ("AI_Victories.csv",)),
    ("diplomacy", "Rival diplomatic intent", False, True,
     ("AI_DiplomaticActions.csv", "DiplomacySummary.csv", "DiplomacyDeals.log")),
    ("targets", "Rival target plots", False, True, ("AI_Targets.csv",)),
    ("history", "Age and historian events", False, True, ("Historian.csv",)),
    ("production", "Settlement build queues", False, True, ("CityBuildQueue.csv",)),
    ("combat", "Combat results", False, True, ("CombatLog.csv",)),
    ("gossip", "Observed world events", False, True, ("Game_Gossip.csv",)),
    ("tactical", "Tactical unit positions and plans", False, True,
     ("UnitOperations.log", "AI_Tactical.csv", "AI_Operation.csv", "AI_CombatPlanning.csv",
      "AI_Operation_Eval.csv", "AI_UnitEfficiency.csv", "AI_MayhemTracker.csv",
      "AI_Commander_Promotions.csv")),
    ("identity", "Leader and civilization identity", False, False, ("GameCore.log",)),
)

# Why the advisor decided it is looking at a different game than before. Anything other
# than a plain continuation must not silently inherit the previous session's state.
FIRST_LOAD = "first_load"
LOGS_WIPED = "logs_wiped"
DIFFERENT_SAVE = "different_save"
TURN_WENT_BACKWARDS = "turn_went_backwards"


@dataclass(frozen=True)
class DomainCoverage:
    """How well one capability's log files covered the turn we analyzed.

    `status` separates the three failures the player needs told apart:
      unavailable — nothing in this domain is readable (missing or malformed);
      partial     — some files are readable and some are not;
      empty       — readable, but the game has written no rows yet;
      stale       — rows exist, but none of them reach the analysis turn;
      ok          — rows reach the analysis turn, or the domain is not turn-scoped.

    "stale" is a statement about coverage, not a fault: episodic logs such as commander
    promotions legitimately have nothing to say on most turns, which is why
    `latest_turn` and `lag` ship alongside so the UI can date the gap instead of
    alarming about it.
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


@dataclass(frozen=True)
class Snapshot:
    """One coherent capture. Never mutated after publication."""

    schema_version: int
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

    @property
    def in_progress(self) -> bool:
        return self.latest_turn > self.analysis_turn

    def domain(self, name: str) -> DomainCoverage | None:
        return next((c for c in self.coverage if c.name == name), None)


def _coverage(state: GameState, analysis_turn: int) -> tuple[DomainCoverage, ...]:
    out = []
    for name, label, required, turn_scoped, names in DOMAINS:
        statuses = [state.files[n] for n in names if n in state.files]
        readable = [f for f in statuses if f.ok]
        missing = tuple(f.name for f in statuses if not f.ok)
        errors = tuple(f.error for f in statuses if not f.ok and f.error)
        rows = sum(f.rows for f in readable)
        turns = [f.latest_turn for f in readable if f.latest_turn is not None]
        latest = max(turns) if turns else None
        if not readable:
            status = "unavailable"
        elif missing:
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
            errors=errors,
        ))
    return tuple(out)


class Store:
    def __init__(self, logs_dir: Path, archive_root: Path | None = None,
                 commentary_worker: CommentaryWorker | None = None,
                 identity_provider: Callable[[Snapshot], dict] | None = None) -> None:
        # `identity_provider` supplies the decision, context and catalog revisions that
        # complete a generation's identity. It is a hook rather than an import so this
        # module stays free of the decisions package, and so a store with no decision
        # layer still works — the identity is then simply less specific.
        self.identity_provider = identity_provider
        self.logs_dir = logs_dir
        self.archive_root = archive_root
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

    def rebuild(self) -> Snapshot:
        """Re-read every log, archive it, and recompute advice. Safe to call from a worker thread."""
        raw = load_logs(self.logs_dir)
        state = build_state(raw)
        insights = run_all(state)
        key = game_key(self.logs_dir)
        with self._lock:
            snapshot = self._capture_locked(raw, state, insights, key)
            self.snapshot = snapshot
        self._archive(raw, snapshot.session)
        if self.commentary_worker is not None:
            self.commentary_worker.schedule(snapshot, revisions=self.revisions(snapshot))
        return snapshot

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
                        key: str | None) -> Snapshot:
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
            session=self._session, epoch=self._epoch, epoch_reason=self._session_reason,
            game_key=self._observed_key, revision=self._revision, captured_at=time.time(),
            latest_turn=state.latest_turn, analysis_turn=state.complete_through_turn,
            state=state, insights=tuple(insights),
            coverage=_coverage(state, state.complete_through_turn),
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

    def _archive(self, raw: RawLogs, session: str) -> None:
        if self.archive_root is None:
            return
        if not raw.stats:
            return
        try:
            key = self._observed_key or UNKNOWN_GAME
            names = sorted(p.name for p in self.logs_dir.iterdir() if p.suffix in ARCHIVE_SUFFIXES)
            archive_logs(self.logs_dir, self.archive_root / key / session, names)
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
