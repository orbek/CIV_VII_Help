import asyncio
from pathlib import Path

from civ7_advisor.store import Store


def test_rebuild_loads_fixture_and_ranks_insights(fixture_dir: Path):
    store = Store(fixture_dir)
    assert store.state is None and store.insights == []
    state = store.rebuild()
    assert state.latest_turn == 82 and store.state is state
    assert store.insights[0].id == "threat.at_war.4"


def test_publish_reaches_subscribers_and_unsubscribe_stops_it():
    async def scenario():
        store = Store(Path("."))
        q = store.subscribe()
        store.publish({"type": "state_changed", "turn": 5})
        assert await asyncio.wait_for(q.get(), 1) == {"type": "state_changed", "turn": 5}
        store.unsubscribe(q)
        store.publish({"type": "state_changed", "turn": 6})
        assert q.empty()

    asyncio.run(scenario())


def test_store_archives_under_game_and_session_and_starts_a_new_session_after_a_wipe(tmp_path, fixture_dir):
    import shutil
    from civ7_advisor.ingest.load import LOG_FILES
    logs = tmp_path / "logs"
    shutil.copytree(fixture_dir, logs)
    root = tmp_path / "archive"
    store = Store(logs, archive_root=root)
    store.rebuild()
    games = list(root.iterdir())
    assert len(games) == 1
    sessions = sorted(games[0].iterdir())
    assert len(sessions) == 1 and (sessions[0] / "Player_Stats.csv").is_file()
    for name in LOG_FILES:                       # the game relaunches: every log vanishes
        (logs / name).unlink(missing_ok=True)
    store.rebuild()
    shutil.copytree(fixture_dir, logs, dirs_exist_ok=True)  # ... and a save is loaded again
    store.rebuild()
    assert len(sorted(games[0].iterdir())) == 2


def test_store_archives_under_the_seeds_of_the_loaded_save(tmp_path, fixture_dir):
    import shutil
    logs = tmp_path / "logs"
    shutil.copytree(fixture_dir, logs)
    (logs / "GameCore.log").write_text(
        "[2026-09-07 17:13:59]\tRandom Seeds: Game 1571231116, Map 1516997327\n"
    )
    root = tmp_path / "archive"
    Store(logs, archive_root=root).rebuild()
    game = root / "seeds-1571231116-1516997327"
    assert [p.name for p in root.iterdir()] == [game.name]
    sessions = list(game.iterdir())
    assert len(sessions) == 1
    assert (sessions[0] / "GameCore.log").is_file()  # every .csv/.log is mirrored, not only the wired ones


def test_store_without_archive_root_writes_nothing(tmp_path, fixture_dir):
    root = tmp_path / "archive"
    Store(fixture_dir).rebuild()
    assert not root.exists()


def test_archiver_failure_does_not_break_rebuild(tmp_path, fixture_dir, monkeypatch):
    import civ7_advisor.store as store_mod
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(store_mod, "archive_logs", boom)
    state = Store(fixture_dir, archive_root=tmp_path / "archive").rebuild()
    assert state.latest_turn == 82
