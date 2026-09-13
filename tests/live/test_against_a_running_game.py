"""Checks against a real, running Civilization VI with `EnableTuner 1` set.

Whoever runs this has their own game up, with their own cities, their own maintenance
bill, and their own build queues -- there is no fixture to assert exact figures
against. Every check here asserts a SHAPE the reply must have, never a value: that the
maintenance breakdown adds up, and that every build option this settlement offers comes
with a non-negative turn estimate. See tests/live/README.md for how to run this suite.
"""
from __future__ import annotations


def test_maintenance_reads_back_a_consistent_breakdown():
    from civ_advisor.tuner.client import open_tuner

    t = open_tuner()
    m = t.maintenance()
    assert m is not None
    assert m.buildings + m.districts + m.units == m.total


def test_every_settlement_offering_an_option_gives_it_an_estimate():
    from civ_advisor.tuner.client import open_tuner

    for s in open_tuner().build_options():
        for o in s.options:
            assert o.turns >= 0
