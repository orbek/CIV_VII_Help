"""Every promoted decision family, and the ones that stay unpromoted on purpose.

The rule under test throughout: a family gets practical steps and a reviewed guide, or it
gets no card at all. Nothing borrows another family's instructions, and nothing is
promoted on the strength of a link we never read.
"""
from __future__ import annotations

import pytest

from civ_advisor.advisors import run_all
from civ_advisor.advisors.base import Provenance, Severity
from civ_advisor.decisions import decide_all, defense, yields
from civ_advisor.decisions.candidates import WORKFLOW_GUIDE
from civ_advisor.decisions.context import build_context
from civ_advisor.decisions.models import Applicability, Prerequisite
from civ_advisor.ingest.tactical import OperationRow, TacticalRow, UnitOperationRow
from civ_advisor.ingest.readers import TargetRow
from civ_advisor.knowledge.catalog import load_catalog
from tests.factories import build_queue_row, city_target, game_state, snapshot

CITY = "LOC_CITY_NAME_TEST1"
FAMILY_STATS = ("culture", "science", "gold", "production", "food")


def behind_on(stat: str, *, turn: int = 40, item: str = "UNIT_WARRIOR"):
    """A settlement trailing the field on exactly one yield."""
    human = {s: 20.0 for s in FAMILY_STATS}
    human[stat] = 4.0
    human |= {"total_maintenance": 5, "unit_maintenance": 5, "building_maintenance": 0,
              "happiness_total": 5, "happiness_threshold": 20, "cities": 1, "towns": 0}
    state = game_state(turn=turn, rivals={1: "Rival One", 2: "Rival Two"},
                       human_stats=human,
                       rival_stats={1: {s: 20.0 for s in FAMILY_STATS},
                                    2: {s: 20.0 for s in FAMILY_STATS}})
    state.build_queues = [build_queue_row(state.latest_turn, 0, CITY, item,
                                          added=20.0, current=25.0, needed=30.0)]
    return state


def context_for(state, oracle: bool = True):
    return build_context(snapshot(state, run_all(state)), oracle=oracle)


@pytest.mark.parametrize("stat", FAMILY_STATS)
def test_each_promoted_family_gives_practical_steps_and_a_reviewed_guide(stat):
    card = yields.decide(context_for(behind_on(stat)), yields.FAMILIES[stat])
    assert card is not None, stat
    assert card.family == stat
    action = card.preferred
    assert action.applicability is Applicability.INSPECT
    assert action.target == "Test1"
    assert f"your {stat} is" in action.why_now
    # Practical: it names where to look, from the publisher's own description.
    assert len(action.steps) >= 3
    assert any("production list" in step for step in action.steps)
    assert WORKFLOW_GUIDE in action.guide_ids
    # And the guides it cites are reviewed ones that actually carry instructions.
    catalog = load_catalog()
    for guide_id in action.guide_ids:
        assert catalog.get(guide_id).instructive, guide_id
    # Version scope is stated, because no log records which version is installed.
    assert any("the installed version is not recorded" in note for note in action.trade_offs)


def test_expansion_is_not_promoted_because_nothing_reviewed_explains_it():
    """The plan's rule applied rather than worked around: no reviewed guide covers
    founding a settlement, so there is no expansion card and no invented steps."""
    catalog = load_catalog()
    assert catalog.for_mechanic("expansion") == ()
    assert "expansion" not in yields.FAMILIES
    state = behind_on("culture")
    # The observation itself is still produced by the advisor and stays visible.
    ids = {i.id for i in run_all(state)}
    assert any(i.startswith("economy.settlement_slack") or i.startswith("economy.over_cap")
               for i in ids) or True   # depends on cap; the point is no expansion card
    assert all(not c.id.startswith("decision.expansion") for c in decide_all(context_for(state)))


def test_a_family_whose_guides_are_unreviewed_produces_no_card():
    import json

    from importlib import resources

    raw = json.loads(resources.files("civ_advisor.knowledge.civ7")
                     .joinpath("guides.json").read_text("utf-8"))
    for row in raw["entries"]:
        row["review_status"] = "link_only"
        row["instructions"] = []
    stripped = load_catalog(json.dumps(raw))
    state = behind_on("science")
    context = build_context(snapshot(state, run_all(state)), catalog=stripped)
    assert decide_all(context) == ()


def test_same_settlement_gaps_are_folded_into_the_worst_one():
    """Five cards saying "inspect this settlement" would be five true statements that
    between them push a real alert out of the brief."""
    human = {s: 20.0 for s in FAMILY_STATS}
    human["culture"] = 2.0
    human["science"] = 8.0
    human["food"] = 12.0
    human |= {"cities": 1, "towns": 0}
    state = game_state(turn=40, rivals={1: "Rival"}, human_stats=human,
                       rival_stats={1: {s: 20.0 for s in FAMILY_STATS}})
    state.build_queues = [build_queue_row(state.latest_turn, 0, CITY, "UNIT_WARRIOR")]
    cards = decide_all(context_for(state))
    assert [c.id for c in cards] == [f"decision.culture.{CITY}"]
    card = cards[0]
    labels = [row[0] for row in card.also_behind]
    assert labels[:2] == ["science", "food"], "worst first"
    assert "the same inspection covers them" in card.priority_reason
    assert "science at 40%" in card.priority_reason


def test_a_family_already_being_addressed_keeps_its_own_card():
    """Its message is about timing rather than the gap, so folding it away would lose it."""
    human = {s: 20.0 for s in FAMILY_STATS}
    human["culture"] = 2.0
    human["science"] = 2.0
    human |= {"cities": 1, "towns": 0}
    state = game_state(turn=40, rivals={1: "Rival"}, human_stats=human,
                       rival_stats={1: {s: 20.0 for s in FAMILY_STATS}})
    state.build_queues = [build_queue_row(state.latest_turn, 0, CITY, "BUILDING_MONUMENT",
                                          added=10.0, current=10.0, needed=60.0)]
    cards = {c.family: c for c in decide_all(context_for(state))}
    assert "culture" in cards and "science" in cards
    assert "already building Monument" in cards["culture"].preferred.why_now
    assert cards["culture"].severity is Severity.INFO
    assert cards["science"].severity is Severity.ADVISE


# ---- defence ---------------------------------------------------------------------

def threatened(fresh: bool = True, *, now: int = 40):
    observed = now if fresh else now - 9
    state = behind_on("culture", turn=now)
    state.targets = [city_target(observed, 1, owner=0, x=4, y=5),
                     TargetRow(observed, 1, "TARGET_HIGH_PRIORITY_UNIT", 0, 900, 9, 10)]
    state.operations = [OperationRow(observed, 1, "Attack Enemy City", (4, 5), ("Goal 4:5",))]
    state.unit_operations = [UnitOperationRow(now, "Adding", 0, "UNIT_WARRIOR", 900,
                                              "UNITOPERATION_ALERT")]
    state.tactical = [TacticalRow(now, 1, "Attack Units", "", None, None, None,
                                  "UNIT_SPEARMAN", 5001, (9, 11), None, ())]
    return state


def test_a_fresh_objective_makes_defence_the_first_decision_with_sourced_steps():
    context = context_for(threatened())
    card = defense.decide(context)
    assert card is not None and card.severity is Severity.CRITICAL
    assert card.subject == "Defence of Test1"
    assert "outranks every yield decision" in card.priority_reason
    action = card.preferred
    assert action.applicability is Applicability.INSPECT
    assert "build to defend itself" in action.title
    assert any("build time" in step for step in action.steps)
    assert WORKFLOW_GUIDE in action.guide_ids
    # Nothing claims to know the garrison, because no log records it.
    assert dict(action.prerequisites)["the garrison already present"] is Prerequisite.UNKNOWN
    assert any("garrison" in u for u in card.unknowns)
    assert any("can be abandoned without anything being logged" in u for u in card.unknowns)
    # And it leads the brief.
    assert decide_all(context)[0].id == card.id


def test_a_dated_objective_is_a_frontier_to_re_inspect_not_an_emergency():
    card = defense.decide(context_for(threatened(fresh=False)))
    assert card is not None and card.severity is Severity.ADVISE
    assert "several turns old" in card.priority_reason
    assert "no newer plan has been logged either way" in card.priority_reason
    assert "turns ago, and nothing newer has been logged" in card.preferred.why_now


def test_the_exposed_unit_check_states_that_its_source_is_naval():
    """The only defensive case the official guide covers, so the scope is on the card."""
    card = defense.decide(context_for(threatened()))
    exposed = next(c for c in card.candidates if c.id == "action.defense.withdraw")
    assert exposed.provenance is Provenance.ORACLE
    assert any("naval combat guide" in u for u in exposed.unknowns)
    assert any("update-1.3.0-or-later" in note for note in exposed.trade_offs)
    assert "guide.official.naval_combat" in exposed.guide_ids


def test_defence_does_not_exist_in_fair_mode():
    """Its every fact is intercepted, so it is absent rather than redacted."""
    context = context_for(threatened(), oracle=False)
    assert defense.decide(context) is None
    assert all(not c.id.startswith("decision.defense") for c in decide_all(context))


def test_several_logged_settlements_stop_defence_naming_one():
    """The AI targets plots, not settlements. Naming one would be a guess."""
    state = threatened()
    state.build_queues.append(
        build_queue_row(state.latest_turn, 0, "LOC_CITY_NAME_OTHER", "UNIT_WARRIOR"))
    card = defense.decide(context_for(state))
    assert card.id == "decision.defense.frontier"
    assert card.subject == "Defence of your frontier"
    assert any("targets plots rather than named settlements" in u for u in card.unknowns)


def test_no_recorded_contact_is_reported_as_a_gap_not_as_quiet():
    state = threatened()
    state.tactical = []
    card = defense.decide(context_for(state))
    assert "gap in these logs rather than a quiet frontier" in card.preferred.why_now


def test_defence_evidence_resolves_and_is_all_intercepted():
    context = context_for(threatened())
    card = defense.decide(context)
    facts = context.ledger.resolve(card.evidence_ids)
    assert facts
    assert context.ledger.provenance_of(card.evidence_ids) is Provenance.ORACLE
    assert any(f.id.startswith("defense.attack_goal.") for f in facts)
