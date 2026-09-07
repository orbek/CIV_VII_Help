import pytest

from civ7_advisor.ingest.load import RawLogs
from civ7_advisor.state.build import build_state, display_name
from civ7_advisor.state.models import PlayerKind, StrategyStatus


def test_turn_bookkeeping(fixture_state):
    assert fixture_state.latest_turn == 82
    assert fixture_state.complete_through_turn == 81


def test_player_classification(fixture_state):
    s = fixture_state
    assert s.human().kind is PlayerKind.HUMAN and s.human().alive
    assert [p.id for p in s.rivals()] == [1, 2, 4, 5, 6, 7]
    assert [p.id for p in s.rivals(alive_only=False)] == [1, 2, 3, 4, 5, 6, 7]
    napoleon = s.players[3]
    assert (napoleon.name, napoleon.kind, napoleon.alive, napoleon.last_seen_turn) == (
        "Napoleon", PlayerKind.RIVAL, False, 59,
    )
    assert s.players[4].name == "José Rizal"
    assert s.players[7].name == "Catherine"
    assert s.players[9].kind is PlayerKind.INDEPENDENT
    assert [p.id for p in s.majors()] == [0, 1, 2, 4, 5, 6, 7]


def test_player_turn_merges_treasury_and_happiness(fixture_state):
    pt = fixture_state.at(0)  # defaults to the complete turn, 81
    assert pt.turn == 81
    assert pt.land_units == 5 and pt.science == 15.0
    assert (pt.unit_maintenance, pt.building_maintenance, pt.total_maintenance) == (2, 2, 4)
    assert pt.net_gold == 19.0  # gold 23.0 - maintenance 4
    assert (pt.happiness_total, pt.happiness_threshold, pt.golden_age) == (1038, 1532, False)
    assert pt.celebration_progress == pytest.approx(1038 / 1532)
    assert pt.settlements == 2 and pt.military_units == 5


def test_independent_has_treasury_but_no_happiness(fixture_state):
    pt = fixture_state.at(9)
    assert pt is not None and pt.total_maintenance is not None  # treasury covers all players
    assert pt.happiness_threshold is None and pt.celebration_progress is None


def test_strategies_fold_to_current_status(fixture_state):
    st = fixture_state.strategies
    assert st[4]["CULTURAL"] == StrategyStatus(4, "CULTURAL", "Following", 100, since_turn=74)
    assert st[1]["CULTURAL"].status == "Stopped" and st[1]["CULTURAL"].since_turn == 80
    assert st[7]["SCIENCE"].weight == 100 and st[7]["SCIENCE"].following
    assert 0 not in st  # the human has no AI strategy rows


def test_series_reads_backwards_from_complete_turn(fixture_state):
    assert fixture_state.series(0, "land_units", 3) == [7.0, 6.0, 5.0]  # turns 79, 80, 81
    assert fixture_state.series(3, "land_units", 3) == []  # Napoleon is gone


def test_raw_rows_are_carried_through(fixture_state):
    assert len(fixture_state.intents) == 2422
    assert len(fixture_state.targets) == 47025
    assert len(fixture_state.events) == 190
    assert set(fixture_state.files) and all(f.ok for f in fixture_state.files.values())


def test_empty_logs_give_empty_state():
    state = build_state(RawLogs())
    assert state.latest_turn == 0 and state.players == {} and state.human() is None
    assert state.rivals() == [] and state.majors() == [] and state.at(0) is None


def test_display_name_fallback():
    assert display_name("LOC_LEADER_CONFUCIUS_NAME") == "Confucius"
    assert display_name("LOC_LEADER_SOME_NEW_LEADER_NAME") == "Some New Leader"
