import shutil
from pathlib import Path

import pytest

from civ7_advisor.ingest.load import LOG_FILES, load_logs

# The seven logs v1 shipped with; the v1 fixture has exactly these, so every newer log is
# legitimately "file not found" there.
V1_FILES = ["Player_Stats.csv", "Player_Treasury.csv", "Player_Happiness.csv", "AI_Victories.csv",
            "AI_DiplomaticActions.csv", "AI_Targets.csv", "Historian.csv"]


def test_load_logs_fixture_all_ok(fixture_dir: Path):
    raw = load_logs(fixture_dir)
    assert set(raw.files) == set(LOG_FILES)
    assert all(raw.files[name].ok for name in V1_FILES)
    assert set(V1_FILES) <= set(LOG_FILES)
    for name in set(LOG_FILES) - set(V1_FILES):
        assert raw.files[name].error == "file not found", name
    assert raw.files["Player_Stats.csv"].rows == 2523
    assert raw.files["Player_Stats.csv"].latest_turn == 82
    assert raw.files["AI_Victories.csv"].latest_turn == 80
    assert len(raw.targets) == 47025
    assert all([raw.stats, raw.treasury, raw.happiness, raw.victories, raw.diplomacy, raw.targets, raw.historian])


def test_load_logs_isolates_a_broken_file(tmp_path: Path, fixture_dir: Path):
    for name in V1_FILES:
        shutil.copy(fixture_dir / name, tmp_path / name)
    (tmp_path / "Player_Treasury.csv").write_text("Turn, Player, Broken\n1, 0, x\n")
    raw = load_logs(tmp_path)
    assert raw.files["Player_Treasury.csv"].ok is False
    assert "unexpected header" in raw.files["Player_Treasury.csv"].error
    assert raw.treasury == []
    assert raw.files["Player_Stats.csv"].ok is True
    assert len(raw.stats) == 2523


def test_load_logs_reports_missing_files(tmp_path: Path):
    raw = load_logs(tmp_path)
    assert all(fs.ok is False and fs.error == "file not found" for fs in raw.files.values())
    assert raw.stats == []


def test_load_logs_isolates_a_non_missing_os_error(tmp_path: Path, fixture_dir: Path):
    for name in V1_FILES:
        shutil.copy(fixture_dir / name, tmp_path / name)
    (tmp_path / "Player_Treasury.csv").unlink()
    (tmp_path / "Player_Treasury.csv").mkdir()  # open() now raises IsADirectoryError
    raw = load_logs(tmp_path)
    treasury = raw.files["Player_Treasury.csv"]
    assert treasury.ok is False
    assert treasury.error and treasury.error != "file not found"
    assert raw.treasury == []
    assert all(raw.files[name].ok for name in V1_FILES if name != "Player_Treasury.csv")
    assert len(raw.stats) == 2523


# (file name, RawLogs attribute, one valid data row under the file's real header)
NEW_LOG_SAMPLES = [
    ("CityBuildQueue.csv", "build_queue",
     "Game Turn, Player, City, Production Added, Current Item, Current Production, Production Needed, Overflow\n"
     "82, 0, LOC_CITY_NAME_MAURYA1, 15.0, BUILDING_BRICKYARD, 47.5, 55, 0.0\n"),
    ("CombatLog.csv", "combat",
     "Turn, SourceType, Location, AttPlayer, DefPlayer, CombatType, Attacker, Defender, AttStr, DefStr, "
     "AttStrMod, DefStrMod, AttDmg, DefDmg, Destroyed, HealAmount, attHealth, defHealth\n"
     "82,Unit vs Location,(63)(30),0,4,Melee,(14)UNIT_WARRIOR,(-1)LOC_DISTRICT_CITY_CENTER_NAME,"
     "20,30,-5,0,34,12,Attacker,0,(0)100,(8)100\n"),
    ("Game_Gossip.csv", "gossip",
     "Game Turn, Player, Civilization, Plot X, Plot Y, Type\n"
     "82, Alexander, Maurya, 63, 31, GOSSIP_UNIT_DESTROYED, Warrior\n"),
    ("DiplomacySummary.csv", "diplomacy_summary",
     "Game Turn, Initiator, Recipient, Action, Details, Mayhem, Visibility\n"
     "82, 0, 7, Diplomacy Action Enter Stage, "
     "Cultural Exchange Entering Stage DIPLOMACY_CULTURAL_EXCHANGE_COMPLETE,  426.0\n"),
    ("DiplomacyDeals.log", "deals",
     "Turn 79, Enacting Deal id 1 for player 4 and 7\n"
     ", Enacting Deal Item ID 2, from player 7, to player 4, type Peace, subType -751445167 (), value type , "
     "amount 0, duration 1\n"),
    ("GameCore.log", "player_identities",
     "Player 0: Civilization - CIVILIZATION_AMERICA (1)  Leader - LEADER_BENJAMIN_FRANKLIN (2), "
     "- Level - CIVILIZATION_LEVEL_FULL_CIV, SlotStatus - Human\n"),
]


@pytest.mark.parametrize("name,attr,content", NEW_LOG_SAMPLES)
def test_new_logs_are_wired_to_their_rawlogs_attribute(tmp_path: Path, fixture_dir: Path, name, attr, content):
    """READERS binds each file to a RawLogs attribute by a string; a typo there would leave the
    list empty while every other test stayed green. Feed one real row and check it lands."""
    for v1 in V1_FILES:
        shutil.copy(fixture_dir / v1, tmp_path / v1)
    (tmp_path / name).write_text(content)
    raw = load_logs(tmp_path)
    assert raw.files[name].ok is True and raw.files[name].rows == 1
    assert len(getattr(raw, attr)) == 1
