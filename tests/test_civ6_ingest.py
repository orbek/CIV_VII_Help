from civ_advisor.games.base import Capability
from civ_advisor.games.civ6 import CIV6
from civ_advisor.ingest.load import load_logs


def test_civ6_is_registered_by_importing_the_games_package():
    import civ_advisor.games  # noqa: F401
    from civ_advisor.games.registry import get_profile, profile_ids

    assert "civ6" in profile_ids()
    assert get_profile("civ6") is CIV6


def test_civ6_declares_only_what_its_logs_can_support():
    """Civ VI's AI_Victories holds era strategies, not victory paths (spec
    §3.2), and it logs no amenities, maintenance or deals."""
    assert not CIV6.supports(Capability.VICTORY_PATHS)
    assert not CIV6.supports(Capability.HAPPINESS)
    assert not CIV6.supports(Capability.MAINTENANCE)
    assert not CIV6.supports(Capability.PEACE_DEALS)
    assert not CIV6.supports(Capability.COMBAT_ODDS)
    assert CIV6.supports(Capability.FAITH)
    assert CIV6.supports(Capability.CIVICS)


def test_civ6_does_not_declare_ai_victories():
    """Declaring it would populate GameState.strategies with era postures the
    victory advisor would report as victory pursuit."""
    assert "AI_Victories.csv" not in CIV6.log_files


def test_the_shared_readers_parse_the_civ6_capture(civ6_dir):
    raw = load_logs(civ6_dir, profile=CIV6)
    for name in ("DiplomacySummary.csv", "AI_Tactical.csv", "AI_Operation.csv",
                 "AI_MayhemTracker.csv", "AI_UnitEfficiency.csv", "GameCore.log"):
        status = raw.files[name]
        assert status.ok, f"{name}: {status.error}"
        assert status.rows > 0, f"{name} parsed but is empty"


def test_civ6_identities_come_from_the_shared_gamecore_reader(civ6_dir):
    """Verified against the capture: 6 majors, human at 0, Free Cities at 62."""
    raw = load_logs(civ6_dir, profile=CIV6)
    by_player = {r.player: r for r in raw.player_identities}

    assert by_player[0].civilization == "CIVILIZATION_ROME"
    assert by_player[0].leader == "LEADER_JULIUS_CAESAR"
    assert by_player[0].slot_status == "Human"
    assert by_player[1].civilization == "CIVILIZATION_SCOTLAND"
    majors = [r for r in raw.player_identities
              if r.level == "CIVILIZATION_LEVEL_FULL_CIV"]
    assert len(majors) == 6
    assert by_player[62].level == "CIVILIZATION_LEVEL_FREE_CITIES"


def test_player_by_civilization_ignores_a_stale_id_from_an_earlier_game(tmp_path):
    """GameCore.log never truncates in Civ VI. An earlier game's leftover id
    for a civilization must not survive alongside the current game's id for
    that same civilization -- that would make `_player_by_civilization` see
    it as fielded by two players and drop it, silently discarding a live
    rival from every Player_Stats row that names it."""
    from civ_advisor.games.civ6.readers import _player_by_civilization

    (tmp_path / "GameCore.log").write_text(
        "Player 0: Civilization - CIVILIZATION_AMERICA (1)  Leader - LEADER_BENJAMIN_FRANKLIN (2), "
        "- Level - CIVILIZATION_LEVEL_FULL_CIV, SlotStatus - Human\n"
        "Player 3: Civilization - CIVILIZATION_PERSIA (3)  Leader - LEADER_CYRUS (4), "
        "- Level - CIVILIZATION_LEVEL_FULL_CIV, SlotStatus - AI\n"
        "Player 0: Civilization - CIVILIZATION_AMERICA (1)  Leader - LEADER_BENJAMIN_FRANKLIN (2), "
        "- Level - CIVILIZATION_LEVEL_FULL_CIV, SlotStatus - Human\n"
        "Player 1: Civilization - CIVILIZATION_PERSIA (3)  Leader - LEADER_CYRUS (4), "
        "- Level - CIVILIZATION_LEVEL_FULL_CIV, SlotStatus - AI\n"
    )
    players = _player_by_civilization(tmp_path)
    assert players == {"CIVILIZATION_AMERICA": 0, "CIVILIZATION_PERSIA": 1}


def test_player_stats_reads_both_faith_columns_by_position(civ6_dir):
    """`Faith` is the header name at index 13 (balance) AND index 17 (yield).
    A name-keyed reader silently keeps one and drops the other."""
    from civ_advisor.games.civ6.readers import read_player_stats_civ6

    rows = read_player_stats_civ6(civ6_dir, civ6_dir / "Player_Stats.csv")
    rome = [r for r in rows if r.turn == 53 and r.player == 0]
    assert len(rome) == 1
    row = rome[0]
    assert row.cities == 2
    assert row.techs == 5
    assert row.civics == 5
    assert row.gold_balance == 98.0
    assert row.gold == 11.0
    assert row.production == 13.0
    assert row.food == 9.0
    assert row.faith_balance == 0.0
    assert row.faith == 0.0


def test_player_stats_leaves_civ7_only_fields_unavailable(civ6_dir):
    """Civ VI logs no towns, settlement cap, urban/rural split, amenities or
    diplomacy yield. These must be None, never 0."""
    from civ_advisor.games.civ6.readers import read_player_stats_civ6

    row = read_player_stats_civ6(civ6_dir, civ6_dir / "Player_Stats.csv")[0]
    assert row.towns is None
    assert row.settlement_cap is None
    assert row.urban_pop is None
    assert row.rural_pop is None
    assert row.happiness is None
    assert row.diplomacy is None


def test_unit_operations_skips_engine_diagnostics_but_not_real_rows(civ6_dir):
    """Civ VI interleaves 'Unit operation handler <hex>, is disabled' lines
    among the data -- at lines 2-4, before any data row.

    Counts are for the COMMITTED fixture, which Task 3 trimmed to 400 lines:
    396 data rows and 3 diagnostics, turns 1-7. (The untrimmed capture had
    6533 data rows through turn 52.) The trim deliberately kept the
    diagnostics, which are the whole point of this test."""
    from civ_advisor.games.civ6.readers import read_unit_operations_civ6

    rows = read_unit_operations_civ6(civ6_dir, civ6_dir / "UnitOperations.log")
    assert len(rows) == 396
    assert max(r.turn for r in rows) == 7


def test_unit_operations_still_raises_on_an_unrecognised_short_row(tmp_path):
    """Skipping every short row would turn a malformed log into quiet data
    loss. Only the known diagnostic shape may be skipped."""
    import pytest

    from civ_advisor.games.civ6.readers import read_unit_operations_civ6
    from civ_advisor.ingest.csvfile import LogFormatError

    path = tmp_path / "UnitOperations.log"
    path.write_text(
        "Game Turn, Mode, Player, Unit, Operation\n"
        "001, Adding, 0, UNIT_WARRIOR (1), UNITOPERATION_MOVE_TO (2)\n"
        "002, Adding\n"
    )
    with pytest.raises((LogFormatError, ValueError, IndexError)):
        read_unit_operations_civ6(tmp_path, path)


def test_unit_operations_reads_only_the_latest_game(tmp_path):
    """Civ VI never truncates UnitOperations.log; it accumulates across every
    game ever played. Without segmenting to the latest game, a second match
    would read the first match's rows as its own."""
    from civ_advisor.games.civ6.readers import read_unit_operations_civ6

    path = tmp_path / "UnitOperations.log"
    path.write_text(
        "Game Turn, Mode, Player, Unit, Operation\n"
        "001, Adding, 0, UNIT_WARRIOR (1), UNITOPERATION_MOVE_TO (2)\n"
        "Unit operation handler a92585ad, is disabled\n"
        "002, Adding, 0, UNIT_WARRIOR (1), UNITOPERATION_MOVE_TO (2)\n"
        "001, Adding, 0, UNIT_SETTLER (2), UNITOPERATION_FOUND_CITY (14)\n"
        "002, Adding, 0, UNIT_SETTLER (2), UNITOPERATION_MOVE_TO (19)\n"
        "003, Adding, 0, UNIT_SETTLER (2), UNITOPERATION_MOVE_TO (19)\n"
    )
    rows = read_unit_operations_civ6(tmp_path, path)
    assert len(rows) == 3
    assert [r.turn for r in rows] == [1, 2, 3]
    assert all(r.unit_id == 2 for r in rows)  # only the second game's unit, not the first's


def test_build_queue_attributes_cities_via_the_sibling_file(civ6_dir):
    """City_BuildQueue has no Player column; ownership comes from
    AI_CityBuild. Rome is the human's city in this capture."""
    from civ_advisor.games.civ6.readers import read_build_queue_civ6

    rows = read_build_queue_civ6(civ6_dir, civ6_dir / "City_BuildQueue.csv")
    rome = [r for r in rows if r.city == "LOC_CITY_NAME_ROME"]
    assert rome
    assert {r.player for r in rome} == {0}


def test_build_queue_carries_ownership_forward_rather_than_requiring_same_turn(civ6_dir):
    """AI_CityBuild logs only 25% of (turn, city) pairs. Requiring a same-turn
    match would discard three quarters of the queue."""
    from civ_advisor.games.civ6.readers import read_build_queue_civ6

    rows = read_build_queue_civ6(civ6_dir, civ6_dir / "City_BuildQueue.csv")
    attributed = [r for r in rows if r.player is not None and r.player >= 0]
    assert len(attributed) > len(rows) * 0.9


def test_build_queue_ignores_the_purchase_sentinel(civ6_dir):
    """AI_CityBuild's City column sometimes reads PURCHASE. Treating it as a
    city name would invent a city and attribute real queues to it."""
    from civ_advisor.games.civ6.readers import read_build_queue_civ6

    rows = read_build_queue_civ6(civ6_dir, civ6_dir / "City_BuildQueue.csv")
    assert all(r.city != "PURCHASE" for r in rows)


def test_a_queue_row_with_no_owner_anywhere_is_not_attributed_to_the_human(tmp_path):
    """Defaulting an unknown owner to player 0 would put a rival's production
    on the player's own Economy tab."""
    from civ_advisor.games.civ6.readers import read_build_queue_civ6

    (tmp_path / "City_BuildQueue.csv").write_text(
        "Game Turn, City, Production Added, Current Item, Current Production, "
        "Production Needed, Overflow\n"
        "5, LOC_CITY_NAME_NOWHERE, 6.0, UNIT_BUILDER, 6.0, 50, 0.0\n"
    )
    (tmp_path / "AI_CityBuild.csv").write_text(
        "Game Turn, Player, City, Food Adv., Prod. Adv., Construct, Order Source\n"
    )
    rows = read_build_queue_civ6(tmp_path, tmp_path / "City_BuildQueue.csv")
    assert len(rows) == 1
    assert rows[0].player is None


def test_ownership_from_an_earlier_game_does_not_leak_into_the_current_one(tmp_path):
    """AI_CityBuild.csv never truncates, same as every other Civ VI log. A city
    name reused by a different owner in an earlier game must not carry that
    earlier owner into the current game's queue -- especially not onto the
    human, who never owned it in the current game at all."""
    from civ_advisor.games.civ6.readers import read_build_queue_civ6

    (tmp_path / "City_BuildQueue.csv").write_text(
        "Game Turn, City, Production Added, Current Item, Current Production, "
        "Production Needed, Overflow\n"
        "100, LOC_CITY_NAME_SOMEWHERE_ELSE, 5.0, UNIT_WARRIOR, 5.0, 50, 0.0\n"
        "60, LOC_CITY_NAME_TESTCITY, 6.0, UNIT_BUILDER, 6.0, 50, 0.0\n"
    )
    (tmp_path / "AI_CityBuild.csv").write_text(
        "Game Turn, Player, City, Food Adv., Prod. Adv., Construct, Order Source\n"
        # An earlier game: the human (player 0) owned this city name, at turn 50.
        "50, 0, LOC_CITY_NAME_TESTCITY, 0, 0, ,\n"
        # The current game (turn column drops 50 -> 5, marking a new game): an
        # AI (player 3) owns the same city name this time, established turn 5.
        "5, 3, LOC_CITY_NAME_TESTCITY, 0, 0, ,\n"
    )
    rows = read_build_queue_civ6(tmp_path, tmp_path / "City_BuildQueue.csv")
    testcity = [r for r in rows if r.city == "LOC_CITY_NAME_TESTCITY"]
    assert len(testcity) == 1
    # Unsegmented, the earlier game's (50, player 0) entry would sort after and
    # overwrite the current game's (5, player 3) when queried at turn 60 --
    # filing this AI's build queue under the human.
    assert testcity[0].player == 3


def test_build_queue_raises_on_a_reordered_header(tmp_path):
    """Pinning only a column COUNT would let a patch that reorders columns (e.g.
    swapping Current Item and Current Production) silently misread one field as
    another. The header itself must be pinned, matching Civ VII's own strictness."""
    import pytest

    from civ_advisor.games.civ6.readers import read_build_queue_civ6
    from civ_advisor.ingest.csvfile import LogFormatError

    (tmp_path / "City_BuildQueue.csv").write_text(
        # "Current Item" and "Current Production" swapped from their real order.
        "Game Turn, City, Production Added, Current Production, Current Item, "
        "Production Needed, Overflow\n"
        "5, LOC_CITY_NAME_ROME, 6.0, UNIT_BUILDER, 6.0, 50, 0.0\n"
    )
    (tmp_path / "AI_CityBuild.csv").write_text(
        "Game Turn, Player, City, Food Adv., Prod. Adv., Construct, Order Source\n"
    )
    with pytest.raises(LogFormatError, match="header"):
        read_build_queue_civ6(tmp_path, tmp_path / "City_BuildQueue.csv")


def test_unit_operations_raises_on_a_reordered_header(tmp_path):
    """Same strictness for UnitOperations.log: a reordered header must not be
    silently accepted just because the column count still matches."""
    import pytest

    from civ_advisor.games.civ6.readers import read_unit_operations_civ6
    from civ_advisor.ingest.csvfile import LogFormatError

    (tmp_path / "UnitOperations.log").write_text(
        # "Mode" and "Player" swapped from their real order.
        "Game Turn, Player, Mode, Unit, Operation\n"
        "001, 0, Adding, UNIT_WARRIOR (1), UNITOPERATION_MOVE_TO (2)\n"
    )
    with pytest.raises(LogFormatError, match="header"):
        read_unit_operations_civ6(tmp_path, tmp_path / "UnitOperations.log")


def test_city_ownership_status_reader_reports_a_missing_file(tmp_path):
    """AI_CityBuild.csv is joined privately by the build-queue reader; this
    reader exists only so a broken or missing sibling gets its own visible
    FileStatus instead of silently emptying every queue row's attribution."""
    import pytest

    from civ_advisor.games.civ6.readers import read_city_ownership_status

    with pytest.raises(OSError):
        read_city_ownership_status(tmp_path, tmp_path / "AI_CityBuild.csv")


def test_city_ownership_status_reader_raises_on_a_reordered_header(tmp_path):
    import pytest

    from civ_advisor.games.civ6.readers import read_city_ownership_status
    from civ_advisor.ingest.csvfile import LogFormatError

    (tmp_path / "AI_CityBuild.csv").write_text(
        "Player, Game Turn, City, Food Adv., Prod. Adv., Construct, Order Source\n"
    )
    with pytest.raises(LogFormatError, match="header"):
        read_city_ownership_status(tmp_path, tmp_path / "AI_CityBuild.csv")
