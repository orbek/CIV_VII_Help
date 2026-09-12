"""Pinned positional layout of Civ VI's Player_Stats.csv.

Addressed by position, not by header name, because `Faith` is the name of
BOTH column 13 (the treasury balance) and column 17 (the per-turn yield). A
dict keyed on the header keeps one and discards the other, and which one
survives depends on iteration order.

Verified 2026-09-12 against a turn-53 capture: header and every row carry
exactly 20 fields.
"""

PLAYER_STATS_COLUMN_COUNT = 20

# Column 1 is the civilization string, not a player id; see spec §5.
PLAYER_STATS_CIV_COLUMN = 1

PLAYER_STATS_INT_COLUMNS = {
    "turn": 0,
    "cities": 2,
    "techs": 4,
    "civics": 5,
    "land_units": 6,
    "corps": 7,
    "armies": 8,
    "naval_units": 9,
    "tiles_owned": 10,
    "tiles_improved": 11,
}

PLAYER_STATS_FLOAT_COLUMNS = {
    "gold_balance": 12,
    "faith_balance": 13,
    "science": 14,
    "culture": 15,
    "gold": 16,
    "faith": 17,
    "production": 18,
    "food": 19,
}
