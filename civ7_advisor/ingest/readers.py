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


# --- Player_Treasury.csv ---------------------------------------------------

TREASURY_HEADER = [
    "Turn", "Player", "Gold Balance", "Unit Maintenance",
    "Building Maintenance", "Total Maintenance", "Gold Yield",
]


@dataclass(frozen=True)
class TreasuryRow:
    turn: int
    player: int
    gold_balance: float
    unit_maintenance: int
    building_maintenance: int
    total_maintenance: int
    gold_yield: float


def read_treasury(path: Path) -> list[TreasuryRow]:
    table = read_table(path)
    expect_header(table, TREASURY_HEADER)
    return [
        TreasuryRow(int(r[0]), int(r[1]), float(r[2]), int(r[3]), int(r[4]), int(r[5]), float(r[6]))
        for r in latest_game_segment(table.rows, turn_col=0)
    ]


# --- Player_Happiness.csv (majors only) ------------------------------------

HAPPINESS_HEADER = [
    "Game Turn", "Player", "Golden Age", "Threshold",
    "Total Happiness", "Per Turn Happiness", "Happiness Bonus",
]


@dataclass(frozen=True)
class HappinessRow:
    turn: int
    player: int
    golden_age: bool
    threshold: int
    total: int
    per_turn: int
    bonus: int


def read_happiness(path: Path) -> list[HappinessRow]:
    table = read_table(path)
    expect_header(table, HAPPINESS_HEADER)
    return [
        HappinessRow(int(r[0]), int(r[1]), r[2] == "Yes", int(r[3]), int(r[4]), int(r[5]), int(r[6]))
        for r in latest_game_segment(table.rows, turn_col=0)
    ]


# --- AI_Victories.csv (event-based) ----------------------------------------

VICTORIES_HEADER = ["Game Turn", "Player", "Owner", "Strategy", "Status", "Percentage"]


@dataclass(frozen=True)
class VictoryRow:
    turn: int
    player: int
    owner_key: str   # e.g. LOC_LEADER_CONFUCIUS_NAME
    strategy: str    # canonical: SCIENCE, CULTURAL, MILITARY, ECONOMIC, ESPIONAGE
    status: str      # Following | Stopped | Forbidden
    weight: int      # the AI's priority weight for this strategy (NOT progress)


def canonical_strategy(raw: str) -> str:
    """CD_VICTORY_STRATEGY_SCIENCE -> SCIENCE; TRIUMPH_STRATEGY_ALLAGES_ESPIONAGE -> ESPIONAGE."""
    return raw.rsplit("_", 1)[-1]


def read_victories(path: Path) -> list[VictoryRow]:
    table = read_table(path)
    expect_header(table, VICTORIES_HEADER)
    return [
        VictoryRow(int(r[0]), int(r[1]), r[2], canonical_strategy(r[3]), r[4], int(r[5]))
        for r in latest_game_segment(table.rows, turn_col=0)
    ]
