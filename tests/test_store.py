import asyncio
from pathlib import Path

from civ_advisor.store import SCHEMA_VERSION, Store


def test_rebuild_publishes_one_snapshot_with_state_insights_and_coverage(fixture_dir: Path):
    store = Store(fixture_dir)
    assert store.state is None and store.insights == []
    captured = store.rebuild()
    assert captured.latest_turn == 82 and captured.analysis_turn == 81
    assert captured.in_progress is True
    assert store.snapshot is captured and store.state is captured.state
    assert store.insights[0].id == "threat.at_war.4"
    assert captured.insights[0].id == "threat.at_war.4"
    assert captured.schema_version == SCHEMA_VERSION and captured.revision == 1
    assert captured.epoch == 1 and captured.epoch_reason == "first_load"
    # The v1 fixture has no v2 AI logs at all, so tactical intelligence is unavailable
    # while the empire data it does have covers the analysis turn.
    assert captured.domain("empire").status == "ok"
    assert captured.domain("tactical").status == "unavailable"
    assert captured.domain("tactical").required is False


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
    from civ_advisor.games.civ7 import CIV7
    logs = tmp_path / "logs"
    shutil.copytree(fixture_dir, logs)
    root = tmp_path / "archive"
    store = Store(logs, archive_root=root)
    store.rebuild()
    games = list(root.iterdir())
    assert len(games) == 1
    sessions = sorted(games[0].iterdir())
    assert len(sessions) == 1 and (sessions[0] / "Player_Stats.csv").is_file()
    for name in CIV7.log_files:                       # the game relaunches: every log vanishes
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
    import civ_advisor.store as store_mod
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(store_mod, "archive_logs", boom)
    state = Store(fixture_dir, archive_root=tmp_path / "archive").rebuild()
    assert state.latest_turn == 82


def _copy_logs(tmp_path: Path, fixture_dir: Path, name: str = "logs") -> Path:
    import shutil
    logs = tmp_path / name
    shutil.copytree(fixture_dir, logs)
    return logs


def test_coverage_tells_empty_stale_and_unreadable_apart(tmp_path, fixture_dir):
    """A player has to be able to tell "the game wrote nothing" from "we cannot read it"
    from "these rows stop several turns back". Reporting all three as one warning is what
    makes an optional missing log look like a broken advisor."""
    logs = _copy_logs(tmp_path, fixture_dir)
    (logs / "CityBuildQueue.csv").write_text(          # readable, header only
        "Game Turn, Player, City, Production Added, Current Item, Current Production, "
        "Production Needed, Overflow\n"
    )
    (logs / "Game_Gossip.csv").write_text(             # readable, but stops well short
        "Game Turn, Player, Civilization, Plot X, Plot Y, Type\n"
        "40, Alexander, Maurya, 63, 31, GOSSIP_UNIT_DESTROYED, Warrior\n"
    )
    (logs / "Player_Treasury.csv").write_text("Turn, Player, Broken\n1, 0, x\n")  # malformed

    captured = Store(logs).rebuild()
    by_name = {c.name: c for c in captured.coverage}
    assert by_name["empire"].status == "ok" and by_name["empire"].required is True
    assert by_name["production"].status == "empty" and by_name["production"].rows == 0
    gossip = by_name["gossip"]
    assert gossip.status == "stale" and gossip.latest_turn == 40
    assert gossip.lag == captured.analysis_turn - 40
    treasury = by_name["treasury"]
    assert treasury.status == "unavailable" and treasury.errors and "header" in treasury.errors[0]
    # The v1 fixture never had the v2 AI logs; that disables tactical rather than failing.
    assert by_name["tactical"].status == "unavailable" and by_name["tactical"].required is False
    # A domain built from several files reports partial rather than pretending it is whole.
    assert by_name["diplomacy"].status == "partial"
    assert set(by_name["diplomacy"].missing) < set(by_name["diplomacy"].files)


def test_revision_is_monotonic_and_each_snapshot_is_internally_coherent(fixture_dir):
    """Interleave reads and rebuilds: every read must see one revision whose insights and
    state came from the same rebuild, and revisions must only ever go up."""
    store = Store(fixture_dir)
    seen = []
    for _ in range(4):
        store.rebuild()
        captured = store.snapshot
        seen.append(captured.revision)
        assert captured.state is store.state
        assert all(i.turn == captured.analysis_turn for i in captured.insights
                   if i.turn is not None)
    assert seen == [1, 2, 3, 4]


def test_session_identity_exists_without_archiving_and_survives_a_plain_rebuild(fixture_dir):
    store = Store(fixture_dir)          # no archive_root at all
    first = store.rebuild()
    second = store.rebuild()
    assert first.session and first.session == second.session
    assert first.epoch == second.epoch == 1
    assert second.revision > first.revision


def test_a_log_wipe_and_reload_start_a_new_epoch(tmp_path, fixture_dir):
    """Civ VII empties Logs/ on launch. Whatever appears afterwards is a different
    sitting, so acknowledgements must not silently carry across it."""
    import shutil
    from civ_advisor.games.civ7 import CIV7
    logs = _copy_logs(tmp_path, fixture_dir)
    store = Store(logs)
    first = store.rebuild()
    for name in CIV7.log_files:
        (logs / name).unlink(missing_ok=True)
    wiped = store.rebuild()
    assert wiped.epoch == first.epoch     # an empty read alone is not yet a new game
    shutil.copytree(fixture_dir, logs, dirs_exist_ok=True)
    reloaded = store.rebuild()
    assert reloaded.epoch == first.epoch + 1
    assert reloaded.session != first.session
    assert reloaded.epoch_reason == "logs_wiped"


def test_a_turn_that_moves_backwards_starts_a_new_epoch(tmp_path, fixture_dir):
    """A reload we never caught mid-wipe: the same seeds can be branched, so identical
    seeds are not evidence of the same line of play. Ambiguity resolves to a new epoch."""
    logs = _copy_logs(tmp_path, fixture_dir)
    store = Store(logs)
    first = store.rebuild()
    header, *rows = (logs / "Player_Stats.csv").read_text().splitlines()
    kept = [r for r in rows if r.split(",")[0].strip().isdigit()
            and int(r.split(",")[0]) <= first.latest_turn - 20]
    (logs / "Player_Stats.csv").write_text("\n".join([header, *kept]) + "\n")
    rewound = store.rebuild()
    assert rewound.latest_turn < first.latest_turn
    assert rewound.epoch == first.epoch + 1 and rewound.epoch_reason == "turn_went_backwards"


def test_loading_a_different_save_starts_a_new_epoch(tmp_path, fixture_dir):
    logs = _copy_logs(tmp_path, fixture_dir)
    (logs / "GameCore.log").write_text(
        "[2026-09-07 17:13:59]\tRandom Seeds: Game 111, Map 222\n")
    store = Store(logs)
    first = store.rebuild()
    assert first.game_key == "seeds-111-222"
    (logs / "GameCore.log").write_text(
        "[2026-09-07 18:00:00]\tRandom Seeds: Game 333, Map 444\n")
    switched = store.rebuild()
    assert switched.epoch == first.epoch + 1
    assert switched.epoch_reason == "different_save" and switched.game_key == "seeds-333-444"


def test_a_log_written_once_per_save_is_not_reported_as_stale(fixture_v2_dir):
    """GameCore.log records identity when the save loads and never again. Grading it
    against the turn counter would report a 99-turn lag on a perfectly current file —
    exactly the kind of technical noise that makes real coverage warnings unreadable."""
    captured = Store(fixture_v2_dir).rebuild()
    identity = captured.domain("identity")
    assert identity.turn_scoped is False
    assert identity.status == "ok" and identity.rows > 0
    assert identity.latest_turn is None and identity.lag is None
    assert [c.name for c in captured.coverage if c.status != "ok"] == []


def test_two_stores_started_in_the_same_second_get_different_sessions(fixture_dir):
    """The session id is what the player's saved acknowledgements are filed under, so a
    collision could apply one game's record to another."""
    sessions = {Store(fixture_dir).rebuild().session for _ in range(5)}
    assert len(sessions) == 5


def test_store_watches_and_reads_only_the_profile_s_files(fixture_dir, tmp_path):
    """The profile reaches the reader table, not just the constructor."""
    from civ_advisor.games.base import GameProfile, LogReader, simple
    from civ_advisor.ingest.readers import read_player_stats
    from civ_advisor.store import Store

    only_stats = GameProfile(
        id="store-statsonly", display_name="Stats Only", default_logs_dir=tmp_path,
        readers=(LogReader("Player_Stats.csv", "stats", simple(read_player_stats)),),
        knowledge_package="civ_advisor.knowledge",
    )
    snapshot = Store(fixture_dir, profile=only_stats).rebuild()

    assert list(snapshot.state.files) == ["Player_Stats.csv"]
