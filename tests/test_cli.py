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
    rc = cli.main(["--logs-dir", str(fixture_dir), "--port", "9000", "--host", "0.0.0.0"])
    assert rc == 0
    assert calls["port"] == 9000 and calls["host"] == "0.0.0.0"
    assert calls["app"].title == "Civ VII Advisor"
