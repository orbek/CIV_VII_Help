"""Typed snapshot of the current game. Advisors import only this module."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

from civ7_advisor.ingest.load import FileStatus
from civ7_advisor.ingest.readers import DiplomacyRow, HistorianRow, IntentKind, TargetRow

# Row types advisors need, re-exported under domain names.
DiplomaticIntent = DiplomacyRow
Target = TargetRow
HistorianEvent = HistorianRow

__all__ = [
    "DiplomaticIntent", "FileStatus", "GameState", "HistorianEvent", "IntentKind",
    "Player", "PlayerKind", "PlayerTurn", "StrategyStatus", "Target",
]


class PlayerKind(Enum):
    HUMAN = "human"
    RIVAL = "rival"
    INDEPENDENT = "independent"


@dataclass(frozen=True)
class Player:
    id: int
    name: str
    kind: PlayerKind
    alive: bool
    last_seen_turn: int


@dataclass(frozen=True)
class PlayerTurn:
    """One player's per-turn stats, with treasury and happiness rows merged in when present."""

    turn: int
    player: int
    cities: int
    towns: int
    settlement_cap: int
    settlements_over_cap: int
    urban_pop: int
    rural_pop: int
    techs: int
    land_units: int
    naval_units: int
    tiles_owned: int
    tiles_improved: int
    gold_balance: float
    science: float
    culture: float
    gold: float
    production: float
    food: float
    happiness: float
    diplomacy: float
    unit_maintenance: int | None = None
    building_maintenance: int | None = None
    total_maintenance: int | None = None
    golden_age: bool | None = None
    happiness_threshold: int | None = None
    happiness_total: int | None = None

    @property
    def settlements(self) -> int:
        return self.cities + self.towns

    @property
    def military_units(self) -> int:
        return self.land_units + self.naval_units

    @property
    def net_gold(self) -> float | None:
        if self.total_maintenance is None:
            return None
        return self.gold - self.total_maintenance

    @property
    def celebration_progress(self) -> float | None:
        if not self.happiness_threshold or self.happiness_total is None:
            return None
        return self.happiness_total / self.happiness_threshold


@dataclass(frozen=True)
class StrategyStatus:
    player: int
    strategy: str   # SCIENCE, CULTURAL, MILITARY, ECONOMIC, ESPIONAGE
    status: str     # Following | Stopped | Forbidden
    weight: int     # the AI's priority weight, not progress
    since_turn: int

    @property
    def following(self) -> bool:
        return self.status == "Following"


@dataclass
class GameState:
    players: dict[int, Player] = field(default_factory=dict)
    latest_turn: int = 0
    complete_through_turn: int = 0
    turns: dict[int, dict[int, PlayerTurn]] = field(default_factory=dict)  # turn -> player -> stats
    strategies: dict[int, dict[str, StrategyStatus]] = field(default_factory=dict)  # player -> path
    intents: list[DiplomaticIntent] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)
    events: list[HistorianEvent] = field(default_factory=list)
    files: dict[str, FileStatus] = field(default_factory=dict)

    HUMAN: ClassVar[int] = 0

    def human(self) -> Player | None:
        return self.players.get(self.HUMAN)

    def rivals(self, alive_only: bool = True) -> list[Player]:
        return [
            p for p in sorted(self.players.values(), key=lambda p: p.id)
            if p.kind is PlayerKind.RIVAL and (p.alive or not alive_only)
        ]

    def majors(self) -> list[Player]:
        """The human plus every living rival, human first."""
        human = self.human()
        return ([human] if human else []) + self.rivals()

    def at(self, player: int, turn: int | None = None) -> PlayerTurn | None:
        t = self.complete_through_turn if turn is None else turn
        return self.turns.get(t, {}).get(player)

    def series(self, player: int, attr: str, n: int) -> list[float]:
        """`attr` over the last n complete turns, oldest first; turns without a row are skipped."""
        t = self.complete_through_turn
        out: list[float] = []
        for turn in range(t - n + 1, t + 1):
            pt = self.turns.get(turn, {}).get(player)
            if pt is not None:
                out.append(float(getattr(pt, attr)))
        return out
