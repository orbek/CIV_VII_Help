from pathlib import Path

from civ7_advisor import cli


def test_default_logs_dir_is_the_macos_civ_vii_logs_folder():
    assert cli.DEFAULT_LOGS_DIR == Path.home() / "Library/Application Support/Civilization VII/Logs"


def test_missing_logs_dir_exits_2_with_a_helpful_message(tmp_path: Path, capsys):
    rc = cli.main(["--logs-dir", str(tmp_path / "nope")])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not found" in err and "--logs-dir" in err and str(tmp_path / "nope") in err


def test_server_is_started_with_parsed_options(fixture_dir: Path, monkeypatch):
    calls = {}

    def fake_run(app, host, port, log_level):
        calls.update(app=app, host=host, port=port, log_level=log_level)

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    # --no-archive: this calls the real create_app, and must never touch the user's home.
    rc = cli.main(["--logs-dir", str(fixture_dir), "--port", "9000", "--host", "0.0.0.0", "--no-archive"])
    assert rc == 0
    assert calls["port"] == 9000 and calls["host"] == "0.0.0.0"
    assert calls["app"].title == "Civ VII Advisor"


def test_archive_flags_reach_create_app(fixture_dir, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, host, port, log_level: None)
    monkeypatch.setattr(cli, "create_app", lambda logs_dir, poll, archive_root=None: seen.update(root=archive_root) or object.__new__(type("A", (), {"title": "x"})))
    cli.main(["--logs-dir", str(fixture_dir), "--no-archive"])
    assert seen["root"] is None
    cli.main(["--logs-dir", str(fixture_dir), "--archive-dir", str(tmp_path / "arc")])
    assert seen["root"] == tmp_path / "arc"


def test_archive_list_prints_sessions(tmp_path, capsys):
    from civ7_advisor.archive import MANIFEST
    session = tmp_path / "arc" / "abc123def456" / "20260907T171100"
    session.mkdir(parents=True)
    (session / MANIFEST).write_text('{"updated": "2026-09-07T17:11:00", "files": ["Player_Stats.csv"]}')
    assert cli.main(["archive", "list", "--archive-dir", str(tmp_path / "arc")]) == 0
    out = capsys.readouterr().out
    assert "abc123def456" in out and "20260907T171100" in out and "1 file" in out


def test_archive_list_with_no_archive_is_quiet(tmp_path, capsys):
    assert cli.main(["archive", "list", "--archive-dir", str(tmp_path / "none")]) == 0
    assert "No archive" in capsys.readouterr().out
