"""Readers for the AI's own scored deliberations.

Every file here is Civilization VI-only and every row is AI-internal: what
the AI wants, what it resents, and what it is weighing. Nothing in this
module is derivable from what a player can see in game, so everything built
from it is Provenance.ORACLE (spec §3.3).

Civ VII has no counterpart to any of these files, which is why they live
here as first-class readers rather than in games/civ6/readers.py -- that
module reshapes Civ VII row types into the canonical form, and there is no
Civ VII row type here to reshape.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .csvfile import LogFormatError, expect_header, latest_game_segment, read_table

MILITARY_HEADER = [
    "Game Turn", "Player", "Regional Strength", "Enemy Strength", "Other Strength",
    "Current Explorers", "Desired Explorers", "Fav Tech", "Combat Desire",
]

MODIFIERS_HEADER = [
    "Game Turn", "Player", "Opponent", "Modifier", "Change", "Value", "Max",
    "Accum Amt", "Accum Turns", "Cooldown Turns", "Reduction",
]


@dataclass(frozen=True)
class MilitaryRow:
    """One player's military posture on one turn, as the AI reads it.

    `combat_desire` is the AI's own appetite for a fight -- a far more direct
    war-intent signal than anything Civ VII exposes, and one the player has no
    way to see. The file's `Current Explorers`/`Desired Explorers` cells are
    colon-pairs ("4:0") whose meaning the logs never state, so they are not
    carried: an unexplained signal is worse than an absent one.
    """

    turn: int
    player: int
    regional_strength: int
    enemy_strength: int
    other_strength: int
    fav_tech: str
    combat_desire: float


def read_military(path: Path) -> list[MilitaryRow]:
    table = read_table(path)
    expect_header(table, MILITARY_HEADER)
    out: list[MilitaryRow] = []
    # Civ VI never truncates this log; see the module docstring in
    # games/civ6/readers.py. Without segmenting, a previous match's combat
    # desire would be reported as this match's.
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) != len(MILITARY_HEADER):
            raise LogFormatError(
                f"{path.name}: expected {len(MILITARY_HEADER)} columns but a row "
                f"has {len(row)}: {row!r}"
            )
        out.append(MilitaryRow(
            turn=int(row[0]), player=int(row[1]), regional_strength=int(row[2]),
            enemy_strength=int(row[3]), other_strength=int(row[4]),
            fav_tech=row[7], combat_desire=float(row[8]),
        ))
    return out


# The file's three real row widths. An Activate row carries every column; an
# Update row stops after Change; a Deactivate row stops after Modifier. Any
# other width is a format change and raises.
_MODIFIER_WIDTHS = (11, 6, 5)


@dataclass(frozen=True)
class DiplomacyModifierRow:
    """One entry in the AI's grievance ledger for an ordered player/opponent pair.

    WHAT THIS ROW DOES NOT SAY: which of the two players holds the opinion.
    The `Modifier` text is the game's own second-person wording ("First
    impressions of you", "They dislike civilizations with a small standing
    army"), written from one side's voice, and the file records the pair but
    never labels the direction. The fixture's turn-48 rows appear in both
    orderings for one meeting, so the ordering does not disambiguate it
    either. Callers must therefore report a modifier as standing *between*
    two players, never as one player's opinion of the other.
    """

    turn: int
    player: int
    opponent: int
    modifier: str          # the game's own wording, kept verbatim
    action: str            # Activate | Update | Deactivate
    value: float | None = None
    max_value: float | None = None
    accum_amount: float | None = None
    accum_turns: int | None = None
    cooldown_turns: int | None = None
    reduction: float | None = None


def _opt_float(row: list[str], index: int) -> float | None:
    return float(row[index]) if index < len(row) and row[index] else None


def _opt_int(row: list[str], index: int) -> int | None:
    return int(row[index]) if index < len(row) and row[index] else None


def read_diplomacy_modifiers(path: Path) -> list[DiplomacyModifierRow]:
    table = read_table(path)
    expect_header(table, MODIFIERS_HEADER)
    out: list[DiplomacyModifierRow] = []
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) not in _MODIFIER_WIDTHS:
            raise LogFormatError(
                f"{path.name}: a row has {len(row)} columns; this file's rows are "
                f"{_MODIFIER_WIDTHS[0]} (Activate), {_MODIFIER_WIDTHS[1]} (Update) "
                f"or {_MODIFIER_WIDTHS[2]} (Deactivate): {row!r}"
            )
        out.append(DiplomacyModifierRow(
            turn=int(row[0]), player=int(row[1]), opponent=int(row[2]),
            modifier=row[3], action=row[4],
            value=_opt_float(row, 5), max_value=_opt_float(row, 6),
            accum_amount=_opt_float(row, 7), accum_turns=_opt_int(row, 8),
            cooldown_turns=_opt_int(row, 9), reduction=_opt_float(row, 10),
        ))
    return out
