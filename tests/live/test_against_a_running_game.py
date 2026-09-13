"""Checks against a real, running Civilization VI with `EnableTuner 1` set.

Whoever runs this has their own game up, with their own cities, their own maintenance
bill, and their own build queues -- there is no fixture to assert exact figures
against. Every check here asserts a SHAPE the reply must have, never a value.

A shape that a dataclass already enforces is not a shape worth asserting: `net_gold`
and `unattributed` are computed properties, so `m.net_gold == m.gold_yield - m.total`
restates its own definition and cannot fail against any game. `o.turns >= 0` is the
same -- `BuildOption` rejects a negative estimate in `__post_init__`, and the parser
skips a row that would have raised, so nothing negative can survive to be asserted
about. What is left to learn from a live game is what no fixture can tell us: whether
the game answers these questions at all, and whether it dates its answers.
"""
from __future__ import annotations


def test_a_live_figure_is_dated_by_the_turn_the_game_named(tuner):
    """The headline defect of this round, against a real game.

    `_turn: int = 0` was never set, so every live figure in production was filed under
    turn 0 while a player sat on turn 59. Nothing here supplies a turn: the game names
    it in its own reply and the client parses it out, so a reading that comes back at
    all is proof the whole path works end to end.
    """
    m = tuner.maintenance()
    assert m is not None, tuner.reason

    reading = tuner.reading()
    assert reading is not None, tuner.reason
    assert reading.turn >= 1
    assert reading.state == "GameCore_Tuner"
    assert reading.read_at


def test_the_ui_state_also_names_the_game_turn(tuner):
    """The one thing the spike did not verify.

    `Game.GetCurrentGameTurn()` was confirmed live in GameCore_Tuner and never in the
    InGame VM that `build_options` runs in. If it is missing there, the client refuses
    to date those figures and build options go absent -- real figures are never
    misdated, but they are lost, and only a running game can say which it is.
    """
    tuner.build_options()

    reading = tuner.reading()
    assert reading is not None, tuner.reason
    assert reading.turn >= 1
    assert reading.state == "InGame"


def test_every_settlement_the_game_offers_options_for_is_named(tuner):
    """That the reply parsed into real settlements and real items, rather than into
    empty strings the parser happened to accept."""
    for settlement in tuner.build_options():
        assert settlement.city
        for option in settlement.options:
            assert option.item
