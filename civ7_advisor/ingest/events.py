"""Readers for the event logs: combat, gossip and diplomatic actions.

These logs record things that happened between players. Whether an event is FAIR or ORACLE
is decided later (advisors/intel.py) by who took part; the readers only parse.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .csvfile import LogFormatError, expect_header, latest_game_segment, read_table

# --- CombatLog.csv ----------------------------------------------------------
# The one Civ VII log written without a space after each comma; read_table strips cells,
# so the same reader path handles it.

COMBAT_HEADER = [
    "Turn", "SourceType", "Location", "AttPlayer", "DefPlayer", "CombatType", "Attacker",
    "Defender", "AttStr", "DefStr", "AttStrMod", "DefStrMod", "AttDmg", "DefDmg", "Destroyed",
    "HealAmount", "attHealth", "defHealth",
]
_LOCATION = re.compile(r"^\((-?\d+)\)\((-?\d+)\)$")   # (63)(30)
_COMBATANT = re.compile(r"^\((-?\d+)\)(.+)$")        # (14)UNIT_WARRIOR or (-1)LOC_DISTRICT_...


@dataclass(frozen=True)
class Combatant:
    unit_id: int | None   # None for a district or plot, which the log tags (-1)
    kind: str             # UNIT_WARRIOR, LOC_DISTRICT_CITY_CENTER_NAME, ...


@dataclass(frozen=True)
class CombatRow:
    turn: int
    source_type: str      # e.g. "Unit vs Location"
    x: int
    y: int
    att_player: int
    def_player: int
    combat_type: str      # e.g. "Melee"
    attacker: Combatant
    defender: Combatant
    att_str: int
    def_str: int
    att_str_mod: int
    def_str_mod: int
    att_dmg: int          # raw; whether this is damage dealt or taken is pinned by the fixture task
    def_dmg: int          # raw; see above
    destroyed: str | None  # "Attacker" | "Defender" | None — the only field win/loss reads
    heal_amount: int
    att_health_raw: str   # "(a)b" exactly as logged; order of the two numbers pinned later
    def_health_raw: str

    def parties(self) -> frozenset[int]:
        return frozenset({self.att_player, self.def_player})

    def involves(self, player: int) -> bool:
        return player in self.parties()

    def loser(self) -> int | None:
        """The player whose combatant `Destroyed` names; None when nothing died."""
        if self.destroyed == "Attacker":
            return self.att_player
        if self.destroyed == "Defender":
            return self.def_player
        return None


def _combatant(cell: str, path: Path) -> Combatant:
    m = _COMBATANT.match(cell)
    if not m:
        raise LogFormatError(f"{path.name}: unexpected combatant cell {cell!r}")
    unit_id = int(m.group(1))
    return Combatant(None if unit_id < 0 else unit_id, m.group(2))


def read_combat_log(path: Path) -> list[CombatRow]:
    table = read_table(path)
    expect_header(table, COMBAT_HEADER)
    out: list[CombatRow] = []
    for r in latest_game_segment(table.rows, turn_col=0):
        loc = _LOCATION.match(r[2])
        if not loc:
            raise LogFormatError(f"{path.name}: unexpected Location cell {r[2]!r}")
        out.append(CombatRow(
            int(r[0]), r[1], int(loc.group(1)), int(loc.group(2)), int(r[3]), int(r[4]), r[5],
            _combatant(r[6], path), _combatant(r[7], path),
            int(r[8]), int(r[9]), int(r[10]), int(r[11]), int(r[12]), int(r[13]),
            r[14] or None, int(r[15]), r[16], r[17],
        ))
    return out


# --- Game_Gossip.csv --------------------------------------------------------
# Ragged: 6 header names, 6 or 7 data columns (the 7th is a free-text detail). `Player`
# holds the leader's display NAME, not an id — state/names.py resolves it.

GOSSIP_HEADER = ["Game Turn", "Player", "Civilization", "Plot X", "Plot Y", "Type"]


@dataclass(frozen=True)
class GossipRow:
    turn: int
    leader: str          # display name as logged, e.g. "Alexander"; resolve via NameResolver
    civilization: str    # e.g. "Maurya"
    x: int               # may be negative when the gossip has no plot
    y: int
    type: str            # GOSSIP_UNIT_DESTROYED, GOSSIP_CITY_FOUNDED, ...
    detail: str | None   # the optional 7th column, e.g. "Warrior"


def read_gossip(path: Path) -> list[GossipRow]:
    table = read_table(path)
    expect_header(table, GOSSIP_HEADER)
    out: list[GossipRow] = []
    for r in latest_game_segment(table.rows, turn_col=0):
        if len(r) not in (6, 7):
            raise LogFormatError(
                f"{path.name}: expected 6 or 7 columns but a row has {len(r)} (row starts {r[:2]})"
            )
        detail = r[6] if len(r) == 7 and r[6] else None
        out.append(GossipRow(int(r[0]), r[1], r[2], int(r[3]), int(r[4]), r[5], detail))
    return out


# --- DiplomacySummary.csv ---------------------------------------------------
# Seven header names, but the captured live row carried six values, so it is not known
# whether `Mayhem` or `Visibility` is the one missing. Everything after `Details` is kept
# raw in `extra`; the fixture task names those cells once the distribution is known.

DIPLOMACY_SUMMARY_HEADER = ["Game Turn", "Initiator", "Recipient", "Action", "Details", "Mayhem", "Visibility"]


@dataclass(frozen=True)
class DiplomacySummaryRow:
    turn: int
    initiator: int
    recipient: int
    action: str
    details: str
    extra: tuple[str, ...]   # the cells after Details, unnamed until Task 11 pins them

    def parties(self) -> frozenset[int]:
        return frozenset({self.initiator, self.recipient})

    def involves(self, player: int) -> bool:
        return player in self.parties()


def read_diplomacy_summary(path: Path) -> list[DiplomacySummaryRow]:
    table = read_table(path)
    expect_header(table, DIPLOMACY_SUMMARY_HEADER)
    out: list[DiplomacySummaryRow] = []
    for r in latest_game_segment(table.rows, turn_col=0):
        if len(r) < 5:
            raise LogFormatError(
                f"{path.name}: expected at least 5 columns but a row has {len(r)} (row starts {r[:2]})"
            )
        out.append(DiplomacySummaryRow(int(r[0]), int(r[1]), int(r[2]), r[3], r[4], tuple(r[5:])))
    return out
