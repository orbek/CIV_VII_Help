from pathlib import Path

import pytest

from civ_advisor.games.base import GameProfile, LogReader
from civ_advisor.games.registry import UnknownGame, get_profile, profile_ids, register


def _reader(name: str) -> LogReader:
    return LogReader(filename=name, attr="stats", read=lambda path: [])


def test_log_files_lists_every_declared_reader_in_order():
    profile = GameProfile(
        id="testgame", display_name="Test Game", default_logs_dir=Path("/tmp/logs"),
        readers=(_reader("B.csv"), _reader("A.csv")),
        knowledge_package="civ_advisor.knowledge",
    )
    assert profile.log_files == ("B.csv", "A.csv")


def test_profiles_are_frozen():
    profile = GameProfile(
        id="testgame", display_name="Test Game", default_logs_dir=Path("/tmp/logs"),
        readers=(), knowledge_package="civ_advisor.knowledge",
    )
    with pytest.raises(AttributeError):
        profile.id = "other"


def test_register_then_get_round_trips():
    profile = GameProfile(
        id="registerme", display_name="Register Me", default_logs_dir=Path("/tmp/logs"),
        readers=(), knowledge_package="civ_advisor.knowledge",
    )
    register(profile)
    assert get_profile("registerme") is profile
    assert "registerme" in profile_ids()


def test_registering_the_same_id_twice_is_refused():
    """A second registration would silently shadow the first, and which one won
    would depend on import order."""
    profile = GameProfile(
        id="dupe", display_name="Dupe", default_logs_dir=Path("/tmp/logs"),
        readers=(), knowledge_package="civ_advisor.knowledge",
    )
    register(profile)
    with pytest.raises(ValueError, match="dupe"):
        register(profile)


def test_unknown_game_names_the_games_that_do_exist():
    """The error is what a user sees after a typo in --game, so it must list the
    valid ids rather than only repeating the bad one."""
    register(GameProfile(
        id="listed", display_name="Listed", default_logs_dir=Path("/tmp/logs"),
        readers=(), knowledge_package="civ_advisor.knowledge",
    ))
    with pytest.raises(UnknownGame) as exc:
        get_profile("civ5")
    assert "civ5" in str(exc.value)
    assert "listed" in str(exc.value)
