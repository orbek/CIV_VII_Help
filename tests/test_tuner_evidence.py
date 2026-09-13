"""A tuner reading is labelled as what it is: a value we asked for."""
import pytest

from civ_advisor.advisors.base import Provenance
from civ_advisor.decisions.evidence import (
    EvidenceLedger, amenities_fact, build_option_fact, tuner_net_gold_fact,
)
from civ_advisor.decisions.models import EvidenceFact, SourceKind
from civ_advisor.tuner.base import BuildOption, CityAmenities, Maintenance, TunerReading


def fact(**kw) -> EvidenceFact:
    base = dict(id="x", label="Amenities in Rome", source_kind=SourceKind.LIVE_READING,
                provenance=Provenance.FAIR, observed_turn=59, value=3,
                reported_at="2026-09-13T10:40:00Z", subject_id="Rome")
    return EvidenceFact(**{**base, **kw})


def test_a_live_reading_is_a_distinct_source_kind():
    assert SourceKind.LIVE_READING.value == "live_reading"
    assert SourceKind.LIVE_READING is not SourceKind.LOG


def test_a_live_reading_must_record_when_it_was_asked_for():
    """This is what separates it from a log row the game wrote on its own."""
    with pytest.raises(ValueError, match="reported_at"):
        fact(reported_at=None)


def test_a_live_reading_must_name_the_turn_it_describes():
    with pytest.raises(ValueError, match="observed_turn"):
        fact(observed_turn=None)


def test_a_live_reading_is_fair():
    """Amenities and upkeep are on the player's own screen. Not an intercept."""
    assert fact().provenance is Provenance.FAIR


def test_a_live_reading_needs_no_source_file():
    """It came from a socket. Demanding a filename would invite a fake one."""
    assert fact(source_file=None).source_file is None


READING = TunerReading(turn=59, read_at="2026-09-13T10:40:00Z", state="GameCore_Tuner")


def test_amenities_fact_is_a_live_reading():
    ledger = EvidenceLedger()
    amenities = CityAmenities(city="Rome", total=6, from_luxuries=2, from_civics=1,
                               from_entertainment=1, housing=4, food_surplus=2)
    result = amenities_fact(ledger, READING, amenities)
    assert result.source_kind is SourceKind.LIVE_READING
    assert result.observed_turn == READING.turn
    assert result.reported_at == READING.read_at
    assert result.subject_id == "Rome"
    assert result.provenance is Provenance.FAIR


def test_tuner_net_gold_fact_is_a_live_reading():
    ledger = EvidenceLedger()
    maintenance = Maintenance(total=10, buildings=4, districts=3, units=3,
                               gold=0, gold_yield=25)
    result = tuner_net_gold_fact(ledger, READING, maintenance)
    assert result.source_kind is SourceKind.LIVE_READING
    assert result.observed_turn == READING.turn
    assert result.reported_at == READING.read_at
    assert result.provenance is Provenance.FAIR


def test_build_option_fact_is_a_live_reading():
    ledger = EvidenceLedger()
    option = BuildOption(item="Granary", turns=4)
    result = build_option_fact(ledger, READING, "Rome", option)
    assert result.source_kind is SourceKind.LIVE_READING
    assert result.observed_turn == READING.turn
    assert result.reported_at == READING.read_at
    assert result.subject_id == "Rome"
    assert result.provenance is Provenance.FAIR
