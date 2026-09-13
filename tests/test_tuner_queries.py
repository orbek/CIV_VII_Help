"""The catalog of questions, checked against real replies."""
from pathlib import Path

import pytest

from civ_advisor.tuner.protocol import output_text, parse
from civ_advisor.tuner.queries import CATALOG, looks_unreachable, split_turn

FIXTURES = Path(__file__).parent / "fixtures" / "tuner"


def lines(name: str) -> list[str]:
    """The output lines of one captured reply.

    The .bin captures predate the turn line every query now prints first, and they
    are never edited: they are real bytes off a real socket and are the ground truth
    for the protocol. A test that needs a turn-bearing reply builds one with
    `dated()` below instead.
    """
    msgs = parse((FIXTURES / name).read_bytes())
    return [t for t in (output_text(p) for _, p in msgs) if t and "---END---" not in t]


def dated(name: str, turn: int = 59) -> list[str]:
    """A captured reply as the game sends it today: the turn line, then the figures."""
    return [f"turn\t{turn}", *lines(name)]


def test_every_entry_declares_where_it_runs_and_when_it_was_verified():
    for q in CATALOG.values():
        assert q.state in {"GameCore_Tuner", "InGame"}, q.id
        assert q.verified_on, q.id


def test_every_entry_asks_the_game_for_its_own_turn():
    """A figure must carry the turn that produced it, and the only honest source of
    that turn is the game. Not the logs: they are complete through the last FINISHED
    turn, and disagree with the live game exactly when the player is mid-turn."""
    for q in CATALOG.values():
        assert "Game.GetCurrentGameTurn()" in q.lua, q.id


def test_the_turn_is_read_out_of_a_real_reply_and_removed_before_parsing():
    turn, rest = split_turn(dated("query_maintenance.bin", 59))
    assert turn == 59
    assert rest == lines("query_maintenance.bin")
    m = CATALOG["maintenance"].parse(rest)
    assert m.net_gold == 7


def test_every_figure_still_parses_out_of_a_turn_bearing_reply():
    turn, rest = split_turn(dated("query_amenities.bin", 59))
    assert turn == 59
    assert {r.city for r in CATALOG["amenities"].parse(rest)} == {"Rome", "Puteoli"}

    turn, rest = split_turn(dated("query_buildoptions.bin", 60))
    assert turn == 60
    assert CATALOG["build_options"].parse(rest)


def test_a_reply_with_no_turn_line_reports_no_turn_rather_than_zero():
    """`None`, never 0: 0 is a real-looking turn number that no match is ever on."""
    turn, rest = split_turn(lines("query_maintenance.bin"))
    assert turn is None
    assert rest == lines("query_maintenance.bin")


def test_no_entry_contains_a_format_placeholder():
    """Query Lua is a constant. A placeholder is the beginning of injection."""
    for q in CATALOG.values():
        assert "{" not in q.lua and "%s" not in q.lua, q.id


def test_maintenance_parses_the_real_reply():
    m = CATALOG["maintenance"].parse(lines("query_maintenance.bin"))
    assert m.total == 1 and m.districts == 1 and m.buildings == 0 and m.units == 0
    assert m.gold == 152 and m.gold_yield == 8
    assert m.net_gold == 7


def test_amenities_parses_every_city_in_the_real_reply():
    rows = CATALOG["amenities"].parse(lines("query_amenities.bin"))
    by_city = {r.city: r for r in rows}
    assert by_city["Rome"].total == 3
    assert by_city["Rome"].from_entertainment == 2
    assert by_city["Puteoli"].total == 1
    assert by_city["Puteoli"].housing == 5


def test_build_options_parses_each_settlement_separately():
    rows = CATALOG["build_options"].parse(lines("query_buildoptions.bin"))
    by_city = {r.city: r for r in rows}
    assert by_city["Rome"].offers("BUILDING_GRANARY").turns == 8
    assert by_city["Rome"].offers("BUILDING_LIBRARY").turns == 11
    assert by_city["Puteoli"].offers("BUILDING_MONUMENT").turns == 60
    assert by_city["Rome"].offers("BUILDING_MONUMENT") is None


def test_build_options_runs_in_the_ui_state():
    """CanProduce and GetTurnsLeft are stubs in GameCore. This is not a preference."""
    assert CATALOG["build_options"].state == "InGame"


def test_a_not_implemented_reply_reads_as_unreachable():
    assert looks_unreachable(lines("query_not_implemented.bin")) is True


def test_a_missing_binding_reads_as_unreachable():
    assert looks_unreachable(lines("query_missing_binding.bin")) is True


def test_a_good_reply_does_not_read_as_unreachable():
    assert looks_unreachable(lines("query_maintenance.bin")) is False


def test_parsing_a_truncated_reply_raises_rather_than_inventing_a_figure():
    with pytest.raises(ValueError):
        CATALOG["maintenance"].parse(["total\t1"])


# `query_buildoptions_ids.bin` does not exist: Task 1's write spike, which was to capture
# it from a live game, is DEFERRED per docs/superpowers/sdd .../progress.md ("needs the
# user's running game and a save they are willing to damage, which they have not yet
# supplied"). Fabricating a fake ".bin" and calling it a capture would be exactly the
# defect tests/fixtures/tuner/README.md warns against ("these are captures, not
# hand-written"), so this parser is exercised against lines built in the test itself --
# the same shape the real reply will have, six tab-separated fields per row -- and
# labelled as synthetic rather than pretending to be real bytes off a socket.
_SYNTHETIC_BUILD_OPTION_ID_LINES = [
    "65536\tRome\tBUILDING_GRANARY\t123456789\tfalse\t8",
    "65536\tRome\tBUILDING_LIBRARY\t987654321\tfalse\t11",
    "65537\tPuteoli\tBUILDING_MONUMENT\t555555555\ttrue\t60",
]


def test_build_option_ids_carry_the_city_id_the_hash_and_placement():
    rows = CATALOG["build_options_ids"].parse(_SYNTHETIC_BUILD_OPTION_ID_LINES)
    by_city = {r.city: r for r in rows}
    first = next(iter(by_city.values()))
    assert isinstance(first.city_id, int)
    for o in first.options:
        assert isinstance(o.item_hash, int) and o.item.startswith("BUILDING_")
        assert o.requires_placement in (True, False)
        assert o.turns >= 0
    assert by_city["Rome"].city_id == 65536
    assert by_city["Puteoli"].options[0].requires_placement is True


def test_build_option_ids_runs_in_the_ui_state():
    assert CATALOG["build_options_ids"].state == "InGame"


def test_build_option_ids_lua_is_a_constant():
    assert "{" not in CATALOG["build_options_ids"].lua and "%s" not in CATALOG["build_options_ids"].lua
