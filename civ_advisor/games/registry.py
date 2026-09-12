"""The set of games this build can advise on."""
from __future__ import annotations

from .base import GameProfile


class UnknownGame(KeyError):
    """Asked for a game this build does not have a profile for."""

    def __str__(self) -> str:  # KeyError's repr would quote the message
        return self.args[0]


_PROFILES: dict[str, GameProfile] = {}


def register(profile: GameProfile) -> None:
    """Add a profile. Refuses a duplicate id: a silent overwrite would make the
    active profile depend on import order."""
    if profile.id in _PROFILES:
        raise ValueError(f"a profile for {profile.id!r} is already registered")
    _PROFILES[profile.id] = profile


def get_profile(game_id: str) -> GameProfile:
    if game_id not in _PROFILES:
        known = ", ".join(sorted(_PROFILES)) or "none"
        raise UnknownGame(f"unknown game {game_id!r}; this build knows: {known}")
    return _PROFILES[game_id]


def profile_ids() -> tuple[str, ...]:
    return tuple(sorted(_PROFILES))
