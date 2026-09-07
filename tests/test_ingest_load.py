import shutil
from pathlib import Path

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
