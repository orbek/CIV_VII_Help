from dataclasses import replace

import pytest

from civ7_advisor.advisors import threat
from civ7_advisor.advisors.base import Provenance, Severity
from tests.factories import city_target, executed_war, game_state, kill, scored_war


def ids(insights):
    return {i.id: i for i in insights}


def test_executed_war_is_critical_oracle_and_suppresses_intent():
    s = game_state(turn=20)
    s.intents = [scored_war(20, 1, score=204.0), executed_war(18, 1)]
    got = ids(threat.advise(s))
    assert got["threat.at_war.1"].severity is Severity.CRITICAL
    assert got["threat.at_war.1"].provenance is Provenance.ORACLE
    assert "turn 18" in got["threat.at_war.1"].why
    assert "threat.war_intent.1" not in got


def test_executed_war_outside_window_is_ignored():
    s = game_state(turn=40)
    s.intents = [executed_war(30, 1)]  # RECENT_TURNS = 10 -> window is 31..40
    assert "threat.at_war.1" not in ids(threat.advise(s))


def test_executed_war_with_unknown_target_is_not_attributed():
    s = game_state(turn=20)
    s.intents = [executed_war(20, 1, target=None)]
    assert "threat.at_war.1" not in ids(threat.advise(s))


@pytest.mark.parametrize(
    "score,expected",
    [(49.0, None), (50.0, Severity.INFO), (99.9, Severity.INFO), (100.0, Severity.WARN), (202.0, Severity.WARN)],
)
def test_war_intent_thresholds(score, expected):
    s = game_state(turn=20)
    s.intents = [scored_war(20, 1, score=score)]
    got = ids(threat.advise(s))
    if expected is None:
        assert "threat.war_intent.1" not in got
    else:
        assert got["threat.war_intent.1"].severity is expected
        assert got["threat.war_intent.1"].provenance is Provenance.ORACLE


def test_war_intent_reports_start_of_current_run():
    s = game_state(turn=20)
    s.intents = [
        scored_war(15, 1, score=25.0), scored_war(16, 1, score=150.0),
        scored_war(17, 1, score=160.0), scored_war(20, 1, score=202.0),
    ]
    why = ids(threat.advise(s))["threat.war_intent.1"].why
    assert "since turn 16" in why and "held for 5 turns" in why


def test_stale_war_score_is_dropped():
    s = game_state(turn=20)
    s.intents = [scored_war(17, 1, score=202.0)]  # last logged 3 turns ago
    assert "threat.war_intent.1" not in ids(threat.advise(s))


def test_war_intent_against_someone_else_is_ignored():
    s = game_state(turn=20, rivals={1: "A", 2: "B"})
    s.intents = [scored_war(20, 1, target=2, score=202.0)]
    assert not any(i.id.startswith("threat.war") for i in threat.advise(s))


def test_active_front_counts_kills_and_losses_fairly():
    s = game_state(turn=20)
    s.events = [
        kill(15, victim=1, killer=0),
        kill(18, victim=0, killer=1),
        kill(20, victim=0, killer=1, unit="Slinger", x=7, y=9),
        kill(5, victim=0, killer=1),  # outside the window
    ]
    i = ids(threat.advise(s))["threat.active_front.1"]
    assert i.severity is Severity.WARN and i.provenance is Provenance.FAIR
    assert "3 unit kills" in i.why and "you lost 2" in i.why and "turn 20 at (7,9)" in i.why


def test_city_targeting_is_warn_and_units_only_is_advise():
    s = game_state(turn=20)
    s.targets = [
        city_target(20, 1, x=3, y=4),
        city_target(20, 1, x=5, y=6),
        city_target(20, 1, x=4, y=4, target_type="TARGET_HIGH_PRIORITY_UNIT"),
    ]
    i = ids(threat.advise(s))["threat.targeting.1"]
    assert i.severity is Severity.WARN and i.provenance is Provenance.ORACLE
    assert "2 of your city tiles and 1 of your units" in i.why and "x 3-5, y 4-6" in i.why
    s.targets = [city_target(20, 1, target_type="TARGET_LOW_PRIORITY_UNIT")]
    assert ids(threat.advise(s))["threat.targeting.1"].severity is Severity.ADVISE


def test_targeting_uses_previous_turn_when_ai_lags_but_not_older():
    s = game_state(turn=20)
    s.targets = [city_target(19, 1)]
    assert "On turn 19" in ids(threat.advise(s))["threat.targeting.1"].why
    s.targets = [city_target(17, 1)]
    assert "threat.targeting.1" not in ids(threat.advise(s))


@pytest.mark.parametrize("rival_units,expected", [(7, False), (8, True), (12, True)])  # human has 5
def test_military_gap_threshold(rival_units, expected):
    s = game_state(turn=20, rival_stats={1: {"land_units": rival_units}})
    assert ("threat.military_gap.1" in ids(threat.advise(s))) is expected


def test_army_growth_compares_deltas():
    s = game_state(turn=20, history_turns=10)
    s.turns[20][1] = replace(s.turns[20][1], land_units=8)  # rival 5 -> 8, human 5 -> 5
    i = ids(threat.advise(s))["threat.army_growth.1"]
    assert i.severity is Severity.INFO and i.provenance is Provenance.FAIR
    assert "from 5 to 8" in i.why
    s.turns[20][1] = replace(s.turns[20][1], land_units=7)  # +2 is below ARMY_GROWTH_DELTA
    assert "threat.army_growth.1" not in ids(threat.advise(s))


def test_no_human_row_means_no_threats():
    s = game_state(turn=20)
    del s.turns[20][0]
    assert threat.advise(s) == [] and threat.summarize(s) == []


def test_fixture_threats_at_turn_81(fixture_state):
    got = ids(threat.advise(fixture_state))
    assert got["threat.at_war.4"].severity is Severity.CRITICAL and "turn 80" in got["threat.at_war.4"].why
    front = got["threat.active_front.4"]
    assert front.provenance is Provenance.FAIR
    assert "6 unit kills" in front.why and "you lost 3" in front.why and "turn 81 at (62,32)" in front.why
    intent = got["threat.war_intent.1"]
    assert intent.severity is Severity.WARN and "since turn 72" in intent.why and "held for 10 turns" in intent.why
    assert "19 of your city tiles" in got["threat.targeting.4"].why
    assert "9 of your city tiles" in got["threat.targeting.1"].why
    assert got["threat.military_gap.1"].why.endswith("has 11 land units to your 5.")
    assert not any(i.subject_player == 7 and i.id.startswith("threat.war") for i in got.values())
    assert not any(i.subject_player == 3 for i in got.values())  # Napoleon is dead


def test_fixture_summary_numbers(fixture_state):
    by_player = {r.player: r for r in threat.summarize(fixture_state)}
    assert set(by_player) == {1, 2, 4, 5, 6, 7}
    assert by_player[4].at_war_since == 80 and by_player[4].kills == 6 and by_player[4].losses == 3
    assert by_player[4].latest_fight == (81, 62, 32)
    assert by_player[4].city_tiles_targeted == 19 and by_player[4].units_targeted == 5
    assert by_player[1].war_score == 202.0 and by_player[1].war_score_since == 72
    assert by_player[1].at_war_since is None and by_player[1].military_ratio == pytest.approx(2.2)
    assert by_player[7].war_score is None and by_player[7].kills == 0
