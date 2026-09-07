"""Low-level CSV access shared by every reader."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


class LogFormatError(ValueError):
    """A log file does not have the shape this reader was pinned against."""


@dataclass(frozen=True)
class RawTable:
    path: Path
    header: list[str]
    rows: list[list[str]]  # data rows; every cell stripped of surrounding whitespace


def read_table(path: Path) -> RawTable:
    """Read a Civ VII CSV: header on row 0, cells stripped, blank lines skipped."""
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh, skipinitialspace=True)
        rows = [
            [cell.strip() for cell in row]
            for row in reader
            if any(cell.strip() for cell in row)
        ]
    if not rows:
        raise LogFormatError(f"{path.name}: file is empty")
    return RawTable(path=path, header=rows[0], rows=rows[1:])


def latest_game_segment(rows: list[list[str]], turn_col: int) -> list[list[str]]:
    """Keep only the rows from the most recent game.

    Civ VII appends to the same log across games and never truncates it, so
    the turn column climbs, drops back when a new game starts, and climbs
    again. The newest game is everything after the last drop.
    """
    start = 0
    prev: int | None = None
    for index, row in enumerate(rows):
        try:
            turn = int(row[turn_col])
        except (IndexError, ValueError):
            continue
        if prev is not None and turn < prev:
            start = index
        prev = turn
    return rows[start:]


def expect_header(table: RawTable, expected: list[str]) -> None:
    if table.header != expected:
        raise LogFormatError(
            f"{table.path.name}: unexpected header {table.header!r}; "
            f"this version of civ7-advisor expects {expected!r}"
        )
