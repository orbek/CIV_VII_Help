import pytest

from civ7_advisor.advisors import victory
from civ7_advisor.advisors.base import Provenance, Severity
from tests.factories import game_state, strategy


def ids(insights):
    return {i.id: i for i in insights}


def test_committed_strategy_is_info_oracle():
    s = game_state(turn=20)
    s.strategies = {1: {"SCIENCE": strategy(1, "SCIENCE", 77, since=12)}}
    i = ids(victory.advise(s))["victory.pursuing.1.SCIENCE"]
    assert i.severity is Severity.INFO and i.provenance is Provenance.ORACLE
    assert "weight 77, last changed on turn 12" in i.why and i.subject_player == 1


@pytest.mark.parametrize(
    "weight,status,expected",
    [(74, "Following", False), (75, "Following", True), (100, "Stopped", False), (100, "Forbidden", False)],
)
def test_commitment_threshold_and_status(weight, status, expected):
    s = game_state(turn=20)
    s.strategies = {1: {"CULTURAL": strategy(1, "CULTURAL", weight, status=status)}}
    assert ("victory.pursuing.1.CULTURAL" in ids(victory.advise(s))) is expected


def test_espionage_is_not_a_legacy_path():
    s = game_state(turn=20)
    s.strategies = {1: {"ESPIONAGE": strategy(1, "ESPIONAGE", 100)}}
    assert not any(i.id.startswith("victory.pursuing") for i in victory.advise(s))


def test_leader_pulling_away_is_advise_fair_by_default():
    s = game_state(turn=20, rivals={1: "A", 2: "B"}, rival_stats={1: {"science": 50.0}, 2: {"science": 39.0}})
    i = ids(victory.advise(s))["victory.leader.SCIENCE"]
    assert i.severity is Severity.ADVISE and i.provenance is Provenance.FAIR and i.subject_player == 1
    assert "A 50.0 vs runner-up B 39.0 (1.28x)" in i.why


def test_leader_below_margin_is_silent():
    s = game_state(turn=20, rivals={1: "A", 2: "B"}, rival_stats={1: {"science": 48.0}, 2: {"science": 39.0}})
    assert "victory.leader.SCIENCE" not in ids(victory.advise(s))


def test_committed_leader_adds_an_oracle_insight_and_leaves_the_fair_one_alone():
    """The AI's commitment must not swallow the yield lead: escalating the single
    insight to ORACLE made a 3x culture lead vanish with the Oracle toggle off, while
    the same numbers sat in the FAIR leaderboard table below it."""
    s = game_state(turn=20, rivals={1: "A", 2: "B"}, rival_stats={1: {"culture": 60.0}})
    s.strategies = {1: {"CULTURAL": strategy(1, "CULTURAL", 100, since=14)}}
    got = ids(victory.advise(s))

    lead = got["victory.leader.CULTURAL"]
    assert lead.severity is Severity.ADVISE and lead.provenance is Provenance.FAIR
    assert lead.why == "Turn 20: A 60.0 vs runner-up You 20.0 (3.00x)."  # yields only
    assert "committed" not in lead.why and "weight" not in lead.why

    both = got["victory.leader_committed.CULTURAL"]
    assert both.severity is Severity.WARN and both.provenance is Provenance.ORACLE
    assert both.subject_player == 1 and both.title != lead.title
    assert both.why == ("A's AI is following its CULTURAL strategy at weight 100 "
                        "(committed threshold 75), last changed on turn 14.")  # strategy weight only


def test_uncommitted_leader_gets_no_oracle_companion():
    s = game_state(turn=20, rivals={1: "A", 2: "B"}, rival_stats={1: {"culture": 60.0}})
    s.strategies = {1: {"CULTURAL": strategy(1, "CULTURAL", 74)}}  # below STRATEGY_COMMITTED
    got = ids(victory.advise(s))
    assert "victory.leader.CULTURAL" in got and "victory.leader_committed.CULTURAL" not in got


def test_a_committed_path_the_rival_does_not_lead_gets_no_companion():
    """Player 1 is committed to CULTURAL but leads SCIENCE: neither path pairs both."""
    s = game_state(turn=20, rivals={1: "A", 2: "B"}, rival_stats={1: {"science": 50.0}})
    s.strategies = {1: {"CULTURAL": strategy(1, "CULTURAL", 100)}}
    got = ids(victory.advise(s))
    assert "victory.leader.SCIENCE" in got
    assert not any(k.startswith("victory.leader_committed") for k in got)


def test_human_strict_lead_is_info_fair_and_ties_are_silent():
    s = game_state(turn=20, human_stats={"gold": 90.0})
    got = ids(victory.advise(s))
    i = got["victory.you_lead.ECONOMIC"]
    assert i.provenance is Provenance.FAIR and "you 90.0" in i.why
    assert "victory.you_lead.MILITARY" not in got  # 5 vs 5 is a tie, not a lead


def test_fixture_victory_at_turn_81(fixture_state):
    got = ids(victory.advise(fixture_state))
    pursuing = sorted(k for k in got if k.startswith("victory.pursuing"))
    assert pursuing == [
        "victory.pursuing.1.SCIENCE", "victory.pursuing.2.MILITARY", "victory.pursuing.4.CULTURAL",
        "victory.pursuing.4.SCIENCE", "victory.pursuing.5.MILITARY", "victory.pursuing.7.SCIENCE",
    ]
    assert "weight 100, last changed on turn 74" in got["victory.pursuing.4.CULTURAL"].why
    econ = got["victory.leader.ECONOMIC"]
    assert econ.subject_player == 2 and econ.severity is Severity.ADVISE and econ.provenance is Provenance.FAIR
    assert "Harriet Tubman 72.5 vs runner-up Ibn Battuta 30.0" in econ.why
    assert not any(k in got for k in ("victory.leader.SCIENCE", "victory.leader.CULTURAL", "victory.leader.MILITARY"))
    assert not any(k.startswith("victory.you_lead") for k in got)
    # Tubman leads ECONOMIC but her AI is committed to MILITARY, so nothing pairs the two.
    assert not any(k.startswith("victory.leader_committed") for k in got)


def test_fixture_leaderboards(fixture_state):
    boards = victory.leaderboards(fixture_state)
    assert set(boards) == {"SCIENCE", "CULTURAL", "ECONOMIC", "MILITARY"}
    assert [p.id for p, _ in boards["SCIENCE"]] == [4, 7, 5, 1, 6, 2, 0]
    assert boards["ECONOMIC"][0][1] == 72.5
