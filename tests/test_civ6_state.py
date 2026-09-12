from civ_advisor.games.civ6 import CIV6
from civ_advisor.ingest.load import load_logs
from civ_advisor.state.build import build_state
from civ_advisor.state.models import PlayerKind


def _state(civ6_dir):
    return build_state(load_logs(civ6_dir, profile=CIV6))


def test_stats_rows_arrive_under_real_player_ids(civ6_dir):
    state = _state(civ6_dir)
    human = state.at(0, turn=53)
    assert human is not None
    assert human.cities == 2
    assert human.gold_balance == 98.0


def test_players_are_classified_by_their_logged_level_not_by_id_range(civ6_dir):
    state = _state(civ6_dir)
    assert state.players[0].kind is PlayerKind.HUMAN
    assert state.players[1].kind is PlayerKind.RIVAL
    assert state.players[6].kind is PlayerKind.INDEPENDENT   # city-state
    assert state.players[62].kind is PlayerKind.INDEPENDENT  # Free Cities
    assert len(state.rivals()) == 5


def test_rivals_are_named_from_their_leader(civ6_dir):
    state = _state(civ6_dir)
    assert state.players[1].name == "Robert The Bruce"


def test_no_victory_strategies_are_claimed_for_civ6(civ6_dir):
    """Civ VI's AI_Victories is not declared, so nothing may populate this."""
    state = _state(civ6_dir)
    assert state.strategies == {}


def test_unavailable_signals_are_none_not_zero(civ6_dir):
    state = _state(civ6_dir)
    human = state.at(0, turn=53)
    assert human.happiness is None
    assert human.total_maintenance is None
    assert human.net_gold is None


def test_the_four_oracle_logs_parse_and_reach_the_state(civ6_dir):
    from civ_advisor.games.civ6 import CIV6
    from civ_advisor.ingest.load import load_logs
    from civ_advisor.state.build import build_state

    raw = load_logs(civ6_dir, profile=CIV6)
    for name in ("AI_Military.csv", "DiplomacyModifiers.csv",
                 "AI_Research.csv", "AI_GovtPolicies.csv"):
        status = raw.files[name]
        assert status.ok, f"{name}: {status.error}"
        assert status.rows > 0, f"{name} parsed but is empty"

    state = build_state(raw)
    assert len(state.military) == 833
    assert len(state.diplomacy_modifiers) == 22
    assert len(state.tech_scores) == 399
    assert len(state.policy_scores) == 399


def test_civ6_declares_the_four_new_capabilities(civ6_dir):
    from civ_advisor.games.base import Capability
    from civ_advisor.games.civ6 import CIV6

    assert CIV6.supports(Capability.COMBAT_DESIRE)
    assert CIV6.supports(Capability.DIPLOMATIC_MODIFIERS)
    assert CIV6.supports(Capability.RESEARCH_PREFERENCE)
    assert CIV6.supports(Capability.POLICY_PREFERENCE)


def test_civ7_declares_none_of_them():
    """Civ VII writes none of these four files. A capability declared there
    would promise a panel nothing can fill."""
    from civ_advisor.games.base import Capability
    from civ_advisor.games.civ7 import CIV7

    for capability in (Capability.COMBAT_DESIRE, Capability.DIPLOMATIC_MODIFIERS,
                       Capability.RESEARCH_PREFERENCE, Capability.POLICY_PREFERENCE):
        assert not CIV7.supports(capability)
    for name in ("AI_Military.csv", "DiplomacyModifiers.csv",
                 "AI_Research.csv", "AI_GovtPolicies.csv"):
        assert name not in CIV7.log_files


def test_a_civ7_state_reports_these_signals_as_empty_not_zero(fixture_state):
    """Civ VII has no such logs, so the lists are empty. Nothing downstream may
    turn that into a number -- Task 4 and Task 6 assert the advisors' side."""
    assert fixture_state.military == []
    assert fixture_state.diplomacy_modifiers == []
    assert fixture_state.tech_scores == []
    assert fixture_state.policy_scores == []
