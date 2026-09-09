import pytest

from civ7_advisor.advisors import economy
from civ7_advisor.advisors.base import Provenance, Severity
from tests.factories import game_state


def ids(insights):
    return {i.id: i for i in insights}


def test_worst_stat_is_warn_when_far_behind_and_others_are_info():
    s = game_state(
        turn=20, rivals={1: "A", 2: "B", 3: "C"},
        human_stats={"food": 8.0, "science": 14.0, "culture": 30.0},
        rival_stats={1: {"food": 20.0, "science": 20.0}, 2: {"food": 24.0}, 3: {"food": 40.0}},
    )
    got = ids(economy.advise(s))
    food = got["economy.behind.food"]  # 8 / median 24 = 0.33
    assert food.severity is Severity.WARN and food.provenance is Provenance.FAIR
    assert "8.0 vs rival median 24.0 (33%)" in food.why and "leader C at 40.0" in food.why
    assert got["economy.behind.science"].severity is Severity.INFO  # 14 / 20 = 0.70
    assert "economy.behind.culture" not in got  # 30 / 20 is ahead


def test_behind_returns_only_sub_threshold_stats_worst_first():
    s = game_state(
        turn=20, rivals={1: "A", 2: "B", 3: "C"},
        human_stats={"food": 8.0, "science": 14.0, "culture": 30.0},
        rival_stats={1: {"food": 20.0, "science": 20.0}, 2: {"food": 24.0}, 3: {"food": 40.0}},
    )
    got = economy.behind(s)  # food 8/24 = 0.33, science 14/20 = 0.70; culture/gold/production are level
    assert [c.stat for c in got] == ["food", "science"]
    assert all(c.ratio < economy.BEHIND_RATIO for c in got)


def test_worst_stat_is_advise_when_moderately_behind():
    s = game_state(turn=20, human_stats={"gold": 14.0})  # 14 / 20 = 0.70
    assert ids(economy.advise(s))["economy.behind.gold"].severity is Severity.ADVISE


@pytest.mark.parametrize("value,flagged", [(14.9, True), (15.0, False)])  # threshold is 0.75 * 20
def test_behind_threshold(value, flagged):
    s = game_state(turn=20, human_stats={"production": value})
    assert ("economy.behind.production" in ids(economy.advise(s))) is flagged


@pytest.mark.parametrize(
    "value,expected",
    [(9.9, Severity.WARN), (10.0, Severity.ADVISE), (10.1, Severity.ADVISE)],
)  # far-behind threshold is 0.5 * 20; a ratio of exactly 0.5 is not yet "far" behind
def test_far_behind_threshold(value, expected):
    s = game_state(turn=20, human_stats={"food": value})  # the only stat behind, so index == 0
    assert ids(economy.advise(s))["economy.behind.food"].severity is expected


def test_settlement_slack_and_over_cap():
    s = game_state(turn=20, human_stats={"cities": 1, "towns": 1, "settlement_cap": 4})
    assert "2 of 4 settlement slots unused" in ids(economy.advise(s))["economy.settlement_slack"].why
    s = game_state(turn=20, human_stats={"cities": 2, "towns": 3, "settlement_cap": 4, "settlements_over_cap": 1})
    got = ids(economy.advise(s))
    assert "economy.settlement_slack" not in got and got["economy.over_cap"].severity is Severity.WARN


def test_negative_gold_needs_treasury_data():
    s = game_state(turn=20, human_stats={"gold": 10.0, "total_maintenance": 14})
    assert "= -4.0 per turn" in ids(economy.advise(s))["economy.negative_gold"].why
    s = game_state(turn=20, human_stats={"gold": 10.0})  # no maintenance row -> unknown, stay silent
    assert "economy.negative_gold" not in ids(economy.advise(s))


def test_celebration_thresholds_and_provenance():
    s = game_state(
        turn=20, human_stats={"happiness_total": 900, "happiness_threshold": 1000},
        rival_stats={1: {"happiness_total": 899, "happiness_threshold": 1000}},
    )
    got = ids(economy.advise(s))
    assert got["economy.celebration"].provenance is Provenance.FAIR
    assert "economy.rival_celebration.1" not in got
    s = game_state(turn=20, rival_stats={1: {"happiness_total": 950, "happiness_threshold": 1000}})
    assert ids(economy.advise(s))["economy.rival_celebration.1"].provenance is Provenance.ORACLE


def test_no_rivals_means_no_comparison_but_own_checks_still_run():
    s = game_state(turn=20, rivals={}, human_stats={"settlement_cap": 5})
    got = ids(economy.advise(s))
    assert not any(k.startswith("economy.behind") for k in got) and "economy.settlement_slack" in got
    assert economy.comparison(s) == []


def test_comparison_skips_a_stat_whose_rival_median_is_zero():
    s = game_state(turn=20, rival_stats={1: {"culture": 0.0}})  # median 0.0 -> would divide by zero
    stats = {c.stat for c in economy.comparison(s)}
    assert "culture" not in stats
    assert stats == {"science", "gold", "production", "food"}


def test_fixture_economy_at_turn_81(fixture_state):
    got = ids(economy.advise(fixture_state))
    food = got["economy.behind.food"]
    assert food.severity is Severity.WARN and "24.0 vs rival median 59.0 (41%)" in food.why
    assert got["economy.behind.culture"].severity is Severity.INFO
    assert got["economy.behind.science"].severity is Severity.INFO
    assert "economy.behind.gold" not in got and "economy.behind.production" not in got
    assert "2 of 4 settlement slots unused" in got["economy.settlement_slack"].why
    assert "economy.negative_gold" not in got  # 23.0 - 4 = +19
    assert "economy.celebration" not in got    # 1038 / 1532 = 68%
    catherine = got["economy.rival_celebration.7"]
    assert catherine.provenance is Provenance.ORACLE and "(93%)" in catherine.why
    assert [k for k in got if k.startswith("economy.rival_celebration")] == ["economy.rival_celebration.7"]


def test_fixture_comparison_table(fixture_state):
    by_stat = {c.stat: c for c in economy.comparison(fixture_state)}
    assert set(by_stat) == {"science", "culture", "gold", "production", "food"}
    assert by_stat["food"].rival_median == 59.0 and by_stat["food"].leader_name == "Ibn Battuta"
    assert by_stat["gold"].leader_name == "Harriet Tubman" and by_stat["gold"].leader_value == 72.5
    assert by_stat["science"].ratio == pytest.approx(15.0 / 31.8)
