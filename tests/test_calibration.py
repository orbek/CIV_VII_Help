import shutil

from scripts.calibrate_advisor import analyze, session_dirs


def test_calibration_reads_every_archive_shaped_session(tmp_path, fixture_dir):
    root = tmp_path / "archive"
    for game, session in (("game-a", "one"), ("game-b", "two")):
        shutil.copytree(fixture_dir, root / game / session)
    assert len(session_dirs(root)) == 2
    report = analyze(root)
    assert report["session_count"] == 2
    assert report["metrics"]["military_ratio"]["n"] > 0
    assert report["metrics"]["yield_ratio"]["direction"] == "below"
    assert report["metrics"]["war_intent"]["threshold"] == 100.0


def test_calibration_empty_archive_is_a_valid_report(tmp_path):
    report = analyze(tmp_path / "missing")
    assert report["session_count"] == 0
    assert all(metric["n"] == 0 for metric in report["metrics"].values())
