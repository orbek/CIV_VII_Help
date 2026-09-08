from civ7_advisor.advisors import Provenance, tactical
from civ7_advisor.ingest.readers import TargetRow
from civ7_advisor.ingest.tactical import OperationEvalRow, OperationRow
from civ7_advisor.state.geo import hex_distance
from civ7_advisor.state.models import GameState, Player, PlayerKind


def test_skewed_axial_hex_distance_has_six_adjacent_directions():
    origin = (10, 10)
    for neighbor in ((11, 10), (10, 11), (9, 11), (9, 10), (10, 9), (11, 9)):
        assert hex_distance(origin, neighbor) == 1
    assert hex_distance(origin, (12, 9)) == 2


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
    insights = tactical.advise(fixture_v2_state)
    assert insights and all(i.advisor == "tactical" and i.provenance is Provenance.ORACLE for i in insights)
