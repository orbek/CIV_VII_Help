from civ7_advisor.advisors import Provenance, tactical
from civ7_advisor.ingest.readers import TargetRow
from civ7_advisor.ingest.tactical import (
    OperationEvalRow, OperationRow, TacticalRow, UnitEfficiencyRow, UnitOperationRow,
)
from civ7_advisor.state.geo import hex_distance
from civ7_advisor.state.models import GameState, Player, PlayerKind
from tests.factories import combat


def test_odd_row_offset_hex_distance_has_six_adjacent_directions():
    even = (10, 10)
    for neighbor in ((9, 9), (10, 9), (9, 10), (11, 10), (9, 11), (10, 11)):
        assert hex_distance(even, neighbor) == 1
    odd = (10, 11)
    for neighbor in ((10, 10), (11, 10), (9, 11), (11, 11), (10, 12), (11, 12)):
        assert hex_distance(odd, neighbor) == 1
    assert hex_distance(even, (12, 10)) == 2


def test_fixture_melee_move_attack_pairs_pin_odd_row_orientation():
    assert hex_distance((70, 20), (69, 21)) == 1  # even row shifts left
    assert hex_distance((72, 21), (73, 22)) == 1  # odd row shifts right


def test_attack_goal_on_human_city_tile_emits_critical_and_odds():
    state = GameState(
        players={
            0: Player(0, "You", PlayerKind.HUMAN, True, 10),
            1: Player(1, "Rival", PlayerKind.RIVAL, True, 10),
        },
        complete_through_turn=10,
        targets=[TargetRow(10, 1, "TARGET_ENEMY_CITY", 0, 9, 4, 5)],
        operations=[OperationRow(10, 1, "Attack Enemy City", (4, 5), ("Goal 4:5",))],
        operation_evals=[OperationEvalRow(10, 1, 2, "Attack Enemy City", 300, .67)],
    )
    insights = tactical.advise(state)
    by_id = {i.id: i for i in insights}
    assert by_id["tactical.ordered_attack.1"].severity.name == "CRITICAL"
    assert by_id["tactical.odds.1"].provenance is Provenance.ORACLE
    assert tactical.snapshot(state)["attack_goals"][0]["x"] == 4


def test_live_tactical_fixture_has_typed_map_and_oracle_advice(fixture_v2_state):
    snap = tactical.snapshot(fixture_v2_state)
    assert snap["available"] and snap["city_tiles"] and snap["enemy_units"]
    assert snap["map_near_tiles"] == tactical.MAP_NEAR_TILES
    assert all("distance_to_city" in unit and "nearest_city_tile" in unit
               for unit in snap["enemy_units"])
    assert len(snap["human_units"]) >= 5
    assert any(u["unit_id"] == 1703946 and (u["x"], u["y"]) == (16, 10)
               for u in snap["human_units"])
    assert snap["commander_promotions"] and all("name" in p for p in snap["commander_promotions"])
    insights = tactical.advise(fixture_v2_state)
    assert insights and all(i.advisor == "tactical" and i.provenance is Provenance.ORACLE for i in insights)


def test_matchup_covers_each_nearby_type_and_exposed_uses_target_join():
    state = GameState(
        players={
            0: Player(0, "You", PlayerKind.HUMAN, True, 10),
            1: Player(1, "Rival", PlayerKind.RIVAL, True, 10),
        },
        complete_through_turn=10,
        targets=[
            TargetRow(10, 1, "TARGET_ENEMY_CITY", 0, 1, 10, 10),
            TargetRow(10, 1, "TARGET_HIGH_PRIORITY_UNIT", 0, 7, 9, 10),
        ],
        unit_operations=[
            UnitOperationRow(10, "Adding", 0, "UNIT_WARRIOR", 7, "UNITOPERATION_ALERT"),
            UnitOperationRow(10, "Adding", 0, "UNIT_ARCHER", 8, "UNITOPERATION_ALERT"),
        ],
        tactical=[
            TacticalRow(10, 1, "Attack Units", "", None, None, None,
                        "UNIT_SPEARMAN", 70, (11, 10), None, ()),
            TacticalRow(10, 1, "Attack Units", "", None, None, None,
                        "UNIT_ARCHER", 71, (10, 11), None, ()),
        ],
        unit_efficiency=[
            UnitEfficiencyRow(0, "UNIT_WARRIOR", {"UNIT_SPEARMAN": 150, "UNIT_ARCHER": 80}),
            UnitEfficiencyRow(0, "UNIT_ARCHER", {"UNIT_SPEARMAN": 90, "UNIT_ARCHER": 140}),
        ],
        combats=[combat(10, 0, 1, "Attacker", "UNIT_WARRIOR", "UNIT_SPEARMAN")],
    )
    by_id = {i.id: i for i in tactical.advise(state)}
    assert "Spearman → Warrior" in by_id["tactical.matchup"].recommendation
    assert "Archer → Archer" in by_id["tactical.matchup"].recommendation
    assert "Recent realized combat disagreed for Warrior vs Spearman" in by_id["tactical.matchup"].why
    assert "your Warrior at 9:10" in by_id["tactical.own_exposed"].why
