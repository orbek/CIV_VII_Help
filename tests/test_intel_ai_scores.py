from civ_advisor.advisors import intel
from civ_advisor.advisors.base import Provenance, visible
from civ_advisor.games.civ6 import CIV6
from civ_advisor.ingest.load import load_logs
from civ_advisor.state.build import build_state


def ai_score_events(state):
    return [e for e in intel.feed(state) if e.kind == "ai_score"]


def test_civ7_produces_no_ai_score_events(fixture_state):
    """Civ VII logs no scored preferences. Nothing may appear for it."""
    assert ai_score_events(fixture_state) == []


def test_the_capture_produces_research_and_policy_events(civ6_dir):
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    events = ai_score_events(state)

    assert events
    assert {e.event_type for e in events} <= {
        "ai_score.research_goal", "ai_score.tech", "ai_score.civic", "ai_score.policy",
    }
    assert {e.source for e in events} == {"AI_Research.csv", "AI_GovtPolicies.csv"}


def test_every_ai_score_event_is_oracle(civ6_dir):
    state = build_state(load_logs(civ6_dir, profile=CIV6))

    assert all(e.provenance is Provenance.ORACLE for e in ai_score_events(state))


def test_fair_mode_drops_every_one_of_them(civ6_dir):
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    fair = visible(intel.feed(state), oracle=False)

    assert all(e.kind != "ai_score" for e in fair)


def test_a_stated_research_goal_is_reported_as_the_ais_own_statement(civ6_dir):
    """Boost == GOAL is the AI naming its selection. That is a statement, and may
    be reported as one."""
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    goals = [e for e in ai_score_events(state)
             if e.event_type == "ai_score.research_goal" and 2 in e.players]

    cyrus = next(e for e in goals if e.turn == 2)
    assert "Cyrus" in cyrus.text
    assert "research goal" in cyrus.text
    assert "Writing" in cyrus.text
    assert "400.1" in cyrus.text


def test_top_scored_civics_are_named_not_interpreted(civ6_dir):
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    civics = [e for e in ai_score_events(state)
              if e.event_type == "ai_score.civic" and 2 in e.players and e.turn == 1]

    assert len(civics) == 1
    assert "scored these civics highest" in civics[0].text
    assert "Military Tradition" in civics[0].text
    assert "204.9" in civics[0].text


def test_the_human_and_independents_get_no_events(civ6_dir):
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    rivals = {p.id for p in state.rivals()}

    for e in ai_score_events(state):
        assert set(e.players) <= rivals, f"{e.text} covers a non-rival"


def test_each_player_turn_yields_at_most_one_event_per_family(civ6_dir):
    """399 rows over two turns must not become 399 events."""
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    keys = [(e.turn, e.players, e.event_type) for e in ai_score_events(state)]

    assert len(keys) == len(set(keys))
    assert len(keys) < 60


def test_the_raw_field_keeps_the_games_own_keys(civ6_dir):
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    event = next(e for e in ai_score_events(state) if e.event_type == "ai_score.research_goal")

    assert "TECH_" in event.raw


def test_every_ai_score_event_carries_its_caveat_in_the_text_itself(civ6_dir):
    """The whole-phase review's Important: the refusal to infer a victory path from a
    scored preference list lived only in this module's docstring, which ships nowhere
    -- the prompt builder reads `event.text` verbatim and the docstring never reaches
    it. The caveat must be IN the text, the same way combat_desire's caveat lives
    inside its own `why` string and so survives into the prompt naturally."""
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    events = ai_score_events(state)

    assert events, "the capture should produce at least one ai_score event"
    for e in events:
        assert intel.AI_SCORE_CAVEAT in e.text, f"{e.event_type} text carries no caveat: {e.text!r}"
