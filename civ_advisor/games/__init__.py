"""Per-game profiles. Importing this package registers every game this build supports."""
from __future__ import annotations

from .base import GameProfile, LogReader
from .registry import UnknownGame, get_profile, profile_ids, register

__all__ = [
    "GameProfile", "LogReader", "UnknownGame", "get_profile", "profile_ids", "register",
]

# Task 3 appends the line that imports and registers civ7 here, at the bottom:
# each game package imports .base, so importing one from the top of this module
# would be circular.
