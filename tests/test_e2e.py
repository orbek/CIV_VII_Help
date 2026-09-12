from civ_advisor.advisors import Provenance, Severity, run_all
from civ_advisor.state.models import GameState


def test_fixture_end_to_end(fixture_state):
    insights = run_all(fixture_state)
    assert insights, "the live game should produce advice"
    assert insights[0].id == "threat.at_war.4" and insights[0].severity is Severity.CRITICAL
    ids_ = [i.id for i in insights]
    assert len(ids_) == len(set(ids_))
    severities = [int(i.severity) for i in insights]
    assert severities == sorted(severities, reverse=True)
    assert all(i.title.strip() and i.recommendation.strip() and i.why.strip() for i in insights)
    assert all(i.turn == 81 for i in insights)
    assert {i.advisor for i in insights} == {"threat", "victory", "economy"}
    assert {"threat.war_intent.1", "economy.behind.food", "victory.pursuing.4.CULTURAL"} <= set(ids_)


def test_fair_view_alone_still_flags_the_real_problems(fixture_state):
    insights = run_all(fixture_state)
    fair = {i.id for i in insights if i.provenance is Provenance.FAIR}
    oracle = {i.id for i in insights if i.provenance is Provenance.ORACLE}
    assert fair and oracle
    assert {"threat.active_front.4", "threat.military_gap.1", "economy.behind.food"} <= fair
    assert {"threat.at_war.4", "threat.war_intent.1", "threat.targeting.4"} <= oracle


def test_empty_state_yields_no_insights():
    assert run_all(GameState()) == []
