"""The catalog of questions, checked against real replies."""
from pathlib import Path

import pytest

from civ_advisor.tuner.protocol import output_text, parse
from civ_advisor.tuner.queries import CATALOG, looks_unreachable

FIXTURES = Path(__file__).parent / "fixtures" / "tuner"


def lines(name: str) -> list[str]:
    msgs = parse((FIXTURES / name).read_bytes())
    return [t for t in (output_text(p) for _, p in msgs) if t and "---END---" not in t]


def test_every_entry_declares_where_it_runs_and_when_it_was_verified():
    for q in CATALOG.values():
        assert q.state in {"GameCore_Tuner", "InGame"}, q.id
        assert q.verified_on, q.id


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
