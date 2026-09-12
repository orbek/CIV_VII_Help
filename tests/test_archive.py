import shutil
from pathlib import Path

import pytest

from civ_advisor.archive import MANIFEST, archive_logs, game_key
from civ_advisor.games.civ7 import CIV7

# One real GameCore.log line: the engine writes it when a save is loaded (tab after the bracket).
SEEDS_LINE = "[2026-09-07 17:13:59]\tRandom Seeds: Game 1571231116, Map 1516997327\n"


def _logs_dir(tmp_path: Path, name: str, gamecore: str | None) -> Path:
    d = tmp_path / name
    d.mkdir()
    if gamecore is not None:
        (d / "GameCore.log").write_text(gamecore)
    return d


def test_game_key_is_the_seeds_whatever_else_is_in_the_directory(tmp_path: Path):
    a = _logs_dir(tmp_path, "a", f"[2026-09-07 17:13:58]\tLoading\n{SEEDS_LINE}[..]\tGame started\n")
    b = _logs_dir(tmp_path, "b", SEEDS_LINE)
    (b / "Player_Stats.csv").write_text("Game Turn, Player\n40, 0\n")  # a relaunch resumes mid-game
    assert game_key(a) == game_key(b) == "seeds-1571231116-1516997327"


def test_game_key_differs_between_saves(tmp_path: Path):
    other = _logs_dir(tmp_path, "other", "[2026-09-07 18:00:00]\tRandom Seeds: Game 42, Map 7\n")
    assert game_key(other) == "seeds-42-7"
    assert game_key(other) != game_key(_logs_dir(tmp_path, "same", SEEDS_LINE))


def test_game_key_is_none_without_a_gamecore_log_or_without_the_line(tmp_path: Path):
    assert game_key(_logs_dir(tmp_path, "empty", None)) is None
    assert game_key(_logs_dir(tmp_path, "quiet", "[2026-09-07 17:00:00]\tLoading mods\n")) is None


def test_game_key_takes_the_last_seeds_line(tmp_path: Path):
    """Loading a second save in the same app session appends another Random Seeds line."""
    two = _logs_dir(tmp_path, "two", SEEDS_LINE + "[2026-09-07 19:00:00]\tRandom Seeds: Game 5, Map 6\n")
    assert game_key(two) == "seeds-5-6"


def test_archive_logs_copies_only_existing_listed_files_and_is_idempotent(tmp_path: Path, fixture_dir: Path):
    dest = tmp_path / "root" / "game" / "session"
    before = {n: (fixture_dir / n).stat() for n in CIV7.log_files if (fixture_dir / n).exists()}
    copied = archive_logs(fixture_dir, dest, CIV7.log_files)
    assert sorted(copied) == sorted(before)                      # the seven v1 files; missing ones skipped
    assert (dest / MANIFEST).is_file()
    assert archive_logs(fixture_dir, dest, CIV7.log_files) == []      # nothing changed -> nothing copied
    after = {n: (fixture_dir / n).stat() for n in before}
    assert all((before[n].st_mtime_ns, before[n].st_size) == (after[n].st_mtime_ns, after[n].st_size) for n in before)
    assert not set(p.name for p in fixture_dir.iterdir()) - set(before) - {"README.md"}  # source dir untouched


def test_archive_logs_recopies_a_changed_file(tmp_path: Path, fixture_dir: Path):
    src = tmp_path / "logs"
    shutil.copytree(fixture_dir, src)
    dest = tmp_path / "root" / "g" / "s"
    archive_logs(src, dest, CIV7.log_files)
    with (src / "Historian.csv").open("a") as fh:
        fh.write("UNIT_KILLED, AGE_ANTIQUITY, 83, 1, 1, 0, 4, Warrior, NO_CONSTRUCTIBLE\n")
    assert archive_logs(src, dest, CIV7.log_files) == ["Historian.csv"]
    assert (dest / "Historian.csv").read_text().endswith("NO_CONSTRUCTIBLE\n")


def test_archive_logs_refuses_a_destination_inside_the_logs_dir(tmp_path: Path):
    with pytest.raises(ValueError, match="inside"):
        archive_logs(tmp_path, tmp_path / "archive", CIV7.log_files)


@pytest.mark.parametrize("name", ["../outside.csv", "/tmp/outside.csv", "nested/file.csv"])
def test_archive_logs_refuses_names_that_can_escape_the_destination(tmp_path: Path, name: str):
    with pytest.raises(ValueError, match="file name"):
        archive_logs(tmp_path / "logs", tmp_path / "archive", [name])


@pytest.mark.parametrize("name", ["Player_Stats.csv", MANIFEST])
def test_archive_logs_refuses_destination_symlinks(tmp_path: Path, name: str):
    logs, dest = tmp_path / "logs", tmp_path / "archive"
    logs.mkdir()
    dest.mkdir()
    (logs / "Player_Stats.csv").write_text("source")
    outside = tmp_path / "outside"
    outside.write_text("keep")
    (dest / name).symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        archive_logs(logs, dest, ["Player_Stats.csv"])
    assert outside.read_text() == "keep"


def test_the_archive_root_is_namespaced_per_game(tmp_path):
    from civ_advisor.archive import archive_root_for

    assert archive_root_for("civ6", base=tmp_path) == tmp_path / "civ6" / "archive"
    assert archive_root_for("civ7", base=tmp_path) != archive_root_for("civ6", base=tmp_path)


def test_the_legacy_archive_root_is_still_named(tmp_path):
    """A user's existing archives are not orphaned by being renamed out of the code."""
    from civ_advisor.archive import LEGACY_ARCHIVE_ROOT

    assert LEGACY_ARCHIVE_ROOT.name == "archive"
    assert LEGACY_ARCHIVE_ROOT.parent.name == ".civ7-advisor"
