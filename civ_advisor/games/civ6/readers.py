"""Readers for the Civ VI logs whose columns differ from Civ VII's.

Each maps into the SAME row dataclass Civ VII's reader produces, leaving
every field Civ VI cannot supply as None. See spec §3.2.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

from civ_advisor.ingest.csvfile import LogFormatError, latest_game_segment, read_table
from civ_advisor.ingest.production import BuildQueueRow
from civ_advisor.ingest.readers import StatsRow
from civ_advisor.ingest.tactical import UnitOperationRow, _unit
from civ_advisor.ingest.textlogs import read_player_identities

from .columns import (
    PLAYER_STATS_CIV_COLUMN,
    PLAYER_STATS_COLUMN_COUNT,
    PLAYER_STATS_FLOAT_COLUMNS,
    PLAYER_STATS_INT_COLUMNS,
)

IDENTITY_FILE = "GameCore.log"


def _player_by_civilization(logs_dir: Path) -> dict[str, int]:
    """civilization string -> player id, from GameCore.log (spec §5).

    A civilization fielded by two players maps to NEITHER: its rows cannot be
    attributed, and guessing one would misfile every observation about that
    rival. Missing or unreadable file returns {}, so rows go unattributed
    rather than wrongly attributed.
    """
    path = logs_dir / IDENTITY_FILE
    if not path.is_file():
        return {}
    try:
        identities = read_player_identities(path)
    except (LogFormatError, ValueError, IndexError, OSError):
        return {}
    counts: dict[str, int] = {}
    for row in identities:
        counts[row.civilization] = counts.get(row.civilization, 0) + 1
    return {r.civilization: r.player for r in identities if counts[r.civilization] == 1}


def read_player_stats_civ6(logs_dir: Path, path: Path) -> list[StatsRow]:
    players = _player_by_civilization(logs_dir)
    table = read_table(path)
    out: list[StatsRow] = []
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) != PLAYER_STATS_COLUMN_COUNT:
            raise LogFormatError(
                f"{path.name}: expected {PLAYER_STATS_COLUMN_COUNT} columns but a row "
                f"has {len(row)} (row starts {row[:2]}). The game may have changed its "
                f"log format; update civ_advisor/games/civ6/columns.py."
            )
        values: dict = {name: int(row[i]) for name, i in PLAYER_STATS_INT_COLUMNS.items()}
        values |= {name: float(row[i]) for name, i in PLAYER_STATS_FLOAT_COLUMNS.items()}
        player = players.get(row[PLAYER_STATS_CIV_COLUMN])
        if player is None:
            # Unattributable: cannot be filed under a player at all. Dropped
            # rather than filed under player 0, which would put a rival's
            # figures on the player's own dashboard.
            log.warning("%s: no player for civilization %r; dropping its rows",
                        path.name, row[PLAYER_STATS_CIV_COLUMN])
            continue
        # Every Civ VII-only field is left at its None default, not zeroed.
        out.append(StatsRow(player=player, **values))
    return out


# Civ VI interleaves handler diagnostics among the data rows, e.g.
# "Unit operation handler a92585ad, is disabled". Only this exact shape is
# skipped; any other malformed row still raises, because silently dropping
# short rows would turn a broken log into quiet data loss.
_DIAGNOSTIC = re.compile(r"^Unit operation handler [0-9a-f]+$")


def read_unit_operations_civ6(logs_dir: Path, path: Path) -> list[UnitOperationRow]:
    table = read_table(path)
    out: list[UnitOperationRow] = []
    # Civ VII deletes its Logs/ directory on every launch, so this file rarely spans
    # two games there. Civ VI never truncates it: it accumulates across every game
    # ever played, so without segmenting to the latest game, a second match would
    # read the first match's unit operations as its own. A diagnostic row's turn
    # cell ("Unit operation handler <hex>") fails int() and is skipped by
    # latest_game_segment without disturbing the segment boundary it's tracking.
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) == 2 and _DIAGNOSTIC.match(row[0]):
            continue
        if len(row) != 5:
            raise LogFormatError(
                f"{path.name}: expected 5 columns but a row has {len(row)}: {row!r}"
            )
        unit_type, unit_id = _unit(row[3])
        out.append(UnitOperationRow(int(row[0]), row[1], int(row[2]), unit_type, unit_id, row[4]))
    return out


OWNERSHIP_FILE = "AI_CityBuild.csv"
# AI_CityBuild's City column carries this instead of a city name on some rows.
PURCHASE_SENTINEL = "PURCHASE"


def _ownership_by_turn(logs_dir: Path) -> dict[str, list[tuple[int, int]]]:
    """city -> [(turn, player), ...] ascending, from AI_CityBuild.csv.

    Missing or unreadable: returns {}, so every queue row is reported
    unattributed rather than attributed wrongly.
    """
    path = logs_dir / OWNERSHIP_FILE
    if not path.is_file():
        return {}
    try:
        table = read_table(path)
    except (LogFormatError, ValueError, IndexError):
        return {}
    seen: dict[str, list[tuple[int, int]]] = {}
    for row in table.rows:
        if len(row) < 3:
            continue
        city = row[2].strip()
        if not city or city == PURCHASE_SENTINEL:
            continue
        try:
            turn, player = int(row[0]), int(row[1])
        except ValueError:
            continue
        seen.setdefault(city, []).append((turn, player))
    for entries in seen.values():
        entries.sort()
    return seen


def _owner_at(entries: list[tuple[int, int]], turn: int) -> int | None:
    """The most recent owner observed at or before `turn`.

    Carried forward rather than matched exactly: AI_CityBuild logs only about
    a quarter of (turn, city) pairs. Carrying forward is also what makes a
    capture read correctly -- ownership changes at the turn the file next
    reports a different player, and earlier rows keep the previous owner.
    """
    owner = None
    for entry_turn, player in entries:
        if entry_turn > turn:
            break
        owner = player
    return owner


def read_build_queue_civ6(logs_dir: Path, path: Path) -> list[BuildQueueRow]:
    ownership = _ownership_by_turn(logs_dir)
    table = read_table(path)
    out: list[BuildQueueRow] = []
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) != 7:
            raise LogFormatError(
                f"{path.name}: expected 7 columns but a row has {len(row)}: {row!r}"
            )
        turn, city = int(row[0]), row[1]
        out.append(BuildQueueRow(
            turn=turn,
            player=_owner_at(ownership.get(city, []), turn),
            city=city,
            added=float(row[2]),
            item=row[3],
            current=float(row[4]),
            needed=float(row[5]),
            overflow=float(row[6]),
        ))
    return out
