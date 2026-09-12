"""What distinguishes one game from another. Imports no game: see games/__init__.py."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable


class Capability(StrEnum):
    """A signal or panel a game may or may not be able to support.

    Declared per profile rather than inferred from data: a log that is merely
    empty this turn is not the same as a game that has no such concept, and
    only the profile knows which is which.
    """

    VICTORY_PATHS = "victory_paths"
    HAPPINESS = "happiness"
    MAINTENANCE = "maintenance"
    PEACE_DEALS = "peace_deals"
    COMBAT_ODDS = "combat_odds"
    SETTLEMENT_CAP = "settlement_cap"
    URBAN_RURAL_SPLIT = "urban_rural_split"
    FAITH = "faith"
    CIVICS = "civics"
    TOURISM = "tourism"
    DIPLOMATIC_FAVOR = "diplomatic_favor"
    # Civ VI-only, and all AI-internal: anything built from these is ORACLE.
    COMBAT_DESIRE = "combat_desire"                # AI_Military.csv
    DIPLOMATIC_MODIFIERS = "diplomatic_modifiers"  # DiplomacyModifiers.csv
    RESEARCH_PREFERENCE = "research_preference"    # AI_Research.csv
    POLICY_PREFERENCE = "policy_preference"        # AI_GovtPolicies.csv


@dataclass(frozen=True)
class LogReader:
    """One log file and the function that turns it into typed rows.

    `attr` is the RawLogs field the rows are stored on, so two games can feed the
    same canonical field from differently-named files.
    """

    filename: str
    attr: str
    read: Callable[[Path, Path], list]


def simple(fn: Callable[[Path], list]) -> Callable[[Path, Path], list]:
    """Adapt a reader that needs only its own file to the two-argument form."""

    def read(logs_dir: Path, path: Path) -> list:
        return fn(path)

    return read


@dataclass(frozen=True)
class GameProfile:
    """Everything about a game that the rest of the advisor must not hard-code."""

    id: str                             # "civ6" | "civ7"; matches --game and the archive path
    display_name: str                   # "Civilization VII"
    default_logs_dir: Path
    readers: tuple[LogReader, ...]
    knowledge_package: str              # importable package holding this game's guides.json
    capabilities: frozenset[Capability] = frozenset()
    unsupported: tuple[tuple[Capability, str], ...] = ()

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def reason(self, capability: Capability) -> str | None:
        """Why this game cannot support `capability`, or None when it can.

        Required for every capability the profile does not declare: "not available" with
        no reason is indistinguishable from a panel that happens to be empty, and the
        two mean opposite things to a player deciding what to do this turn.
        """
        if self.supports(capability):
            return None
        return next((why for cap, why in self.unsupported if cap is capability), None)

    @property
    def log_files(self) -> tuple[str, ...]:
        """Declared file names, in reader order. This is what the poller watches, so a
        file this game never writes is simply never declared and never reported."""
        return tuple(r.filename for r in self.readers)
