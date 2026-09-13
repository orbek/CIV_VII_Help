"""Checks against a real, running Civilization VI with `EnableTuner 1` set.

Whoever runs this has their own game up, with their own cities, their own maintenance
bill, and their own build queues -- there is no fixture to assert exact figures
against. Every check here asserts a SHAPE the reply must have, never a value: that the
figures are internally consistent, and that every build option this settlement offers
comes with a non-negative turn estimate. See tests/live/README.md for how to run this suite.
"""
from __future__ import annotations


def test_maintenance_reads_back_a_coherent_breakdown():
    """Not that the parts close -- they are not known to be exhaustive; see
    Maintenance.unattributed. Only that what we read is internally consistent.

    This asserted `buildings + districts + units == total` until this round, which is
    exactly the invariant an earlier fix removed from Maintenance.__post_init__ for
    resting on ONE observation where the three happened to be 0, 1 and 0. The same
    probe found GetRouteMaintenance missing from this VM, so the game's own total
    plainly counts things it will not itemise. Re-asserting it here contradicted the
    comment in tuner/base.py and would fail on a real game that has roads.
    """
    from civ_advisor.tuner.client import open_tuner

    m = open_tuner().maintenance()
    assert m is not None
    assert m.net_gold == m.gold_yield - m.total
    assert m.unattributed == m.total - (m.buildings + m.districts + m.units)


def test_every_settlement_offering_an_option_gives_it_an_estimate():
    from civ_advisor.tuner.client import open_tuner

    for s in open_tuner().build_options():
        for o in s.options:
            assert o.turns >= 0
