import asyncio
from pathlib import Path

from civ_advisor.games.civ6 import CIV6
from civ_advisor.games.civ7 import CIV7
from civ_advisor.store import DOMAINS, GAME_SWITCHED, SCHEMA_VERSION, Store


def test_rebuild_publishes_one_snapshot_with_state_insights_and_coverage(fixture_dir: Path):
    store = Store(fixture_dir, profile=CIV7)
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
        store = Store(Path("."), profile=CIV7)
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
    store = Store(logs, archive_root=root, profile=CIV7)
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
    Store(logs, archive_root=root, profile=CIV7).rebuild()
    game = root / "seeds-1571231116-1516997327"
    assert [p.name for p in root.iterdir()] == [game.name]
    sessions = list(game.iterdir())
    assert len(sessions) == 1
    assert (sessions[0] / "GameCore.log").is_file()  # every .csv/.log is mirrored, not only the wired ones


def test_store_without_archive_root_writes_nothing(tmp_path, fixture_dir):
    root = tmp_path / "archive"
    Store(fixture_dir, profile=CIV7).rebuild()
    assert not root.exists()


def test_archiver_failure_does_not_break_rebuild(tmp_path, fixture_dir, monkeypatch):
    import civ_advisor.store as store_mod
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(store_mod, "archive_logs", boom)
    state = Store(fixture_dir, archive_root=tmp_path / "archive", profile=CIV7).rebuild()
    assert state.latest_turn == 82


def test_archive_uses_the_rebuild_s_own_locked_snapshot_not_live_attributes(
    tmp_path, fixture_dir, civ6_dir, monkeypatch,
):
    """Whole-phase review, IMPORTANT 3: `_archive` runs after `rebuild()`'s own lock has
    released, so a switch_to landing in that exact gap must not be able to redirect an
    in-flight rebuild's own logs into the wrong archive root, game_key or session. This
    is a white-box test of `_archive`'s own contract: called with the values a rebuild
    captured under its lock, it must use exactly those and never re-read `self.logs_dir`
    /`self.archive_root`/`self._observed_key`, whatever they say by the time it runs."""
    import civ_advisor.store as store_mod

    store = Store(fixture_dir, archive_root=tmp_path / "arc7", profile=CIV7)
    raw = store_mod.load_logs(fixture_dir, CIV7)

    # Simulate the store having already moved on to civ6 by the time _archive runs --
    # exactly the state a concurrent switch_to would leave behind in the real race.
    store.logs_dir = civ6_dir
    store.archive_root = tmp_path / "arc6"
    store._observed_key = "civ6-seeds"

    calls = []
    monkeypatch.setattr(store_mod, "archive_logs",
                        lambda logs_dir, dest, names: calls.append((logs_dir, dest)))

    # The values a real rebuild() would have captured, under its own lock, BEFORE the
    # (simulated) switch -- its own record of "where and whose read this was."
    store._archive(raw, "session-1", fixture_dir, tmp_path / "arc7", "civ7-seeds")

    assert len(calls) == 1
    logs_dir, dest = calls[0]
    assert logs_dir == fixture_dir                        # not civ6_dir
    assert str(dest).startswith(str(tmp_path / "arc7"))    # not arc6
    assert "civ7-seeds" in str(dest)                       # not civ6-seeds


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

    captured = Store(logs, profile=CIV7).rebuild()
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
    store = Store(fixture_dir, profile=CIV7)
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
    store = Store(fixture_dir, profile=CIV7)          # no archive_root at all
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
    store = Store(logs, profile=CIV7)
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
    store = Store(logs, profile=CIV7)
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
    store = Store(logs, profile=CIV7)
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
    captured = Store(fixture_v2_dir, profile=CIV7).rebuild()
    identity = captured.domain("identity")
    assert identity.turn_scoped is False
    assert identity.status == "ok" and identity.rows > 0
    assert identity.latest_turn is None and identity.lag is None
    assert [c.name for c in captured.coverage if c.status != "ok"] == []


def test_two_stores_started_in_the_same_second_get_different_sessions(fixture_dir):
    """The session id is what the player's saved acknowledgements are filed under, so a
    collision could apply one game's record to another."""
    sessions = {Store(fixture_dir, profile=CIV7).rebuild().session for _ in range(5)}
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


def test_coverage_is_profile_aware_for_civ6(civ6_dir):
    """DOMAINS names reader ATTRIBUTES, not literal filenames, so a domain reads
    correctly no matter which game's filename backs it -- and a domain this game's
    profile cannot back at all reports not_applicable, not unavailable."""
    from civ_advisor.games.registry import get_profile

    snapshot = Store(civ6_dir, profile=get_profile("civ6")).rebuild()
    by_name = {c.name: c for c in snapshot.coverage}

    # Civ VI's build queue file is named differently from Civ VII's; the domain must
    # resolve to Civ VI's own file, not report itself unavailable for lacking Civ VII's.
    assert by_name["production"].status == "ok"
    assert by_name["production"].files == ("City_BuildQueue.csv",)

    # Civ VI declares a reader for only one of the three diplomacy-domain attributes
    # (diplomacy_summary); the other two (diplomacy intent, deals) have no reader at
    # all for this profile. The domain must not report "ok" on the strength of the
    # one attribute it happens to have.
    assert by_name["diplomacy"].status == "partial"

    # A domain with no backing reader at all for this profile (e.g. happiness: Civ VI
    # has no Player_Happiness.csv-equivalent) is not_applicable, not unavailable --
    # the concept does not exist for this game, it did not merely fail to read.
    assert by_name["happiness"].status == "not_applicable"
    assert by_name["strategy"].status == "not_applicable"


def test_a_domain_this_game_never_writes_is_not_reported_as_broken(civ6_dir):
    """Civ VI has no Player_Happiness.csv. Reporting it 'unavailable' would be an alarm
    about a file that does not exist by design -- exactly the distinction spec 9 draws.

    The brief for this task described the fix as `_coverage` omitting the domain from
    `captured.coverage` entirely. That was already superseded by an earlier fix round
    (07a5322, "Make coverage domains resolve through reader attributes, not filenames"):
    the domain is KEPT, tagged `not_applicable`, which is more honest than silence (a
    missing key is indistinguishable from a domain nobody thought to check) and is
    already covered by `test_coverage_is_profile_aware_for_civ6` above, whose passing
    assertions this task must not contradict. This test pins the actual, already-correct
    behavior: no such domain is ever reported as `unavailable` or `partial`."""
    captured = Store(civ6_dir, profile=CIV6).rebuild()
    for name in ("happiness", "treasury"):
        assert captured.domain(name).status == "not_applicable"
    for name in ("empire", "production"):
        assert captured.domain(name).status not in ("not_applicable", "unavailable")


def test_civ7_coverage_is_unchanged(fixture_dir):
    captured = Store(fixture_dir, profile=CIV7).rebuild()
    assert len(captured.coverage) == len(DOMAINS)


def test_unattributed_build_queue_rows_are_counted_not_hidden(civ6_dir):
    """Civ VI's City_BuildQueue.csv has no Player column; a row whose city has no owner
    in the join is attributed to nobody. The count must be visible, because a silently
    shorter queue reads as a quieter game."""
    captured = Store(civ6_dir, profile=CIV6).rebuild()
    production = captured.domain("production")
    assert production is not None and production.unattributed is not None
    assert production.unattributed >= 0


def test_civ7_reports_no_attribution_gap_concept(fixture_dir):
    """Civ VII's build-queue reader always produces a real player id (its own CSV
    carries the column directly), so the attribution gap is not "zero today" but a
    concept that does not exist for this game at all."""
    captured = Store(fixture_dir, profile=CIV7).rebuild()
    assert captured.domain("production").unattributed is None


def test_diplomacy_is_partial_for_an_unbacked_reason_not_a_missing_file(civ6_dir):
    """LIVE DEFECT (plan Task 8 appendix): Civ VI's diplomacy domain reads its one
    declared file (DiplomacySummary.csv) fine -- nothing is missing -- but has no reader
    at all for two of the domain's three attributes (diplomacy, deals). `missing` alone
    cannot say why this is 'partial'; `unbacked` must carry the true reason so the
    renderer never states "0 of 1 logs unreadable" when nothing is unreadable."""
    captured = Store(civ6_dir, profile=CIV6).rebuild()
    diplomacy = captured.domain("diplomacy")
    assert diplomacy.status == "partial"
    assert diplomacy.missing == ()
    assert diplomacy.unbacked == ("diplomacy", "deals")


def test_a_snapshot_records_which_game_produced_it(fixture_dir):
    captured = Store(fixture_dir, profile=CIV7).rebuild()
    assert captured.game_id == "civ7"


def test_switching_games_starts_a_new_sitting(fixture_dir, civ6_dir):
    """Spec 8.1: nothing computed under the previous game may survive the switch. The
    session id is what acknowledgements are filed under, so it must change."""
    store = Store(fixture_dir, profile=CIV7)
    first = store.rebuild()
    store.switch_to(CIV6, civ6_dir)
    second = store.rebuild()

    assert second.game_id == "civ6"
    assert second.epoch == first.epoch + 1
    assert second.epoch_reason == GAME_SWITCHED
    assert second.session != first.session
    assert second.revision > first.revision      # revision stays monotonic across a switch


def test_a_switch_does_not_inherit_the_previous_game_s_save_key(tmp_path, fixture_dir, civ6_dir):
    """Neither committed fixture's GameCore.log happens to record a "Random Seeds" line
    (the v1 fixture predates GameCore.log entirely; the civ6 capture's format doesn't
    include one either), so both copies get one written in here -- deterministically,
    rather than relying on what the fixtures happen to contain."""
    import shutil
    civ7_logs, civ6_logs = tmp_path / "civ7", tmp_path / "civ6"
    shutil.copytree(fixture_dir, civ7_logs)
    shutil.copytree(civ6_dir, civ6_logs)
    with open(civ7_logs / "GameCore.log", "a") as f:
        f.write("[2026-09-07 17:13:59]\tRandom Seeds: Game 111, Map 222\n")
    with open(civ6_logs / "GameCore.log", "a") as f:
        f.write("[2026-09-07 17:13:59]\tRandom Seeds: Game 333, Map 444\n")

    store = Store(civ7_logs, profile=CIV7)
    first = store.rebuild()
    store.switch_to(CIV6, civ6_logs)
    second = store.rebuild()
    assert first.game_key == "seeds-111-222"
    assert second.game_key == "seeds-333-444"
    assert first.game_key != second.game_key


def test_switching_back_does_not_resume_the_earlier_sitting(fixture_dir, civ6_dir):
    """Returning to Civ VII is a third sitting, not the first one continued: the logs
    were rewritten while we were not watching them."""
    store = Store(fixture_dir, profile=CIV7)
    first = store.rebuild()
    store.switch_to(CIV6, civ6_dir)
    store.rebuild()
    store.switch_to(CIV7, fixture_dir)
    third = store.rebuild()
    assert third.session != first.session and third.epoch == first.epoch + 2


def test_an_idle_store_has_no_snapshot_and_does_not_invent_one():
    """Auto mode with nothing recent on disk. 'I cannot tell which game is running' is a
    supported answer; a snapshot built from no logs would be an assertion."""
    store = Store(None, profile=None)
    assert store.active is False
    assert store.rebuild() is None
    assert store.snapshot is None


def test_activating_an_idle_store_is_the_first_load_not_a_switch(civ6_dir):
    store = Store(None, profile=None)
    store.switch_to(CIV6, civ6_dir)
    captured = store.rebuild()
    assert captured is not None
    assert captured.epoch == 1 and captured.epoch_reason == "first_load"


def test_a_switch_mid_rebuild_discards_the_stale_read_rather_than_publishing_it(
    fixture_dir, civ6_dir, monkeypatch,
):
    """load_logs runs outside the lock, so switch_to can land while a rebuild for the
    PREVIOUS game is still in flight. Publishing that read would attribute the old
    game's content to whatever the store just switched to. It must be discarded."""
    import civ_advisor.store as store_mod

    store = Store(fixture_dir, profile=CIV7)
    real_load_logs = store_mod.load_logs

    def switching_load_logs(logs_dir, profile):
        raw = real_load_logs(logs_dir, profile)
        store.switch_to(CIV6, civ6_dir)   # simulate a switch landing mid-read
        return raw

    monkeypatch.setattr(store_mod, "load_logs", switching_load_logs)
    stale = store.rebuild()               # this call's own read is for CIV7
    assert stale is None                  # discarded: the store had already moved to civ6
    assert store.snapshot is None         # nothing was published from the stale civ7 read

    monkeypatch.setattr(store_mod, "load_logs", real_load_logs)
    second = store.rebuild()              # a normal rebuild now correctly serves civ6
    assert second.game_id == "civ6"


def test_a_switch_back_to_the_same_game_still_discards_a_stale_in_flight_rebuild(
    fixture_dir, civ6_dir, monkeypatch,
):
    """Whole-phase review, IMPORTANT 7: profile objects are per-game singletons and an
    A->B->A sequence restores both `profile` and `logs_dir` to what they were when this
    rebuild started, even though an entire B sitting happened in between. Without a
    generation check that survives being restored to the same value, this stale read
    would pass the identity guard and publish an old capture at a newer revision,
    overwriting the real civ7 snapshot that already landed during B->A."""
    import civ_advisor.store as store_mod

    store = Store(fixture_dir, profile=CIV7)
    first = store.rebuild()                        # a real, current civ7 snapshot
    assert first is not None

    real_load_logs = store_mod.load_logs

    def switching_load_logs(logs_dir, profile):
        raw = real_load_logs(logs_dir, profile)
        store.switch_to(CIV6, civ6_dir)             # A -> B
        store_mod.load_logs = real_load_logs        # un-patch for this inner, real rebuild
        try:
            landed = store.rebuild()                # a real, fresh civ6 read lands
        finally:
            store_mod.load_logs = switching_load_logs
        assert landed is not None and landed.game_id == "civ6"
        store.switch_to(CIV7, fixture_dir)          # B -> A: same profile object, same dir
        return raw

    monkeypatch.setattr(store_mod, "load_logs", switching_load_logs)
    stale = store.rebuild()   # started under civ7 before A->B->A; profile/logs_dir alone
                              # would look unchanged by the time this reaches its lock
    assert stale is None
    # The genuine B->A switch left the store idle (switch_to always clears snapshot);
    # the stale rebuild above must not have resurrected an old capture over that.
    assert store.snapshot is None
