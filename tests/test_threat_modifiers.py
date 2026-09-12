from civ_advisor.advisors import threat
from civ_advisor.advisors.base import Provenance, Severity
from tests.factories import game_state, modifier_row


def ids(insights):
    return {i.id: i for i in insights}


def test_no_modifier_rows_produce_no_grievances():
    s = game_state(turn=20)
    assert threat.summarize(s)[0].grievances == ()
    assert "threat.grievances.1" not in ids(threat.advise(s))


def test_a_standing_negative_modifier_is_reported_verbatim_and_oracle():
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [
        modifier_row(12, 0, 1, "They dislike civilizations with a small standing army", -6.0),
    ]
    got = ids(threat.advise(s))["threat.grievances.1"]

    assert got.provenance is Provenance.ORACLE
    assert got.severity is Severity.ADVISE            # -6.0 is past GRIEVANCE_ADVISE
    assert "They dislike civilizations with a small standing army" in got.why
    assert "-6.0" in got.why
    assert "turn 12" in got.why


def test_the_evidence_refuses_to_attribute_the_opinion_to_a_side():
    """The log records the pair but never which side holds the modifier, and the
    advisor may not fill that in."""
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [modifier_row(12, 0, 1, "Settled near them", -3.0)]
    why = ids(threat.advise(s))["threat.grievances.1"].why

    assert "does not record which side" in why


def test_a_deactivated_modifier_stops_counting():
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [
        modifier_row(12, 0, 1, "Settled near them", -3.0),
        modifier_row(14, 0, 1, "Settled near them", action="Deactivate"),
    ]
    assert threat.summarize(s)[0].grievances == ()


def test_an_update_replaces_the_value_rather_than_adding_to_it():
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [
        modifier_row(12, 0, 1, "First impressions of you", -4.0),
        modifier_row(18, 0, 1, "First impressions of you", -1.0, action="Update"),
    ]
    grievances = threat.summarize(s)[0].grievances

    assert [(g.turn, g.value) for g in grievances] == [(18, -1.0)]


def test_a_modifier_that_updated_to_zero_is_no_longer_a_grievance():
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [
        modifier_row(12, 0, 1, "First impressions of you", -4.0),
        modifier_row(18, 0, 1, "First impressions of you", 0.0, action="Update"),
    ]
    assert threat.summarize(s)[0].grievances == ()


def test_the_two_orderings_stay_separate_ledgers():
    """(0,1) and (1,0) are two ledgers. Merging them would sum two opinions
    neither of which can be attributed."""
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [
        modifier_row(12, 0, 1, "First impressions of you", -4.0),
        modifier_row(12, 1, 0, "First impressions of you", -2.0),
    ]
    grievances = threat.summarize(s)[0].grievances

    assert len(grievances) == 2
    assert {g.pair for g in grievances} == {(0, 1), (1, 0)}


def test_modifiers_not_involving_the_human_are_ignored():
    s = game_state(turn=20, rivals={1: "Rival One", 2: "Rival Two"})
    s.diplomacy_modifiers = [modifier_row(48, 2, 1, "Settled near them", -9.0)]
    got = ids(threat.advise(s))

    assert "threat.grievances.1" not in got
    assert "threat.grievances.2" not in got


def test_a_mild_grievance_is_info_not_advise():
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [modifier_row(12, 0, 1, "First impressions of you", -1.0)]
    assert ids(threat.advise(s))["threat.grievances.1"].severity is Severity.INFO


def test_the_capture_produces_kupes_ledger(civ6_dir):
    from civ_advisor.games.civ6 import CIV6
    from civ_advisor.ingest.load import load_logs
    from civ_advisor.state.build import build_state

    state = build_state(load_logs(civ6_dir, profile=CIV6))
    got = ids(threat.advise(state))["threat.grievances.5"]

    assert got.provenance is Provenance.ORACLE
    assert got.severity is Severity.ADVISE
    assert "Likes civs who respect the environment" in got.why
