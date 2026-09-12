import os
import time
from pathlib import Path

from civ_advisor.games.base import GameProfile, LogReader, simple
from civ_advisor.games.detect import (
    ALL_STALE, AMBIGUOUS, DETECTED, NO_LOGS_DIR, detect, newest_declared_log,
)


def _profile(game_id: str, logs_dir: Path, *files: str) -> GameProfile:
    return GameProfile(
        id=game_id, display_name=game_id.upper(), default_logs_dir=logs_dir,
        readers=tuple(LogReader(f, "stats", simple(lambda p: [])) for f in files),
        knowledge_package="civ_advisor.knowledge.civ7",
    )


def _write(path: Path, age_s: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    when = time.time() - age_s
    os.utime(path, (when, when))


def test_the_freshest_declared_log_decides(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "Player_Stats.csv", 300)
    _write(b / "Player_Stats.csv", 10)
    found = detect([_profile("ga", a, "Player_Stats.csv"), _profile("gb", b, "Player_Stats.csv")])
    assert (found.game_id, found.reason) == ("gb", DETECTED)


def test_an_undeclared_file_cannot_make_a_game_look_live(tmp_path):
    """Both engines rewrite noise logs at launch. Only declared gameplay logs count, or
    starting Civ VI at the menu would drag the dashboard away from a live Civ VII game."""
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "Player_Stats.csv", 300)
    _write(b / "Player_Stats.csv", 3000)
    _write(b / "VFXSystem.log", 1)          # not declared by gb
    found = detect([_profile("ga", a, "Player_Stats.csv"), _profile("gb", b, "Player_Stats.csv")])
    assert found.game_id == "ga"


def test_a_game_whose_logs_directory_is_absent_is_not_a_candidate(tmp_path):
    a = tmp_path / "a"
    _write(a / "Player_Stats.csv", 5)
    found = detect([_profile("ga", a, "Player_Stats.csv"),
                    _profile("gb", tmp_path / "missing", "Player_Stats.csv")])
    assert found.game_id == "ga"
    absent = next(c for c in found.candidates if c.game_id == "gb")
    assert absent.present is False and absent.newest is None


def test_no_candidate_at_all_says_so_rather_than_naming_one(tmp_path):
    found = detect([_profile("ga", tmp_path / "x", "Player_Stats.csv")])
    assert found.game_id is None and found.reason == NO_LOGS_DIR


def test_nothing_recent_is_cannot_tell_not_least_stale(tmp_path):
    """The point of the window. Two games last played on different days are not a
    question about which is running now; naming one would attach the whole dashboard to
    a game nobody is playing."""
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "Player_Stats.csv", 86400)
    _write(b / "Player_Stats.csv", 7200)
    found = detect([_profile("ga", a, "Player_Stats.csv"), _profile("gb", b, "Player_Stats.csv")],
                   window=600)
    assert found.game_id is None and found.reason == ALL_STALE
    assert {c.game_id for c in found.candidates} == {"ga", "gb"}   # still reported, with ages


def test_an_exact_tie_is_cannot_tell(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "Player_Stats.csv", 5)
    _write(b / "Player_Stats.csv", 5)
    stamp = os.stat(a / "Player_Stats.csv").st_mtime
    os.utime(b / "Player_Stats.csv", (stamp, stamp))
    found = detect([_profile("ga", a, "Player_Stats.csv"), _profile("gb", b, "Player_Stats.csv")])
    assert found.game_id is None and found.reason == AMBIGUOUS


def test_an_overridden_logs_dir_is_the_one_stat_ed(tmp_path):
    """--logs-dir moves where a game's logs are. Detection must look there, or it would
    report a disagreement with the pin purely because it looked in the wrong place."""
    real, elsewhere = tmp_path / "real", tmp_path / "elsewhere"
    _write(real / "Player_Stats.csv", 9000)
    _write(elsewhere / "Player_Stats.csv", 2)
    found = detect([_profile("ga", real, "Player_Stats.csv")], logs_dirs={"ga": elsewhere})
    assert found.game_id == "ga"


def test_newest_declared_log_ignores_a_missing_file(tmp_path):
    _write(tmp_path / "Player_Stats.csv", 5)
    profile = _profile("ga", tmp_path, "Player_Stats.csv", "Never_Written.csv")
    assert newest_declared_log(tmp_path, profile) is not None


def test_detects_against_the_real_registered_profiles_and_fixtures(civ6_dir, fixture_v2_dir):
    """The synthetic tests above prove the algorithm; this proves it against the actual
    registered profiles' real `log_files` and real committed fixtures, not a stand-in
    profile the test built itself. A huge window sidesteps how old the fixture files
    happen to be on disk -- staleness is not what this test is checking."""
    from civ_advisor.games.civ6 import CIV6
    from civ_advisor.games.civ7 import CIV7

    huge = 10**9
    civ6_found = detect([CIV6], logs_dirs={"civ6": civ6_dir}, window=huge)
    assert (civ6_found.game_id, civ6_found.reason) == ("civ6", DETECTED)

    civ7_found = detect([CIV7], logs_dirs={"civ7": fixture_v2_dir}, window=huge)
    assert (civ7_found.game_id, civ7_found.reason) == ("civ7", DETECTED)
