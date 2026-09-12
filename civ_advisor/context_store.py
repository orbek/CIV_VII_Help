"""The player's own record, persisted locally: goals, watchlist entries, acknowledgements.

One JSON file, written atomically, versioned, and scoped by session. Three rules:

  - **A write either lands whole or not at all.** The file is written to a temporary
    sibling and renamed, so a crash mid-write cannot leave a truncated store that reads as
    an empty one.
  - **A damaged store is preserved, not discarded.** If the file cannot be parsed it is
    moved aside and reported, and the advisor carries on with an empty store. Losing the
    player's notes silently would be worse than either.
  - **A different sitting does not inherit plans.** Entries are filed under the session
    they were made in. When the advisor cannot tell whether this is the same game, the old
    entries are offered for explicit association and are not applied until the player says
    so — an acknowledgement carried silently across a reload would hide a live alert.

This is the only place besides the log archive that the advisor writes to disk, and it
writes only inside its own directory.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_STORE_PATH = Path.home() / ".civ7-advisor" / "player-context.json"
SCHEMA_VERSION = 1

GOAL = "goal"              # something the player intends to do
WATCH = "watch"            # something they want kept in view
ACKNOWLEDGED = "acknowledged"  # something they have seen
KINDS = (GOAL, WATCH, ACKNOWLEDGED)


@dataclass(frozen=True)
class Entry:
    """One thing the player recorded.

    `fingerprint` is what the entry was made against — the evidence and severity behind a
    decision. An acknowledgement whose fingerprint no longer matches has not been
    withdrawn; it simply no longer applies, and the decision comes back.
    """

    id: str
    kind: str
    subject: str               # the decision or signal it is about
    session: str
    epoch: int
    turn: int
    created_at: str            # ISO
    text: str = ""             # the player's own words, for a goal
    fingerprint: str = ""
    game_key: str | None = None  # the save's seeds when known, for association

    def to_json(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Association:
    """Entries from another sitting that could belong to this game, offered explicitly."""

    session: str
    epoch: int
    game_key: str | None
    entries: tuple[Entry, ...]
    reason: str

    @property
    def count(self) -> int:
        return len(self.entries)


class StoreError(Exception):
    """The store could not be read or written. Always recoverable: the caller continues
    with whatever it has and reports this."""


@dataclass
class PersistentContextStore:
    """Goals, watchlist entries and acknowledgements that survive a restart."""

    path: Path = DEFAULT_STORE_PATH
    revision: int = 0
    entries: dict[str, Entry] = field(default_factory=dict)
    session: str | None = None
    epoch: int = 0
    game_key: str | None = None
    # Entries from other sittings, held back until the player associates them.
    pending: tuple[Association, ...] = ()
    last_error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---- loading -----------------------------------------------------------------

    def load(self) -> None:
        """Read the store. A damaged file is moved aside and reported, never dropped."""
        with self._lock:
            self.last_error = None
            if not self.path.is_file():
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.last_error = self._quarantine(exc)
                return
            if raw.get("schema_version") != SCHEMA_VERSION:
                self.last_error = (
                    f"The saved player context is version {raw.get('schema_version')!r}, "
                    f"not {SCHEMA_VERSION}. It has been left alone and this session starts "
                    "with an empty record.")
                return
            try:
                loaded = [Entry(**row) for row in raw.get("entries", [])]
            except TypeError as exc:
                self.last_error = self._quarantine(exc)
                return
            self._loaded = tuple(loaded)
            self.revision = int(raw.get("revision", 0))

    def _quarantine(self, exc: Exception) -> str:
        """Move an unreadable store aside so it can be recovered by hand."""
        aside = self.path.with_suffix(f".broken-{int(time.time())}.json")
        try:
            self.path.replace(aside)
            where = f" It has been moved to {aside.name} so nothing is lost."
        except OSError:
            where = " It could not be moved aside; leave it in place and inspect it."
        log.warning("player context store unreadable: %s", exc)
        return (f"The saved player context could not be read ({exc}).{where} This session "
                "starts with an empty record.")

    # ---- session association -----------------------------------------------------

    def adopt(self, session: str, epoch: int, game_key: str | None,
              epoch_reason: str = "") -> None:
        """Point the store at the current sitting.

        Entries made in this exact session apply immediately. Entries from any other are
        held in `pending` for the player to associate or discard: after a reload the
        advisor cannot tell whether this is the same line of play, and the same seeds do
        not settle it because a save can be branched.
        """
        with self._lock:
            if (self.session, self.epoch) == (session, epoch):
                return   # already pointed here; recomputing would discard what is held
            held = getattr(self, "_loaded", ())
            self.session, self.epoch, self.game_key = session, epoch, game_key
            mine = {e.id: e for e in list(held) + list(self.entries.values())
                    if e.session == session and e.epoch == epoch}
            others = [e for e in list(held) + list(self.entries.values())
                      if not (e.session == session and e.epoch == epoch)]
            self.entries = mine
            groups: dict[tuple[str, int], list[Entry]] = {}
            for entry in others:
                groups.setdefault((entry.session, entry.epoch), []).append(entry)
            self.pending = tuple(
                Association(
                    session=key[0], epoch=key[1],
                    game_key=next((e.game_key for e in rows if e.game_key), None),
                    entries=tuple(sorted(rows, key=lambda e: e.id)),
                    reason=_association_reason(rows, game_key, epoch_reason),
                )
                for key, rows in sorted(groups.items())
            )
            self._loaded = ()

    def associate(self, session: str, epoch: int) -> tuple[Entry, ...]:
        """Adopt one held group into this sitting, because the player said to.

        The entries are re-filed under the current session: they are now this game's
        record, and their original sitting is not resurrected.
        """
        with self._lock:
            if self.session is None:
                raise StoreError("no current session to associate entries with")
            group = next((a for a in self.pending
                          if a.session == session and a.epoch == epoch), None)
            if group is None:
                raise StoreError(f"no held entries for session {session!r} epoch {epoch}")
            adopted = []
            for entry in group.entries:
                moved = replace(entry, session=self.session, epoch=self.epoch)
                self.entries[moved.id] = moved
                adopted.append(moved)
            self.pending = tuple(a for a in self.pending if a is not group)
            self.revision += 1
            self._save_locked()
            return tuple(adopted)

    def discard(self, session: str, epoch: int) -> int:
        with self._lock:
            group = next((a for a in self.pending
                          if a.session == session and a.epoch == epoch), None)
            if group is None:
                return 0
            self.pending = tuple(a for a in self.pending if a is not group)
            self.revision += 1
            self._save_locked()
            return group.count

    # ---- writing -----------------------------------------------------------------

    def record(self, kind: str, subject: str, turn: int, *, text: str = "",
               fingerprint: str = "", entry_id: str | None = None) -> Entry:
        with self._lock:
            if kind not in KINDS:
                raise StoreError(f"{kind!r} is not one of {', '.join(KINDS)}")
            if self.session is None:
                raise StoreError("the store has no current session")
            entry = Entry(
                id=entry_id or f"{kind}:{self.session}:{subject}",
                kind=kind, subject=subject, session=self.session, epoch=self.epoch,
                turn=turn, created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                text=text, fingerprint=fingerprint, game_key=self.game_key,
            )
            self.entries[entry.id] = entry
            self.revision += 1
            self._save_locked()
            return entry

    def forget(self, entry_id: str) -> bool:
        with self._lock:
            if self.entries.pop(entry_id, None) is None:
                return False
            self.revision += 1
            self._save_locked()
            return True

    def of_kind(self, kind: str) -> tuple[Entry, ...]:
        return tuple(sorted((e for e in self.entries.values() if e.kind == kind),
                            key=lambda e: e.id))

    def applies(self, subject: str, fingerprint: str, kind: str = ACKNOWLEDGED) -> bool:
        """Whether an entry still applies to what is on screen now.

        A fingerprint mismatch means the evidence or severity behind the decision moved,
        so the entry does not apply and the decision resurfaces.
        """
        return any(e.subject == subject and e.kind == kind and e.fingerprint == fingerprint
                   for e in self.entries.values())

    def _save_locked(self) -> None:
        """Write the whole store atomically. A failure is reported, never fatal."""
        payload = {
            "schema_version": SCHEMA_VERSION,
            "revision": self.revision,
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "entries": [e.to_json() for e in
                        sorted(list(self.entries.values())
                               + [x for a in self.pending for x in a.entries],
                               key=lambda e: (e.session, e.epoch, e.id))],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent,
                prefix=self.path.name + ".", suffix=".tmp", delete=False)
            try:
                with handle:
                    json.dump(payload, handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                # Rename over the target: either the old file or the new one, never half.
                os.replace(handle.name, self.path)
            except BaseException:
                Path(handle.name).unlink(missing_ok=True)
                raise
            self.last_error = None
        except OSError as exc:
            log.warning("could not save player context: %s", exc)
            self.last_error = (
                f"This session's goals and acknowledgements could not be saved ({exc}). "
                "They are still in effect for now but will not survive a restart.")


def _association_reason(entries: list[Entry], game_key: str | None,
                        epoch_reason: str) -> str:
    """Why these entries are being offered rather than applied."""
    theirs = next((e.game_key for e in entries if e.game_key), None)
    same_save = theirs is not None and game_key is not None and theirs == game_key
    turns = sorted(e.turn for e in entries)
    span = f"turn {turns[0]}" if turns[0] == turns[-1] else f"turns {turns[0]}–{turns[-1]}"
    lead = f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} from {span}"
    if same_save:
        return (f"{lead}, recorded against the same save seeds. The same save can be "
                "branched, so this is not proof it is the same line of play — associate "
                "them only if it is.")
    if theirs is None or game_key is None:
        return (f"{lead}, from a sitting whose save could not be identified. Associate "
                "them only if you know they belong to this game.")
    return (f"{lead}, recorded against different save seeds ({theirs}). They almost "
            "certainly belong to another game.")


__all__ = ["ACKNOWLEDGED", "Association", "DEFAULT_STORE_PATH", "Entry", "GOAL", "KINDS",
           "PersistentContextStore", "SCHEMA_VERSION", "StoreError", "WATCH"]
