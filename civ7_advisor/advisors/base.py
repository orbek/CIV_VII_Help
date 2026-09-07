"""Shared vocabulary for advisors."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class Provenance(Enum):
    FAIR = "fair"      # derivable from what the player can see in-game
    ORACLE = "oracle"  # uses AI-internal data the game hides


class Severity(IntEnum):
    INFO = 0
    ADVISE = 1
    WARN = 2
    CRITICAL = 3


@dataclass(frozen=True)
class Insight:
    id: str             # stable key, e.g. "threat.war_intent.1"
    advisor: str        # "threat" | "victory" | "economy"
    severity: Severity
    provenance: Provenance
    title: str
    recommendation: str
    why: str            # the evidence, in plain language, with the numbers
    turn: int           # complete_through_turn it was computed on
    subject_player: int | None = None


_DOMAIN_PREFIXES = ("GOSSIP_", "DISTRICT_", "UNIT_", "BUILDING_", "IMPROVEMENT_", "WONDER_")


def humanize(key: str) -> str:
    """Turn a game key into words: LOC_DISTRICT_CITY_CENTER_NAME -> 'City Center',
    GOSSIP_UNIT_DESTROYED -> 'Unit Destroyed'. Strips LOC_, then exactly ONE domain prefix —
    stripping repeatedly would eat the UNIT_ inside GOSSIP_UNIT_DESTROYED."""
    s = key.removeprefix("LOC_")
    for prefix in _DOMAIN_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.removesuffix("_NAME").replace("_", " ").title()
