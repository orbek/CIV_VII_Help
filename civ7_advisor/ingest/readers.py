"""One reader per Civ VII log file. Each is pure: path in, typed rows out.

Every reader returns rows for the most recent game only (see
csvfile.latest_game_segment) and raises LogFormatError when the file does
not match the shape it was pinned against.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .columns import (
    PLAYER_STATS_COLUMN_COUNT,
    PLAYER_STATS_FLOAT_COLUMNS,
    PLAYER_STATS_INT_COLUMNS,
)
from .csvfile import LogFormatError, expect_header, latest_game_segment, read_table


# --- Player_Stats.csv ------------------------------------------------------


@dataclass(frozen=True)
class StatsRow:
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


def read_player_stats(path: Path) -> list[StatsRow]:
    table = read_table(path)
    out: list[StatsRow] = []
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) != PLAYER_STATS_COLUMN_COUNT:
            raise LogFormatError(
                f"{path.name}: expected {PLAYER_STATS_COLUMN_COUNT} columns but a row has "
                f"{len(row)} (row starts {row[:2]}). The game may have changed its log "
                f"format; update civ7_advisor/ingest/columns.py."
            )
        values = {name: int(row[i]) for name, i in PLAYER_STATS_INT_COLUMNS.items()}
        values |= {name: float(row[i]) for name, i in PLAYER_STATS_FLOAT_COLUMNS.items()}
        out.append(StatsRow(**values))
    return out
