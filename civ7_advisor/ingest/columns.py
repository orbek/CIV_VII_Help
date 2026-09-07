"""Pinned positional layout of Player_Stats.csv.

The header of this file is ragged: it names 22 columns but rows carry 25.
`TILES:`, `BALANCE:`, `YIELDS:` and `BY TYPE:` are group labels, not columns.
The positions below were verified against a live game (turn 82, player 0):
gold_balance matched Player_Treasury "Gold Balance" (136.0), gold matched its
"Gold Yield" (23.0), and happiness matched Player_Happiness "Per Turn
Happiness" (20). Columns 21-24 are an unlabeled by-type breakdown and are
ignored.
"""

PLAYER_STATS_COLUMN_COUNT = 25

PLAYER_STATS_INT_COLUMNS = {
    "turn": 0,
    "player": 1,
    "cities": 2,
    "towns": 3,
    "settlement_cap": 4,
    "settlements_over_cap": 5,
    "urban_pop": 6,
    "rural_pop": 7,
    "techs": 8,
    "land_units": 9,
    "naval_units": 10,
    "tiles_owned": 11,
    "tiles_improved": 12,
}

PLAYER_STATS_FLOAT_COLUMNS = {
    "gold_balance": 13,
    "science": 14,
    "culture": 15,
    "gold": 16,
    "production": 17,
    "food": 18,
    "happiness": 19,
    "diplomacy": 20,
}
