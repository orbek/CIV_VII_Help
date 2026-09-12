"""Per-game profiles. Importing this package registers every game this build supports."""
from __future__ import annotations

from .base import GameProfile, LogReader
from .registry import UnknownGame, get_profile, profile_ids, register

__all__ = [
    "GameProfile", "LogReader", "UnknownGame", "get_profile", "profile_ids", "register",
]

# Imported for the side effect of registering. Must come last: each game package
# imports .base, so importing one from the top of this module would be circular.
from . import civ7  # noqa: E402,F401
from . import civ6  # noqa: E402,F401
