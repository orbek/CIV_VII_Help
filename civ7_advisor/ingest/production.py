"""Reader for CityBuildQueue.csv: what every player is producing, and how long it will take."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from .csvfile import expect_header, latest_game_segment, read_table

BUILD_QUEUE_HEADER = [
    "Game Turn", "Player", "City", "Production Added", "Current Item",
    "Current Production", "Production Needed", "Overflow",
]


@dataclass(frozen=True)
class BuildQueueRow:
    turn: int
    player: int
    city: str        # LOC_CITY_NAME_* key exactly as logged
    added: float     # production added this turn
    item: str        # BUILDING_*, UNIT_*, ...; "" when the city is idle
    current: float
    needed: float
    overflow: float

    @property
    def turns_to_complete(self) -> int | None:
        """Whole turns until `needed` is reached at the current rate.

        None when the city is idle or adds no production (a stall we must not divide by).
        """
        if not self.item or self.added <= 0:
            return None
        remaining = self.needed - self.current
        return 0 if remaining <= 0 else math.ceil(remaining / self.added)


def read_build_queue(path: Path) -> list[BuildQueueRow]:
    table = read_table(path)
    expect_header(table, BUILD_QUEUE_HEADER)
    return [
        BuildQueueRow(int(r[0]), int(r[1]), r[2], float(r[3]), r[4], float(r[5]), float(r[6]), float(r[7]))
        for r in latest_game_segment(table.rows, turn_col=0)
    ]
