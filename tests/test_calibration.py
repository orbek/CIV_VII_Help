import shutil

from scripts.calibrate_advisor import analyze, session_dirs


def test_calibration_reads_every_archive_shaped_session(tmp_path, fixture_dir):
    root = tmp_path / "archive"
    for game, session in (("game-a", "one"), ("game-b", "two")):
        shutil.copytree(fixture_dir, root / game / session)
    assert len(session_dirs(root)) == 2
    report = analyze(root)
    assert report["game_count"] == 2 and report["scanned_session_count"] == 2
    assert report["metrics"]["military_ratio"]["n"] > 0
    assert report["metrics"]["yield_ratio"]["direction"] == "below"
    assert report["metrics"]["war_intent"]["threshold"] == 100.0


def test_calibration_empty_archive_is_a_valid_report(tmp_path):
    report = analyze(tmp_path / "missing")
    assert report["game_count"] == 0 and report["scanned_session_count"] == 0
    assert all(metric["n"] == 0 for metric in report["metrics"].values())


def test_calibration_selects_one_most_advanced_session_per_game(tmp_path, fixture_dir):
    root = tmp_path / "archive"
    shutil.copytree(fixture_dir, root / "same-game" / "one")
    shutil.copytree(fixture_dir, root / "same-game" / "two")
    report = analyze(root)
    assert report["game_count"] == 1 and report["scanned_session_count"] == 2
    assert report["games"] == [{
        "game": "same-game", "session": "same-game/two", "complete_through_turn": 81,
    }]
    assert report["metrics"]["military_ratio"]["n"] == 6
