from pathlib import Path

import pytest

import civ_advisor.games  # noqa: F401  (imported for its registration side effect)
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


def test_importing_the_games_package_registers_civ7():
    """Importing civ_advisor.games must be enough; nothing should have to import
    the civ7 subpackage by hand."""
    assert "civ7" in profile_ids()


def test_civ7_profile_declares_every_reader_the_advisor_had():
    from civ_advisor.games.civ7 import CIV7

    assert CIV7.id == "civ7"
    assert CIV7.display_name == "Civilization VII"
    assert CIV7.default_logs_dir.name == "Logs"
    assert len(CIV7.readers) == 21
    assert "Player_Stats.csv" in CIV7.log_files
    assert "GameCore.log" in CIV7.log_files


def test_civ7_declares_no_file_twice():
    """Two readers on one file would double-count its rows."""
    from civ_advisor.games.civ7 import CIV7

    assert len(set(CIV7.log_files)) == len(CIV7.log_files)


def test_every_civ7_reader_targets_a_real_rawlogs_field():
    """A typo in `attr` would silently drop a whole log: setattr would create a new
    attribute that nothing reads."""
    from dataclasses import fields

    from civ_advisor.games.civ7 import CIV7
    from civ_advisor.ingest.load import RawLogs

    known = {f.name for f in fields(RawLogs)}
    assert {r.attr for r in CIV7.readers} <= known


def test_a_profile_declares_what_it_supports():
    from civ_advisor.games.base import Capability, GameProfile

    profile = GameProfile(
        id="capgame", display_name="Cap Game", default_logs_dir=Path("/tmp/logs"),
        readers=(), knowledge_package="civ_advisor.knowledge",
        capabilities=frozenset({Capability.HAPPINESS}),
    )
    assert profile.supports(Capability.HAPPINESS)
    assert not profile.supports(Capability.VICTORY_PATHS)


def test_civ7_declares_only_what_its_logs_carry():
    """Civ VII's own Player_Stats.csv header has no Faith, no Civics, no
    Tourism, no Diplomatic Favor column: `Game Turn, Player, Cities, Towns,
    Settlement Cap, Settlements Over Cap, Urban Pop, Rural Pop, Techs, Land
    Units, Naval Units, TILES: Owned, Improved, BALANCE: Gold, YIELDS:
    Science, Culture, Gold, Production, Food, Happiness, Diplomacy, BY TYPE:
    Buildings`. Declaring `frozenset(Capability)` (every member) claimed four
    capabilities Civ VII's logs do not carry — the exact defect this phase
    exists to prevent, in Civ VII's own profile."""
    from civ_advisor.games.base import Capability
    from civ_advisor.games.civ7 import CIV7

    assert CIV7.capabilities == frozenset({
        Capability.VICTORY_PATHS,        # AI_Victories.csv: real victory-path pursuit for Civ VII
        Capability.HAPPINESS,            # Player_Happiness.csv
        Capability.MAINTENANCE,          # Player_Treasury.csv
        Capability.PEACE_DEALS,          # DiplomacyDeals.log
        Capability.COMBAT_ODDS,          # AI_Operation_Eval.csv has an Odds column
        Capability.SETTLEMENT_CAP,       # Player_Stats.csv: Settlement Cap, Settlements Over Cap
        Capability.URBAN_RURAL_SPLIT,    # Player_Stats.csv: Urban Pop, Rural Pop
        # NOT FAITH, CIVICS, TOURISM or DIPLOMATIC_FAVOR: no reader Civ VII
        # declares carries any of the four, in any file.
    })
