from civ_advisor.games.civ6 import CIV6
from civ_advisor.ingest.load import load_logs
from civ_advisor.state.build import build_state
from civ_advisor.state.models import PlayerKind


def _state(civ6_dir):
    return build_state(load_logs(civ6_dir, profile=CIV6), profile=CIV6)


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
