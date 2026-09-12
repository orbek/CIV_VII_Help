"""Which game the advisor is advising on, and how that was decided.

Two mechanisms settle it and their precedence is fixed: an explicit choice wins
over detection, always, and the resolution says so. A pin silently overridden by
detection -- or detection silently overridden by a stale pin -- would make the
advisor's own provenance claims unreliable, which is the one thing it may not be.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .base import GameProfile
from .detect import RECENCY_WINDOW_S, Candidate, detect
from .registry import get_profile, profile_ids

AUTO = "auto"
PINNED = "pinned"


@dataclass(frozen=True)
class Resolution:
    """The active game, plus everything needed to explain the choice in one line.

    `profile` is None only in AUTO mode when detection could not tell. That is a
    real state, not an error: the advisor has no game to advise on and must say so.
    """

    profile: GameProfile | None
    logs_dir: Path | None
    mode: str                  # AUTO | PINNED
    pinned_id: str | None
    detected_id: str | None
    detection_reason: str
    disagrees: bool            # pinned, and detection names a DIFFERENT game
    candidates: tuple[Candidate, ...]

    @property
    def game_id(self) -> str | None:
        return None if self.profile is None else self.profile.id


class GameSelector:
    """Holds the session's pin and re-runs detection on demand."""

    def __init__(self, pinned: str | None = None,
                 logs_dirs: Mapping[str, Path] | None = None,
                 window: float = RECENCY_WINDOW_S,
                 clock: Callable[[], float] = time.time) -> None:
        self._logs_dirs = dict(logs_dirs or {})
        self._window = window
        self._clock = clock
        self._pinned: str | None = None
        if pinned is not None:
            self.pin(pinned)

    @property
    def mode(self) -> str:
        return PINNED if self._pinned is not None else AUTO

    @property
    def pinned_id(self) -> str | None:
        return self._pinned

    def pin(self, game_id: str) -> None:
        """Pin the session to one game. Raises UnknownGame, leaving the pin untouched."""
        get_profile(game_id)       # validate before mutating; a refused pin leaves no trace
        self._pinned = game_id

    def unpin(self) -> None:
        self._pinned = None

    def logs_dir_for(self, profile: GameProfile) -> Path:
        return self._logs_dirs.get(profile.id, profile.default_logs_dir)

    def resolve(self) -> Resolution:
        found = detect((get_profile(g) for g in profile_ids()),
                       logs_dirs=self._logs_dirs, now=self._clock(), window=self._window)
        if self._pinned is not None:
            profile = get_profile(self._pinned)
            return Resolution(
                profile=profile, logs_dir=self.logs_dir_for(profile), mode=PINNED,
                pinned_id=self._pinned, detected_id=found.game_id,
                detection_reason=found.reason,
                # "cannot tell" does not contradict a pin. Only a NAMED other game does.
                disagrees=found.game_id is not None and found.game_id != self._pinned,
                candidates=found.candidates,
            )
        profile = None if found.game_id is None else get_profile(found.game_id)
        return Resolution(
            profile=profile,
            logs_dir=None if profile is None else self.logs_dir_for(profile),
            mode=AUTO, pinned_id=None, detected_id=found.game_id,
            detection_reason=found.reason, disagrees=False, candidates=found.candidates,
        )


__all__ = ["AUTO", "PINNED", "GameSelector", "Resolution"]
