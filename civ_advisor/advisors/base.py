"""Shared vocabulary for advisors."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Iterable, Protocol, TypeVar


class Provenance(Enum):
    FAIR = "fair"      # derivable from what the player can see in-game
    ORACLE = "oracle"  # uses AI-internal data the game hides


class Severity(IntEnum):
    INFO = 0
    ADVISE = 1
    WARN = 2
    CRITICAL = 3


class HasProvenance(Protocol):
    provenance: Provenance


T = TypeVar("T", bound=HasProvenance)


@dataclass(frozen=True)
class Insight:
    id: str             # stable key, e.g. "threat.war_intent.1"
    advisor: str        # "threat" | "victory" | "economy" | "production"
    severity: Severity
    provenance: Provenance
    title: str
    recommendation: str
    why: str            # the evidence, in plain language, with the numbers
    turn: int           # complete_through_turn it was computed on
    subject_player: int | None = None


def visible(items: Iterable[T], oracle: bool) -> list[T]:
    """Drop Oracle-provenance items unless the player asked to see intercepts.

    One place decides what "fair mode" means for insights, intel events and anything
    else carrying a `provenance`, so a serializer, a model prompt and a decision cannot
    each filter slightly differently. Filtering has to happen before the data is used,
    not after: a comparison computed from an Oracle fact is itself Oracle, so removing
    the sentence that mentions it is not enough.
    """
    return [i for i in items if oracle or i.provenance is Provenance.FAIR]


_DOMAIN_PREFIXES = ("GOSSIP_", "DISTRICT_", "UNIT_", "BUILDING_", "IMPROVEMENT_",
                    "WONDER_", "TECH_", "CIVIC_", "POLICY_")


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
