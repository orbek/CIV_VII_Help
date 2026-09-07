from pathlib import Path

import pytest

from civ7_advisor.ingest.csvfile import LogFormatError
from civ7_advisor.ingest.events import Combatant, CombatRow, DiplomacySummaryRow, GossipRow, read_combat_log, read_diplomacy_summary, read_gossip

COMBAT_HEADER = ("Turn, SourceType, Location, AttPlayer, DefPlayer, CombatType, Attacker, Defender, AttStr, DefStr, "
                 "AttStrMod, DefStrMod, AttDmg, DefDmg, Destroyed, HealAmount, attHealth, defHealth\n")
# Captured live 2026-09-07: the human's Warrior attacking Rizal's city centre and dying. Note the
# file uses NO space after commas, unlike every other Civ VII log.
LIVE_COMBAT = ("82,Unit vs Location,(63)(30),0,4,Melee,(14)UNIT_WARRIOR,(-1)LOC_DISTRICT_CITY_CENTER_NAME,"
               "20,30,-5,0,34,12,Attacker,0,(0)100,(8)100\n")


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "CombatLog.csv"
    p.write_text(COMBAT_HEADER + body)
    return p


def test_reads_the_live_row_including_parenthesised_fields(tmp_path: Path):
    [row] = read_combat_log(_write(tmp_path, LIVE_COMBAT))
    assert (row.turn, row.source_type, row.x, row.y) == (82, "Unit vs Location", 63, 30)
    assert (row.att_player, row.def_player, row.combat_type) == (0, 4, "Melee")
    assert row.attacker == Combatant(14, "UNIT_WARRIOR")
    assert row.defender == Combatant(None, "LOC_DISTRICT_CITY_CENTER_NAME")
    assert (row.att_str, row.def_str, row.att_str_mod, row.def_str_mod) == (20, 30, -5, 0)
    assert (row.att_dmg, row.def_dmg, row.destroyed, row.heal_amount) == (34, 12, "Attacker", 0)
    assert (row.att_health_raw, row.def_health_raw) == ("(0)100", "(8)100")


def test_parties_involves_and_loser():
    row = read_combat_log_row_for_test()
    assert row.parties() == frozenset({0, 4})
    assert row.involves(0) and row.involves(4) and not row.involves(1)
    assert row.loser() == 0  # the attacker (player 0) was destroyed


def read_combat_log_row_for_test() -> CombatRow:
    return CombatRow(82, "Unit vs Location", 63, 30, 0, 4, "Melee", Combatant(14, "UNIT_WARRIOR"),
                     Combatant(None, "LOC_DISTRICT_CITY_CENTER_NAME"), 20, 30, -5, 0, 34, 12, "Attacker",
                     0, "(0)100", "(8)100")


@pytest.mark.parametrize("destroyed,expected", [("Defender", 4), ("", None)])
def test_loser_follows_the_destroyed_column(destroyed, expected):
    base = read_combat_log_row_for_test()
    row = CombatRow(**{**base.__dict__, "destroyed": destroyed or None})
    assert row.loser() == expected


def test_empty_destroyed_becomes_none(tmp_path: Path):
    body = LIVE_COMBAT.replace(",Attacker,", ",,")
    [row] = read_combat_log(_write(tmp_path, body))
    assert row.destroyed is None


def test_header_mismatch_raises(tmp_path: Path):
    p = tmp_path / "CombatLog.csv"
    p.write_text("Turn,Attacker\n1,x\n")
    with pytest.raises(LogFormatError, match="unexpected header"):
        read_combat_log(p)


def test_malformed_location_raises_log_format_error(tmp_path: Path):
    body = LIVE_COMBAT.replace("(63)(30)", "63:30")
    with pytest.raises(LogFormatError, match="Location"):
        read_combat_log(_write(tmp_path, body))


GOSSIP_HEADER = "Game Turn, Player, Civilization, Plot X, Plot Y, Type\n"
# Captured live 2026-09-07. `Player` is a leader NAME; the row has one more column than the header.
LIVE_GOSSIP = "82, Alexander, Maurya, 63, 31, GOSSIP_UNIT_DESTROYED, Warrior\n"


def test_gossip_reads_the_live_row_with_its_trailing_detail(tmp_path: Path):
    p = tmp_path / "Game_Gossip.csv"
    p.write_text(GOSSIP_HEADER + LIVE_GOSSIP)
    assert read_gossip(p) == [GossipRow(82, "Alexander", "Maurya", 63, 31, "GOSSIP_UNIT_DESTROYED", "Warrior")]


def test_gossip_accepts_six_columns_with_no_detail(tmp_path: Path):
    p = tmp_path / "Game_Gossip.csv"
    p.write_text(GOSSIP_HEADER + "5, Confucius, Han, 40, 12, GOSSIP_CITY_FOUNDED\n")
    [row] = read_gossip(p)
    assert (row.leader, row.civilization, row.type, row.detail) == ("Confucius", "Han", "GOSSIP_CITY_FOUNDED", None)


def test_gossip_treats_an_empty_seventh_cell_as_no_detail(tmp_path: Path):
    p = tmp_path / "Game_Gossip.csv"
    p.write_text(GOSSIP_HEADER + "5, Confucius, Han, 40, 12, GOSSIP_CITY_FOUNDED,\n")
    assert read_gossip(p)[0].detail is None


def test_gossip_rejects_other_widths(tmp_path: Path):
    p = tmp_path / "Game_Gossip.csv"
    p.write_text(GOSSIP_HEADER + "5, Confucius, Han, 40\n")
    with pytest.raises(LogFormatError, match="6 or 7 columns"):
        read_gossip(p)


def test_gossip_rejects_an_eighth_column(tmp_path: Path):
    p = tmp_path / "Game_Gossip.csv"
    p.write_text(GOSSIP_HEADER + "5, Confucius, Han, 40, 12, GOSSIP_CITY_FOUNDED, Warrior, spare\n")
    with pytest.raises(LogFormatError, match="6 or 7 columns"):
        read_gossip(p)


DIPLO_HEADER = "Game Turn, Initiator, Recipient, Action, Details, Mayhem, Visibility\n"
# Captured live 2026-09-07: seven header names, six values. The trailing cells are kept raw.
LIVE_DIPLO = ("82, 0, 7, Diplomacy Action Enter Stage, "
              "Cultural Exchange Entering Stage DIPLOMACY_CULTURAL_EXCHANGE_COMPLETE,  426.0\n")


def test_diplomacy_summary_keeps_trailing_cells_raw(tmp_path: Path):
    p = tmp_path / "DiplomacySummary.csv"
    p.write_text(DIPLO_HEADER + LIVE_DIPLO)
    [row] = read_diplomacy_summary(p)
    assert (row.turn, row.initiator, row.recipient) == (82, 0, 7)
    assert row.action == "Diplomacy Action Enter Stage"
    assert row.details == "Cultural Exchange Entering Stage DIPLOMACY_CULTURAL_EXCHANGE_COMPLETE"
    assert row.extra == ("426.0",)
    assert row.parties() == frozenset({0, 7}) and row.involves(0) and not row.involves(3)


def test_diplomacy_summary_seven_values_also_parse(tmp_path: Path):
    p = tmp_path / "DiplomacySummary.csv"
    p.write_text(DIPLO_HEADER + "10, 4, 1, Denounce, Denounced publicly, 12.5, VISIBLE\n")
    [row] = read_diplomacy_summary(p)
    assert row.extra == ("12.5", "VISIBLE")


def test_diplomacy_summary_five_values_leave_extra_empty(tmp_path: Path):
    p = tmp_path / "DiplomacySummary.csv"
    p.write_text(DIPLO_HEADER + "10, 4, 1, Denounce, Denounced publicly\n")
    assert read_diplomacy_summary(p)[0].extra == ()


def test_diplomacy_summary_needs_at_least_the_five_named_cells(tmp_path: Path):
    p = tmp_path / "DiplomacySummary.csv"
    p.write_text(DIPLO_HEADER + "10, 4, 1, Denounce\n")
    with pytest.raises(LogFormatError, match="at least 5 columns"):
        read_diplomacy_summary(p)
