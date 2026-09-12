from dataclasses import FrozenInstanceError

import pytest

from civ_advisor.advisors import ADVISORS
from civ_advisor.advisors.base import Provenance, Severity
from civ_advisor.advisors.checklist import ADVISOR_ORDER, rank
from tests.factories import insight


def test_rank_orders_by_severity_then_turn_then_advisor_then_id():
    items = [
        insight("economy.a", "economy", Severity.WARN, turn=10),
        insight("threat.b", "threat", Severity.WARN, turn=10),
        insight("victory.c", "victory", Severity.CRITICAL, turn=9),
        insight("threat.a", "threat", Severity.WARN, turn=10),
        insight("threat.z", "threat", Severity.INFO, turn=10),
        insight("threat.old", "threat", Severity.WARN, turn=9),
    ]
    assert [i.id for i in rank(items)] == [
        "victory.c", "threat.a", "threat.b", "economy.a", "threat.old", "threat.z",
    ]


def test_rank_dedupes_by_id_keeping_the_more_severe():
    items = [insight("threat.x", severity=Severity.INFO), insight("threat.x", severity=Severity.WARN)]
    ranked = rank(items)
    assert len(ranked) == 1 and ranked[0].severity is Severity.WARN


def test_severity_is_ordered_and_insight_is_frozen():
    assert Severity.INFO < Severity.ADVISE < Severity.WARN < Severity.CRITICAL
    i = insight("a", provenance=Provenance.ORACLE)
    assert i.provenance is Provenance.ORACLE
    with pytest.raises(FrozenInstanceError):
        i.title = "x"  # type: ignore[misc]


def test_every_advisor_is_registered_in_both_lists_and_stamps_its_own_name(fixture_state):
    """The advisor set is written down in three places: ADVISORS (what run_all runs),
    ADVISOR_ORDER (how rank breaks ties) and the advisor= literal in each module.
    ADVISOR_ORDER.get(a, 99) degrades quietly, so a fourth advisor added to one and
    forgotten in the other would just sort last for ever. Tie them together here."""
    names = {module.__name__.rsplit(".", 1)[-1] for module in ADVISORS}
    assert names == set(ADVISOR_ORDER)
    for module in ADVISORS:
        name = module.__name__.rsplit(".", 1)[-1]
        emitted = {i.advisor for i in module.advise(fixture_state)}
        assert emitted <= {name}, f"{name}.advise() stamps {emitted}"  # silent on this fixture is allowed
