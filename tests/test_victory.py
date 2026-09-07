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


def test_committed_leader_escalates_to_warn_oracle():
    s = game_state(turn=20, rivals={1: "A", 2: "B"}, rival_stats={1: {"culture": 60.0}})
    s.strategies = {1: {"CULTURAL": strategy(1, "CULTURAL", 100)}}
    i = ids(victory.advise(s))["victory.leader.CULTURAL"]
    assert i.severity is Severity.WARN and i.provenance is Provenance.ORACLE and "committed" in i.why


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


def test_fixture_leaderboards(fixture_state):
    boards = victory.leaderboards(fixture_state)
    assert set(boards) == {"SCIENCE", "CULTURAL", "ECONOMIC", "MILITARY"}
    assert [p.id for p, _ in boards["SCIENCE"]] == [4, 7, 5, 1, 6, 2, 0]
    assert boards["ECONOMIC"][0][1] == 72.5
