"""Which game is being played, decided from the games' own gameplay logs.

Only files a profile DECLARES are stat'ed. Both engines rewrite engine and
diagnostic logs when they launch, so an undeclared file is exactly the thing
that could make a main-menu process look like a game in progress.

Nothing here opens a file: every answer comes from stat(), and both games'
directories stay read-only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .base import GameProfile

RECENCY_WINDOW_S = 600.0   # 10 minutes: long enough to survive a slow turn, short
                           # enough that yesterday's session is not mistaken for now

DETECTED = "detected"          # one game is freshest and inside the window
# No registered game has EVER written a declared log: covers both "no logs directory
# exists at all" and "the directory exists but nothing in it has been played" -- those
# are genuinely different situations for a player (not installed vs. installed but
# untouched), and that distinction is NOT collapsed here: `Candidate.present` still
# says which one it was, per game, for whoever renders the reason.
NO_CANDIDATES = "no_candidates"
ALL_STALE = "all_stale"        # candidates exist, none written inside the window
AMBIGUOUS = "ambiguous"        # two candidates share the freshest timestamp exactly


@dataclass(frozen=True)
class Candidate:
    """One game's freshest declared gameplay log, or the absence of one."""

    game_id: str
    logs_dir: Path
    present: bool          # the logs directory exists
    newest: float | None   # mtime of the freshest declared log; None when there is none
    age: float | None      # seconds since `newest`, at the moment of the scan


@dataclass(frozen=True)
class Detection:
    """What the scan concluded, and everything it saw.

    `game_id` is None when the honest answer is that it cannot tell. `candidates`
    ships regardless so the header can say WHY — "Civ VI last wrote 4 hours ago"
    is a usable statement; a blank one is not.
    """

    game_id: str | None
    reason: str
    candidates: tuple[Candidate, ...]
    at: float

    def candidate(self, game_id: str) -> Candidate | None:
        return next((c for c in self.candidates if c.game_id == game_id), None)


def newest_declared_log(logs_dir: Path, profile: GameProfile) -> float | None:
    """The newest mtime among the files this profile declares, or None if none exist."""
    newest: float | None = None
    for name in profile.log_files:
        try:
            mtime = (logs_dir / name).stat().st_mtime
        except OSError:          # missing, or unreadable: not evidence of play either way
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


def detect(profiles: Iterable[GameProfile], *, logs_dirs: Mapping[str, Path] | None = None,
           now: float | None = None, window: float = RECENCY_WINDOW_S) -> Detection:
    """Which game is being played, from one stat() sweep of every declared log."""
    at = time.time() if now is None else now
    overrides = logs_dirs or {}
    candidates: list[Candidate] = []
    for profile in profiles:
        logs_dir = overrides.get(profile.id, profile.default_logs_dir)
        try:
            present = logs_dir.is_dir()
        except OSError:      # unreachable (e.g. permission denied on an ancestor): not
            present = False  # evidence of play either way, same treatment as absent
        newest = newest_declared_log(logs_dir, profile) if present else None
        candidates.append(Candidate(
            game_id=profile.id, logs_dir=logs_dir, present=present, newest=newest,
            age=None if newest is None else at - newest,
        ))
    found = tuple(sorted(candidates, key=lambda c: c.game_id))
    live = [c for c in found if c.newest is not None]
    if not live:
        return Detection(None, NO_CANDIDATES, found, at)
    fresh = [c for c in live if c.age is not None and c.age <= window]
    if not fresh:
        # Deliberately NOT "the least stale". Picking one here would attach a whole
        # dashboard to a game nobody is playing, on evidence that says nothing.
        return Detection(None, ALL_STALE, found, at)
    best = max(c.newest for c in fresh if c.newest is not None)
    winners = [c for c in fresh if c.newest == best]
    if len(winners) > 1:
        return Detection(None, AMBIGUOUS, found, at)
    return Detection(winners[0].game_id, DETECTED, found, at)


__all__ = ["ALL_STALE", "AMBIGUOUS", "Candidate", "DETECTED", "Detection", "NO_CANDIDATES",
           "RECENCY_WINDOW_S", "detect", "newest_declared_log"]
