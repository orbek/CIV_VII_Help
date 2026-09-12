from dataclasses import fields

import pytest

from civ_advisor.ingest.load import RawLogs
from civ_advisor.ingest.readers import StatsRow
from civ_advisor.state.build import build_state, display_name
from civ_advisor.state.models import PlayerKind, PlayerTurn, StrategyStatus


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
    assert st[4]["CULTURAL"] == StrategyStatus(
        player=4, strategy="CULTURAL", status="Following", since_turn=74, weight=100,
    )
    assert st[1]["CULTURAL"].status == "Stopped" and st[1]["CULTURAL"].since_turn == 80
    assert st[7]["SCIENCE"].weight == 100 and st[7]["SCIENCE"].following
    assert 0 not in st  # the human has no AI strategy rows


def test_series_reads_backwards_from_complete_turn(fixture_state):
    assert fixture_state.series(0, "land_units", 3) == [7.0, 6.0, 5.0]  # turns 79, 80, 81
    assert fixture_state.series(3, "land_units", 3) == []  # Napoleon is gone


def test_series_skips_missing_values(fixture_state):
    # Player 9 is an independent: it has stats and treasury rows but no happiness row,
    # so happiness_total is None on every turn. series must skip, not raise.
    assert fixture_state.series(9, "happiness_total", 3) == []
    assert fixture_state.series(9, "land_units", 3) == [3.0, 3.0, 3.0]


def test_player_turn_covers_every_stats_field():
    assert {f.name for f in fields(StatsRow)} <= {f.name for f in fields(PlayerTurn)}


def test_raw_rows_are_carried_through(fixture_state):
    assert len(fixture_state.intents) == 2422
    assert len(fixture_state.targets) == 47025
    assert len(fixture_state.events) == 190
    from tests.test_ingest_load import V1_FILES
    assert all(fixture_state.files[name].ok for name in V1_FILES)


def test_empty_logs_give_empty_state():
    state = build_state(RawLogs())
    assert state.latest_turn == 0 and state.players == {} and state.human() is None
    assert state.rivals() == [] and state.majors() == [] and state.at(0) is None


def test_display_name_fallback():
    assert display_name("LOC_LEADER_CONFUCIUS_NAME") == "Confucius"
    assert display_name("LOC_LEADER_SOME_NEW_LEADER_NAME") == "Some New Leader"


def test_new_rows_are_carried_and_peace_is_folded():
    from civ_advisor.ingest.load import RawLogs
    from civ_advisor.ingest.readers import StatsRow
    from tests.factories import build_queue_row, combat, deal, diplo_event, gossip_row

    def stats(turn, player):
        return StatsRow(
            turn=turn, player=player, cities=1, techs=1, land_units=2, naval_units=0,
            tiles_owned=5, tiles_improved=1, gold_balance=10.0, science=1, culture=1, gold=1,
            production=1, food=1, towns=0, settlement_cap=3, settlements_over_cap=0,
            urban_pop=1, rural_pop=2, happiness=1, diplomacy=0,
        )

    raw = RawLogs(
        stats=[stats(1, 0), stats(1, 4), stats(2, 0), stats(2, 4), stats(3, 0)],
        build_queue=[build_queue_row(2, 0, city="LOC_CITY_NAME_MAURYA1")],
        combat=[combat(2, 0, 4, destroyed="Attacker")],
        gossip=[gossip_row(2, "Alexander", "Maurya")],
        diplomacy_summary=[diplo_event(2, 0, 4)],
        deals=[deal(1, 4, 0, "Peace"), deal(2, 4, 0, "Peace"), deal(2, 1, 7, "Peace"), deal(2, 4, 0, "Open Borders")],
    )
    s = build_state(raw)
    assert len(s.build_queues) == 1 and len(s.combats) == 1 and len(s.gossip) == 1
    assert len(s.diplomacy_events) == 1 and len(s.deals) == 4
    assert s.peace_turns == {frozenset({0, 4}): 2, frozenset({1, 7}): 2}
    assert s.peace_between(0, 4) == 2 and s.peace_between(4, 0) == 2 and s.peace_between(0, 7) is None
    assert s.names is not None and s.names.player_for("Alexander", "Maurya") == 0


def test_empty_state_has_empty_collections_and_no_resolver():
    s = build_state(RawLogs())
    assert s.build_queues == [] and s.combats == [] and s.deals == [] and s.peace_turns == {}
    assert s.names is None and s.peace_between(0, 1) is None


def test_gamecore_identity_classifies_and_names_rival_without_event_rows():
    from civ_advisor.ingest.textlogs import PlayerIdentityRow

    raw = RawLogs(
        stats=[
            StatsRow(
                turn=1, player=player, cities=1, techs=1, land_units=2, naval_units=0,
                tiles_owned=5, tiles_improved=1, gold_balance=10.0, science=1, culture=1,
                gold=1, production=1, food=1, towns=0, settlement_cap=3,
                settlements_over_cap=0, urban_pop=1, rural_pop=2, happiness=1, diplomacy=0,
            )
            for player in (0, 1)
        ],
        player_identities=[
            PlayerIdentityRow(0, 0, "CIVILIZATION_AMERICA", "LEADER_BENJAMIN_FRANKLIN",
                              "CIVILIZATION_LEVEL_FULL_CIV", "Human"),
            PlayerIdentityRow(0, 1, "CIVILIZATION_PERSIA", "LEADER_XERXES",
                              "CIVILIZATION_LEVEL_FULL_CIV", "AI"),
        ],
    )
    state = build_state(raw)
    assert state.players[1].kind is PlayerKind.RIVAL and state.players[1].name == "Xerxes"
    assert state.names is not None and state.names.player_for("Benjamin Franklin") == 0


def test_optional_stats_fields_default_to_none_not_zero():
    """A game that cannot supply happiness must yield None. 0.0 would read as
    'this civ is miserable' rather than 'this game has no such concept'."""
    from civ_advisor.state.models import PlayerTurn

    pt = PlayerTurn(turn=1, player=0, cities=1, techs=2, land_units=1,
                    naval_units=0, tiles_owned=5, tiles_improved=1,
                    gold_balance=10.0, science=1.0, culture=1.0, gold=2.0,
                    production=3.0, food=4.0)
    assert pt.happiness is None
    assert pt.towns is None
    assert pt.settlement_cap is None
    assert pt.diplomacy is None
