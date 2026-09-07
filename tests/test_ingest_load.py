import shutil
from pathlib import Path

from civ7_advisor.ingest.load import LOG_FILES, load_logs


def test_load_logs_fixture_all_ok(fixture_dir: Path):
    raw = load_logs(fixture_dir)
    assert set(raw.files) == set(LOG_FILES)
    assert all(fs.ok for fs in raw.files.values())
    assert raw.files["Player_Stats.csv"].rows == 2523
    assert raw.files["Player_Stats.csv"].latest_turn == 82
    assert raw.files["AI_Victories.csv"].latest_turn == 80
    assert len(raw.targets) == 47025
    assert all([raw.stats, raw.treasury, raw.happiness, raw.victories, raw.diplomacy, raw.targets, raw.historian])


def test_load_logs_isolates_a_broken_file(tmp_path: Path, fixture_dir: Path):
    for name in LOG_FILES:
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
    for name in LOG_FILES:
        shutil.copy(fixture_dir / name, tmp_path / name)
    (tmp_path / "Player_Treasury.csv").unlink()
    (tmp_path / "Player_Treasury.csv").mkdir()  # open() now raises IsADirectoryError
    raw = load_logs(tmp_path)
    treasury = raw.files["Player_Treasury.csv"]
    assert treasury.ok is False
    assert treasury.error and treasury.error != "file not found"
    assert raw.treasury == []
    assert all(raw.files[name].ok for name in LOG_FILES if name != "Player_Treasury.csv")
    assert len(raw.stats) == 2523
