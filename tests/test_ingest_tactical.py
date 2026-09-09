from pathlib import Path

from civ7_advisor.ingest.tactical import (
    read_combat_planning, read_operation_evals, read_operations, read_tactical,
    read_unit_efficiency, read_unit_operations,
)


def test_ragged_tactical_attack_and_combat_order_are_reconstructed(tmp_path: Path):
    tactical = tmp_path / "AI_Tactical.csv"
    tactical.write_text(
        "Game Turn, Player, Category, Target Type, Target Info, Unit Info, Extra\n"
        "15,13,Attack Units,TARGET_LOW_PRIORITY_UNIT,UNIT_SCOUT (131072:0),UNIT_WARRIOR (196610),"
        "Expected Damage: 0,Move 11 14 Attack 11 13,Army\n"
    )
    row = read_tactical(tactical)[0]
    assert (row.unit_type, row.unit_id, row.target_owner) == ("UNIT_WARRIOR", 196610, 0)
    assert row.move == (11, 14) and row.attack == (11, 13)

    planning = tmp_path / "AI_CombatPlanning.csv"
    planning.write_text(
        "Game Turn, Player, Category, Info\n"
        "15,13,Order,Unit 196610,Move 11:14,Do attack\n"
    )
    order = read_combat_planning(planning)[0]
    assert order.unit_id == 196610 and order.move == (11, 14) and order.attacks


def test_operations_accept_normal_and_swapped_battle_line_rows(tmp_path: Path):
    path = tmp_path / "AI_Operation.csv"
    path.write_text(
        "Game Turn, Player, Operation, Notes, Team, Team Notes, Team Members, Terrain\n"
        "99,3,Attack Enemy City,Operation Move Army,UNIT_WARRIOR,Goal 14:26,Start 18:36,End 16:35,SOLO\n"
        "99,Attack Enemy City,3,,Battle line,14:26,0 endangered\n"
    )
    rows = read_operations(path)
    assert rows[0].player == 3 and rows[0].goal == (14, 26)
    assert rows[1].player == 3 and rows[1].operation == "Attack Enemy City"


def test_unit_operation_eval_and_efficiency_shapes(tmp_path: Path):
    operations = tmp_path / "UnitOperations.log"
    operations.write_text(
        "Game Turn, Mode, Player, Unit, Operation\n"
        "001,Adding,0,UNIT_WARRIOR (7),UNITOPERATION_MOVE_TO (9)\n"
    )
    assert read_unit_operations(operations)[0].unit_id == 7

    evals = tmp_path / "AI_Operation_Eval.csv"
    evals.write_text(
        "Game Turn, Player, Operation, Enemy, Value, Odds\n"
        "11,2,-1,Attack Enemy City,427.1,0.38\n"
    )
    assert read_operation_evals(evals)[0].odds == 0.38

    efficiency = tmp_path / "AI_UnitEfficiency.csv"
    efficiency.write_text(",UNIT_WARRIOR,UNIT_ARCHER\nUNIT_WARRIOR,100,125\nUNIT_ARCHER,80,100\n")
    assert read_unit_efficiency(efficiency)[0].ratings["UNIT_ARCHER"] == 125
