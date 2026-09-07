from dataclasses import FrozenInstanceError

import pytest

from civ7_advisor.advisors.base import Provenance, Severity
from civ7_advisor.advisors.checklist import rank
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
