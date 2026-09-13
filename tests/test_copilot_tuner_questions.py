"""Live questions resolve to live readings, and their absence names the tuner's own cause."""
from civ_advisor.copilot.catalog import Unanswerable, ask
from civ_advisor.decisions.context import build_context
from civ_advisor.decisions.models import SourceKind
from civ_advisor.tuner.base import (
    BuildOption, CityAmenities, Maintenance, SettlementOptions, TunerReading, TunerSnapshot,
)

READING = TunerReading(turn=53, read_at="2026-09-13T10:40:00Z", state="GameCore_Tuner")
LIVE = TunerSnapshot(
    available=True,
    amenities=(CityAmenities(city="Rome", total=3, from_luxuries=1, from_civics=0,
                             from_entertainment=2, housing=9, food_surplus=1),),
    maintenance=Maintenance(total=1, buildings=0, districts=1, units=0, gold=152, gold_yield=8),
    build_options=(SettlementOptions(city="Rome", options=(BuildOption("BUILDING_GRANARY", 8),)),),
    readings=(("amenities", READING), ("maintenance", READING),
              ("build_options", TunerReading(turn=53, read_at="2026-09-13T10:40:01Z",
                                             state="InGame"))),
)


def test_amenities_resolve_to_a_live_reading_for_that_city(civ6_store):
    context = build_context(civ6_store.rebuild(), tuner=LIVE)
    got = ask(context, "settlement.amenities", {"city": "Rome"})
    (fact,) = got.facts
    assert fact.source_kind is SourceKind.LIVE_READING
    assert fact.value == 3 and fact.observed_turn == 53 and fact.reported_at


def test_a_city_the_reading_did_not_name_is_a_bad_parameter(civ6_store):
    context = build_context(civ6_store.rebuild(), tuner=LIVE)
    got = ask(context, "settlement.amenities", {"city": "Carthage"})
    assert got.absence.kind is Unanswerable.BAD_PARAMETER


def test_upkeep_resolves_to_the_live_net_gold(civ6_store):
    context = build_context(civ6_store.rebuild(), tuner=LIVE)
    got = ask(context, "empire.upkeep", {})
    assert any(f.value == 7 and f.source_kind is SourceKind.LIVE_READING for f in got.facts)


def test_build_options_resolve_per_option_with_turns(civ6_store):
    context = build_context(civ6_store.rebuild(), tuner=LIVE)
    got = ask(context, "settlement.build_options", {"city": "Rome"})
    assert [(f.subject_id, f.value, f.unit) for f in got.facts] == [("Rome", 8, "turns")]


def test_with_the_tuner_off_the_absence_carries_the_tuners_own_cause(civ6_store):
    context = build_context(civ6_store.rebuild())
    got = ask(context, "empire.upkeep", {})
    assert got.absence.kind is Unanswerable.TUNER_ABSENT
    assert got.absence.cause in {"not_enabled", "not_answering", "no_socket", "not_asked",
                                 "unreachable"}
    assert got.absence.detail


def test_civ7_has_no_socket_and_says_so(civ7_store):
    context = build_context(civ7_store.rebuild(), tuner=civ7_store.snapshot.tuner)
    got = ask(context, "empire.upkeep", {})
    assert got.absence.kind is Unanswerable.TUNER_ABSENT
    assert got.absence.cause == "no_socket"
    assert "EnableTuner" not in got.absence.detail
