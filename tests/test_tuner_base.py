"""What a tuner reading is allowed to be, and what absence looks like."""
import pytest

from civ_advisor.games.base import Capability
from civ_advisor.tuner.base import (
    BuildOption, CityAmenities, Maintenance, NullTuner, SettlementOptions,
    TUNER_OFF, TunerProvider, TunerReading, TunerUnavailable,
)


def test_a_reading_records_both_the_turn_and_the_moment_it_was_asked():
    """Unlike a log row, a reading is something we asked for at a time we chose."""
    r = TunerReading(turn=59, read_at="2026-09-13T10:40:00Z", state="GameCore_Tuner")
    assert r.turn == 59
    assert r.read_at == "2026-09-13T10:40:00Z"


def test_a_reading_must_name_the_vm_it_came_from():
    with pytest.raises(ValueError, match="state"):
        TunerReading(turn=59, read_at="2026-09-13T10:40:00Z", state="")


def test_amenities_sources_must_not_exceed_the_total_they_explain():
    with pytest.raises(ValueError, match="sources"):
        CityAmenities(city="Rome", total=1, from_luxuries=5, from_civics=0,
                      from_entertainment=0, housing=9, food_surplus=1)


def test_net_gold_is_yield_minus_maintenance():
    m = Maintenance(total=1, buildings=0, districts=1, units=0, gold=152, gold_yield=8)
    assert m.net_gold == 7


def test_maintenance_parts_must_sum_to_the_total():
    """A breakdown that does not add up is a parsing bug, not a game fact."""
    with pytest.raises(ValueError, match="breakdown"):
        Maintenance(total=9, buildings=0, districts=1, units=0, gold=152, gold_yield=8)


def test_a_build_option_carries_its_own_completion_estimate():
    o = BuildOption(item="BUILDING_GRANARY", turns=8)
    assert o.turns == 8


def test_a_build_option_rejects_a_negative_estimate():
    with pytest.raises(ValueError, match="turns"):
        BuildOption(item="BUILDING_GRANARY", turns=-1)


def test_a_settlement_offering_nothing_is_different_from_not_being_asked():
    """An empty offer list is a fact. `None` would be an absence of one."""
    s = SettlementOptions(city="Puteoli", options=())
    assert s.options == ()
    assert s.offers("BUILDING_GRANARY") is None


def test_null_tuner_answers_every_question_with_its_reason():
    null = NullTuner(TunerUnavailable.NOT_ENABLED, "EnableTuner is 0 in AppOptions.txt")
    assert null.available is False
    assert null.amenities() == ()
    assert null.maintenance() is None
    assert null.build_options() == ()
    assert "EnableTuner" in null.reason


def test_the_off_singleton_says_which_absence_it_is():
    assert TUNER_OFF.unavailable is TunerUnavailable.NOT_ENABLED


def test_the_three_absences_are_distinct():
    """Told apart on purpose: only one of them is fixable by the player."""
    assert len(set(TunerUnavailable)) == 3


def test_null_tuner_satisfies_the_protocol():
    assert isinstance(TUNER_OFF, TunerProvider)


def test_the_capabilities_a_tuner_can_back_are_named_here():
    from civ_advisor.tuner.base import TUNER_BACKED
    assert Capability.HAPPINESS in TUNER_BACKED
    assert Capability.MAINTENANCE in TUNER_BACKED
