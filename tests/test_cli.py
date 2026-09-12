from pathlib import Path

from civ_advisor import cli


def test_default_logs_dir_is_the_macos_civ_vii_logs_folder():
    assert cli.DEFAULT_LOGS_DIR == Path.home() / "Library/Application Support/Civilization VII/Logs"


def test_missing_logs_dir_exits_2_with_a_helpful_message(tmp_path: Path, capsys):
    rc = cli.main(["--logs-dir", str(tmp_path / "nope"), "--game", "civ7"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not found" in err and "--logs-dir" in err and str(tmp_path / "nope") in err


def test_server_is_started_with_parsed_options(fixture_dir: Path, monkeypatch):
    calls = {}

    def fake_run(app, host, port, log_level):
        calls.update(app=app, host=host, port=port, log_level=log_level)

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    # --no-archive: this calls the real create_app, and must never touch the user's home.
    rc = cli.main(["--logs-dir", str(fixture_dir), "--game", "civ7", "--port", "9000",
                  "--host", "0.0.0.0", "--no-archive"])
    assert rc == 0
    assert calls["port"] == 9000 and calls["host"] == "0.0.0.0"
    assert calls["app"].title == "Civ VII Advisor"


def test_archive_flags_reach_create_app(fixture_dir, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, host, port, log_level: None)
    monkeypatch.setattr(cli, "create_app",
                        lambda logs_dir, poll, archive_root=None, commentary_worker=None,
                        player_store=None, profile=None:
                        seen.update(root=archive_root, worker=commentary_worker,
                                    store=player_store) or
                        object.__new__(type("A", (), {"title": "x"})))
    cli.main(["--logs-dir", str(fixture_dir), "--game", "civ7", "--no-archive"])
    assert seen["root"] is None
    cli.main(["--logs-dir", str(fixture_dir), "--game", "civ7",
             "--archive-dir", str(tmp_path / "arc")])
    assert seen["root"] == tmp_path / "arc"


def test_the_notes_file_is_configurable_and_can_be_turned_off(fixture_dir, monkeypatch, tmp_path):
    """Goals and acknowledgements are written to disk, so where must be the player's
    choice — and running without keeping any must be possible."""
    seen = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, host, port, log_level: None)
    monkeypatch.setattr(cli, "create_app", lambda *args, **kwargs:
                        seen.update(kwargs) or object.__new__(type("A", (), {"title": "x"})))
    notes = tmp_path / "notes.json"
    cli.main(["--logs-dir", str(fixture_dir), "--game", "civ7", "--no-archive",
             "--context-file", str(notes)])
    assert seen["player_store"].path == notes
    cli.main(["--logs-dir", str(fixture_dir), "--game", "civ7", "--no-archive",
             "--no-context-file"])
    throwaway = seen["player_store"].path
    assert throwaway != notes and throwaway != cli.DEFAULT_STORE_PATH
    assert not throwaway.exists()      # nothing is written until something is recorded


def test_llm_flags_reach_the_server(fixture_dir, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, host, port, log_level: None)
    monkeypatch.setattr(cli, "create_app", lambda *args, **kwargs: seen.update(kwargs) or object())
    cli.main(["--logs-dir", str(fixture_dir), "--game", "civ7", "--no-archive",
             "--llm-model", "llama3.3:70b", "--llm-timeout", "123"])
    assert seen["commentary_worker"].client.model == "llama3.3:70b"
    assert seen["commentary_worker"].client.timeout == 123
    cli.main(["--logs-dir", str(fixture_dir), "--game", "civ7", "--no-archive", "--no-llm"])
    assert seen["commentary_worker"] is None


def test_archive_list_prints_sessions(tmp_path, capsys, monkeypatch):
    """--archive-dir is now the BASE holding every game's own archive (spec §11), and
    the real LEGACY_ARCHIVE_ROOT must not leak this machine's own pre-2b archives into
    the test -- it is monkeypatched aside for the same reason the Step 1 test does."""
    from civ_advisor.archive import MANIFEST, archive_root_for

    monkeypatch.setattr(cli, "LEGACY_ARCHIVE_ROOT", tmp_path / "no-legacy-here")
    session = archive_root_for("civ7", base=tmp_path / "arc") / "abc123def456" / "20260907T171100"
    session.mkdir(parents=True)
    (session / MANIFEST).write_text('{"updated": "2026-09-07T17:11:00", "files": ["Player_Stats.csv"]}')
    assert cli.main(["archive", "list", "--archive-dir", str(tmp_path / "arc")]) == 0
    out = capsys.readouterr().out
    assert "abc123def456" in out and "20260907T171100" in out and "1 file" in out


def test_archive_list_with_no_archive_is_quiet(tmp_path, capsys, monkeypatch):
    """The real LEGACY_ARCHIVE_ROOT must not leak this machine's own pre-2b archives
    into what should be an empty result -- monkeypatched aside, same as the sibling test."""
    monkeypatch.setattr(cli, "LEGACY_ARCHIVE_ROOT", tmp_path / "no-legacy-here")
    assert cli.main(["archive", "list", "--archive-dir", str(tmp_path / "none")]) == 0
    assert "No archive" in capsys.readouterr().out


def test_game_flag_selects_the_profile_and_its_default_logs_dir(monkeypatch, capsys):
    """--game picks both the readers and where to look, so a user who names the
    game does not also have to know the path."""
    import civ_advisor.cli as cli

    seen = {}

    def fake_create_app(logs_dir, poll_interval, **kwargs):
        seen["logs_dir"] = logs_dir
        seen["profile"] = kwargs["profile"]
        return object()

    monkeypatch.setattr(cli, "create_app", fake_create_app)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: None)
    # The profile's real default_logs_dir only exists if the game is installed, and
    # the test is about which path is chosen, not whether it is present. main() makes
    # exactly one is_dir() call before create_app, and monkeypatch undoes this after.
    monkeypatch.setattr(Path, "is_dir", lambda self: True)

    assert cli.main(["--game", "civ7", "--no-llm", "--no-context-file"]) == 0
    assert seen["profile"].id == "civ7"
    assert seen["logs_dir"] == seen["profile"].default_logs_dir


def test_unknown_game_is_refused_with_the_known_ids(capsys):
    """A typo must not fall back to a default and silently advise on the wrong game."""
    import civ_advisor.cli as cli

    assert cli.main(["--game", "civ5"]) == 2
    assert "civ7" in capsys.readouterr().err


def test_logs_dir_without_game_is_refused(tmp_path, capsys):
    """A logs directory belongs to one game, and the advisor cannot tell which from the
    path. Guessing would run Civ VII's readers over a Civ VI directory: every file would
    report "file not found" and the player would get empty advice instead of an error."""
    rc = cli.main(["--logs-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "--logs-dir" in err and "--game" in err
    assert "civ6" in err and "civ7" in err       # name the choices, do not just refuse


def test_logs_dir_with_an_explicit_game_is_accepted(fixture_dir, monkeypatch):
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: None)
    assert cli.main(["--logs-dir", str(fixture_dir), "--game", "civ7", "--no-archive",
                     "--no-llm", "--no-context-file"]) == 0


def test_archive_list_shows_pre_2b_archives_under_a_label(tmp_path, capsys, monkeypatch):
    """An existing archive must stay visible from the tool that exists to see it."""
    import civ_advisor.cli as cli

    legacy = tmp_path / ".civ7-advisor" / "archive" / "seeds-1-2" / "20260101T000000-1-abc"
    legacy.mkdir(parents=True)
    (legacy / "archived.json").write_text('{"files": ["Player_Stats.csv"], "updated": "x"}')
    monkeypatch.setattr(cli, "LEGACY_ARCHIVE_ROOT", tmp_path / ".civ7-advisor" / "archive")

    assert cli.main(["archive", "list", "--archive-dir", str(tmp_path / ".civ-advisor")]) == 0
    out = capsys.readouterr().out
    assert "pre-2b" in out and "seeds-1-2" in out
