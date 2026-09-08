"""Readers for Civ VII's tactical AI logs.

Several of these are diagnostic CSV streams rather than strict tables: rows grow
extra comma-separated cells as the AI appends notes.  The readers therefore pin
the stable leading columns and retain/reconstruct the remainder deliberately.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from .csvfile import LogFormatError, latest_game_segment

UNIT_RE = re.compile(r"^(UNIT_[A-Z0-9_]+) \((\d+)\)$")
TARGET_UNIT_RE = re.compile(r"^(UNIT_[A-Z0-9_]+) \((\d+):(\d+)\)$")
SPACE_COORD_RE = re.compile(r"(?:Move To|Fortify|Move|Attack|At):?\s+(\d+)\s+(\d+)")
COLON_COORD_RE = re.compile(r"(?:TARGET|Goal|Start|End|Move)?\s*(\d+):(\d+)")


def _rows(path: Path, header: list[str]) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = [[cell.strip() for cell in row] for row in csv.reader(f)]
    if not rows:
        raise LogFormatError(f"{path.name}: empty file")
    if rows[0] != header:
        raise LogFormatError(f"{path.name}: expected header {header!r}, got {rows[0]!r}")
    return latest_game_segment(rows[1:], turn_col=0)


def _unit(cell: str) -> tuple[str, int]:
    match = UNIT_RE.fullmatch(cell)
    if not match:
        raise ValueError(f"invalid unit cell {cell!r}")
    return match.group(1), int(match.group(2))


def _coords(cells: list[str], pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    return [(int(x), int(y)) for cell in cells for x, y in pattern.findall(cell)]


@dataclass(frozen=True)
class UnitOperationRow:
    turn: int
    mode: str
    player: int
    unit_type: str
    unit_id: int
    operation: str


def read_unit_operations(path: Path) -> list[UnitOperationRow]:
    rows = _rows(path, ["Game Turn", "Mode", "Player", "Unit", "Operation"])
    out = []
    for row in rows:
        unit_type, unit_id = _unit(row[3])
        out.append(UnitOperationRow(int(row[0]), row[1], int(row[2]), unit_type, unit_id, row[4]))
    return out


@dataclass(frozen=True)
class TacticalRow:
    turn: int
    player: int
    category: str
    target_type: str
    target_unit_type: str | None
    target_unit_id: int | None
    target_owner: int | None
    unit_type: str
    unit_id: int
    move: tuple[int, int] | None
    attack: tuple[int, int] | None
    extra: tuple[str, ...]


def read_tactical(path: Path) -> list[TacticalRow]:
    rows = _rows(path, ["Game Turn", "Player", "Category", "Target Type", "Target Info", "Unit Info", "Extra"])
    out = []
    for row in rows:
        if len(row) < 6:
            raise ValueError(f"short tactical row: {row!r}")
        unit_type, unit_id = _unit(row[5])
        target_type = target_id = target_owner = None
        match = TARGET_UNIT_RE.fullmatch(row[4])
        if match:
            target_type, target_id, target_owner = match.group(1), int(match.group(2)), int(match.group(3))
        extra = row[6:]
        found = _coords(extra, SPACE_COORD_RE)
        move = found[0] if found else None
        attack = found[1] if len(found) > 1 and "Attack" in " ".join(extra) else None
        out.append(TacticalRow(
            int(row[0]), int(row[1]), row[2], row[3], target_type, target_id, target_owner,
            unit_type, unit_id, move, attack, tuple(extra),
        ))
    return out


@dataclass(frozen=True)
class OperationRow:
    turn: int
    player: int
    operation: str
    goal: tuple[int, int] | None
    notes: tuple[str, ...]


def read_operations(path: Path) -> list[OperationRow]:
    rows = _rows(path, ["Game Turn", "Player", "Operation", "Notes", "Team", "Team Notes", "Team Members", "Terrain"])
    out = []
    for row in rows:
        if len(row) < 3:
            raise ValueError(f"short operation row: {row!r}")
        # "Battle line" diagnostic rows swap the Operation and Player cells.
        if row[1].isdigit():
            player, operation = int(row[1]), row[2]
        elif row[2].isdigit():
            player, operation = int(row[2]), row[1]
        else:
            raise ValueError(f"operation row has no player id: {row!r}")
        notes = row[3:]
        goals = _coords([c for c in notes if c.startswith(("Goal ", "TARGET "))], COLON_COORD_RE)
        if not goals and len(notes) >= 2 and notes[0] == "Started":
            goals = _coords(notes[1:2], COLON_COORD_RE)
        out.append(OperationRow(int(row[0]), player, operation, goals[0] if goals else None, tuple(notes)))
    return out


@dataclass(frozen=True)
class CombatOrderRow:
    turn: int
    player: int
    category: str
    unit_id: int | None
    move: tuple[int, int] | None
    action: str
    info: tuple[str, ...]

    @property
    def attacks(self) -> bool:
        return "attack" in self.action.lower() and "not" not in self.action.lower()


def read_combat_planning(path: Path) -> list[CombatOrderRow]:
    rows = _rows(path, ["Game Turn", "Player", "Category", "Info"])
    out = []
    for row in rows:
        info = row[3:]
        unit = re.search(r"\bUnit (\d+)", info[0] if info else "")
        moves = _coords(info, COLON_COORD_RE)
        out.append(CombatOrderRow(
            int(row[0]), int(row[1]), row[2], int(unit.group(1)) if unit else None,
            moves[0] if moves else None, info[-1] if row[2] == "Order" and info else "", tuple(info),
        ))
    return out


@dataclass(frozen=True)
class OperationEvalRow:
    turn: int
    player: int
    operation_id: int
    kind: str
    value: float
    odds: float


def read_operation_evals(path: Path) -> list[OperationEvalRow]:
    return [OperationEvalRow(int(r[0]), int(r[1]), int(r[2]), r[3], float(r[4]), float(r[5]))
            for r in _rows(path, ["Game Turn", "Player", "Operation", "Enemy", "Value", "Odds"])]


@dataclass(frozen=True)
class UnitEfficiencyRow:
    turn: int
    attacker: str
    ratings: dict[str, float]


def read_unit_efficiency(path: Path) -> list[UnitEfficiencyRow]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = [[cell.strip() for cell in row] for row in csv.reader(f)]
    if not rows or rows[0][0] != "" or len(rows[0]) < 2:
        raise LogFormatError(f"{path.name}: invalid efficiency matrix header")
    defenders = rows[0][1:]
    if len(rows) - 1 != len(defenders):
        raise LogFormatError(f"{path.name}: efficiency matrix is not square")
    out = []
    for row in rows[1:]:
        if len(row) != len(rows[0]):
            raise ValueError("ragged efficiency matrix")
        out.append(UnitEfficiencyRow(0, row[0], dict(zip(defenders, map(float, row[1:]), strict=True))))
    return out


@dataclass(frozen=True)
class MayhemRow:
    turn: int
    event: str
    attacker: int
    attacker_type: str
    defender: int
    defender_type: str
    mayhem: float
    total: float


def read_mayhem(path: Path) -> list[MayhemRow]:
    return [MayhemRow(int(r[0]), r[1], int(r[2]), r[3], int(r[4]), r[5], float(r[6]), float(r[7]))
            for r in _rows(path, ["Game Turn", "Event", "Attacker", "Unit", "Defender", "Unit", "Mayhem", "Current Total"])]


@dataclass(frozen=True)
class CommanderPromotionRow:
    turn: int
    player: int
    commander: str
    count: int
    discipline: str
    promotion: str


def read_commander_promotions(path: Path) -> list[CommanderPromotionRow]:
    return [CommanderPromotionRow(int(r[0]), int(r[1]), r[2], int(r[3]), r[4], r[5])
            for r in _rows(path, ["Game Turn", "Player", "Commander", "Num Promotions", "Discipline", "Promotion"])]
