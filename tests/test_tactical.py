from civ_advisor.advisors import Provenance, tactical
from civ_advisor.ingest.readers import TargetRow
from civ_advisor.ingest.tactical import (
    OperationEvalRow, OperationRow, TacticalRow, UnitEfficiencyRow, UnitOperationRow,
)
from civ_advisor.state.geo import hex_distance
from civ_advisor.state.models import GameState, Player, PlayerKind
from tests.factories import city_target, combat


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


def _attack_state(observed_turn: int, now: int = 20) -> GameState:
    return GameState(
        players={
            0: Player(0, "You", PlayerKind.HUMAN, True, now),
            1: Player(1, "Rival", PlayerKind.RIVAL, True, now),
        },
        complete_through_turn=now,
        targets=[TargetRow(observed_turn, 1, "TARGET_ENEMY_CITY", 0, 9, 4, 5)],
        operations=[OperationRow(observed_turn, 1, "Attack Enemy City", (4, 5), ("Goal 4:5",))],
        operation_evals=[OperationEvalRow(observed_turn, 1, 2, "Attack Enemy City", 300, .67)],
    )


def test_a_fresh_attack_goal_is_critical_and_dated():
    state = _attack_state(observed_turn=19, now=20)
    by_id = {i.id: i for i in tactical.advise(state)}
    fresh = by_id["tactical.ordered_attack.1"]
    assert fresh.severity.name == "CRITICAL"
    assert "Turn 19" in fresh.why
    assert "tactical.stale_attack_goal.1" not in by_id
    goal = tactical.snapshot(state)["attack_goals"][0]
    assert goal["turn"] == 19 and goal["age"] == 1 and goal["fresh"] is True


def test_an_old_attack_goal_is_not_reported_as_an_immediate_objective():
    """An attack operation is re-emitted every turn the AI still holds it, so a row that
    stopped appearing is a plan that stopped — but silence is not safety either."""
    state = _attack_state(observed_turn=10, now=20)
    by_id = {i.id: i for i in tactical.advise(state)}
    assert "tactical.ordered_attack.1" not in by_id
    stale = by_id["tactical.stale_attack_goal.1"]
    assert stale.severity.name == "ADVISE"
    assert "10 turns before turn 20" in stale.why
    assert "not evidence the objective was dropped" in stale.why
    assert "immediate" not in stale.recommendation.lower()
    assert "10 turns old" in by_id["tactical.odds.1"].why
    goal = tactical.snapshot(state)["attack_goals"][0]
    assert goal["age"] == 10 and goal["fresh"] is False


def test_known_city_area_tiles_carry_the_turn_they_were_observed_on():
    state = _attack_state(observed_turn=14, now=20)
    snap = tactical.snapshot(state)
    assert snap["city_tile_turn"] == 14
    assert snap["city_tiles"] == [{"x": 4, "y": 5, "turn": 14, "age": 6}]
    assert snap["goal_fresh_turns"] == tactical.GOAL_FRESH_TURNS
    assert tactical.city_tile_observations(state) == {(4, 5): 14}


def _two_frontier_state(now: int = 20) -> GameState:
    """Two city areas far apart, with contacts near each and one exposed unit between."""
    tiles = [(10, 10), (11, 10), (10, 11)] + [(70, 40), (71, 40)]
    return GameState(
        players={
            0: Player(0, "You", PlayerKind.HUMAN, True, now),
            1: Player(1, "Rival One", PlayerKind.RIVAL, True, now),
            2: Player(2, "Rival Two", PlayerKind.RIVAL, True, now),
        },
        complete_through_turn=now,
        targets=[city_target(now, 1, owner=0, x=x, y=y) for x, y in tiles]
        + [TargetRow(now, 1, "TARGET_HIGH_PRIORITY_UNIT", 0, 900, 40, 25)],
        unit_operations=[UnitOperationRow(now, "Adding", 0, "UNIT_SCOUT", 900, "UNITOPERATION_ALERT")],
        tactical=[
            TacticalRow(now, 1, "Attack Units", "", None, None, None,
                        "UNIT_SPEARMAN", 5001, (12, 12), None, ()),
            TacticalRow(now, 1, "Attack Units", "", None, None, None,
                        "UNIT_ARCHER", 5002, (13, 12), None, ()),
            TacticalRow(now, 1, "Attack Units", "", None, None, None,
                        "UNIT_ARCHER", 5003, (13, 12), None, ()),
            TacticalRow(now, 2, "Attack Units", "", None, None, None,
                        "UNIT_IMMORTAL", 5004, (72, 41), None, ()),
            TacticalRow(now, 1, "Attack Units", "", None, None, None,
                        "UNIT_SCOUT", 5007, (41, 26), None, ()),
        ],
    )


def test_distant_city_areas_are_separate_frontiers():
    """One viewBox around both would be a picture of the sea between them."""
    state = _two_frontier_state()
    clusters = tactical.city_clusters(state)
    assert [c["id"] for c in clusters] == ["area-10-10", "area-70-40"]
    assert [len(c["tiles"]) for c in clusters] == [3, 2]
    # Labelled by coordinates: the source is a list of plots and says nothing about which
    # settlement any plot belongs to, so no settlement name is invented.
    assert clusters[0]["label"] == "Area around 10:10"
    assert all("tiles" in c and c["turn"] == 20 for c in clusters)
    assert clusters[0]["bounds"] == {"min_x": 10, "max_x": 11, "min_y": 10, "max_y": 11}


def test_a_contact_belongs_to_a_frontier_only_when_it_is_actually_near_one():
    snap = tactical.snapshot(_two_frontier_state())
    by_key = {u["key"]: u for u in snap["enemy_units"]}
    assert by_key["1:5001"]["cluster"] == "area-10-10"
    assert by_key["2:5004"]["cluster"] == "area-70-40"
    # Nearest to *something* by arithmetic, but nowhere near it.
    stray = by_key["1:5007"]
    assert stray["cluster"] is None and stray["near"] is False
    assert stray["nearest_cluster"] is not None and stray["distance_to_city"] > tactical.MAP_NEAR_TILES


def test_a_contact_keeps_a_stable_identity_as_it_moves():
    """Selecting a row selects the same unit on the map, and keeps doing so next turn."""
    first = tactical.snapshot(_two_frontier_state())
    moved = _two_frontier_state()
    moved.tactical = [
        r if r.unit_id != 5001 else type(r)(**(r.__dict__ | {"move": (11, 12)}))
        for r in moved.tactical
    ]
    second = tactical.snapshot(moved)
    before = next(u for u in first["enemy_units"] if u["key"] == "1:5001")
    after = next(u for u in second["enemy_units"] if u["key"] == "1:5001")
    assert (before["x"], before["y"]) != (after["x"], after["y"])
    assert before["key"] == after["key"] == "1:5001"


def test_a_distant_exposed_unit_gets_its_own_focus():
    """Stretching a frontier's bounds to include it would shrink the frontier itself."""
    snap = tactical.snapshot(_two_frontier_state())
    exposed = [u for u in snap["human_units"] if u["exposed"]]
    assert [u["key"] for u in exposed] == ["0:900"]
    unit = exposed[0]
    assert unit["distance_to_enemy"] <= tactical.NEAR_TILES
    assert unit["distance_to_city"] > tactical.MAP_NEAR_TILES
    assert unit["cluster"] is None


def test_every_contact_is_in_the_snapshot_however_many_there_are():
    """The old twelve-position cap is gone: the payload carries them all and the browser
    pages through them."""
    state = _two_frontier_state()
    state.tactical = [
        TacticalRow(20, 1, "Attack Units", "", None, None, None,
                    "UNIT_ARCHER", 6000 + n, (12 + n % 3, 12), None, ())
        for n in range(30)
    ]
    snap = tactical.snapshot(state)
    assert len(snap["enemy_units"]) == 30
    assert len({u["key"] for u in snap["enemy_units"]}) == 30


def test_missing_tactical_data_cannot_be_read_as_safe():
    """No city area and no contact is a gap in these logs, and the snapshot says nothing
    that could be mistaken for an all-clear."""
    state = GameState(
        players={0: Player(0, "You", PlayerKind.HUMAN, True, 20),
                 1: Player(1, "Rival", PlayerKind.RIVAL, True, 20)},
        complete_through_turn=20,
    )
    snap = tactical.snapshot(state)
    assert snap["available"] is False
    assert snap["clusters"] == [] and snap["enemy_units"] == []
    assert snap["city_tile_turn"] is None
    assert "safe" not in repr(snap) and "clear" not in repr(snap)
