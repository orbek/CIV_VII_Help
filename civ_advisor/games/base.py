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


@dataclass(frozen=True)
class LogReader:
    """One log file and the function that turns it into typed rows.

    `attr` is the RawLogs field the rows are stored on, so two games can feed the
    same canonical field from differently-named files.
    """

    filename: str
    attr: str
    read: Callable[[Path], list]


@dataclass(frozen=True)
class GameProfile:
    """Everything about a game that the rest of the advisor must not hard-code."""

    id: str                             # "civ6" | "civ7"; matches --game and the archive path
    display_name: str                   # "Civilization VII"
    default_logs_dir: Path
    readers: tuple[LogReader, ...]
    knowledge_package: str              # importable package holding this game's guides.json
    capabilities: frozenset[Capability] = frozenset()

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    @property
    def log_files(self) -> tuple[str, ...]:
        """Declared file names, in reader order. This is what the poller watches, so a
        file this game never writes is simply never declared and never reported."""
        return tuple(r.filename for r in self.readers)
