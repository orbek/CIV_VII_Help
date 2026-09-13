"""Does a tuner reading actually reach the browser? Nothing else is proof.

Earlier phases proved a provider worked while nothing whatsoever reached the page --
every check called the provider directly. These tests go through the HTTP payload a
real dashboard request gets, not through `capture()` or a builder function's return
value.
"""
import pytest
from fastapi.testclient import TestClient

from civ_advisor.api.app import create_app
from civ_advisor.games.civ6 import CIV6
from civ_advisor.tuner.base import (
    BuildOption, CityAmenities, Maintenance, SettlementOptions, TUNER_OFF, TunerReading,
)


class _LiveTuner:
    """A fake socket that always answers, so the payload path can be proven without a
    running game."""

    available = True
    reason = None
    unavailable = None

    def reading(self):
        return TunerReading(turn=12, read_at="2026-09-13T10:40:00Z", state="GameCore_Tuner")

    def amenities(self):
        return (CityAmenities(city="Rome", total=3, from_luxuries=1, from_civics=1,
                              from_entertainment=1, housing=5, food_surplus=1),)

    def maintenance(self):
        return Maintenance(total=5, buildings=2, districts=2, units=1, gold=0, gold_yield=10)

    def build_options(self):
        return (SettlementOptions(city="Rome",
                                  options=(BuildOption(item="BUILDING_GRANARY", turns=4),)),)


def _profile_with_tuner(factory):
    return CIV6.__class__(**{**CIV6.__dict__, "tuner": factory})


@pytest.fixture
def client_with_live_tuner(civ6_dir):
    profile = _profile_with_tuner(_LiveTuner)
    with TestClient(create_app(civ6_dir, poll_interval=60, profile=profile,
                               archiving=False)) as c:
        yield c


@pytest.fixture
def client_no_tuner(civ6_dir):
    profile = _profile_with_tuner(lambda: TUNER_OFF)
    with TestClient(create_app(civ6_dir, poll_interval=60, profile=profile,
                               archiving=False)) as c:
        yield c


def test_amenities_reach_the_payload_with_a_live_tuner(client_with_live_tuner):
    body = client_with_live_tuner.get("/api/briefing").json()
    # Not "the provider returned 3" -- the number must be in what the page gets.
    assert "3" in str(body)
    assert body["tuner"]["available"] is True
    assert body["tuner"]["amenities"][0]["total"] == 3
    assert body["tuner"]["amenities"][0]["city"] == "Rome"


def test_with_the_tuner_off_the_payload_carries_the_reason_not_a_zero(client_no_tuner):
    caps = client_no_tuner.get("/api/game").json()["active"]["capabilities"]
    assert caps["happiness"]["supported"] is False
    assert "EnableTuner" in caps["happiness"]["reason"]
    assert caps["happiness"].get("value") is None

    briefing = client_no_tuner.get("/api/briefing").json()
    assert briefing["tuner"]["available"] is False
    assert "EnableTuner" in briefing["tuner"]["reason"]
    assert briefing["tuner"]["amenities"] == []


def test_build_options_reach_the_refine_prefill(client_with_live_tuner):
    body = client_with_live_tuner.get("/api/briefing").json()
    assert "BUILDING_GRANARY" in str(body)
    options = body["tuner"]["build_options"][0]["options"]
    assert options[0]["item"] == "BUILDING_GRANARY"
    assert options[0]["turns"] == 4


def test_a_live_reading_is_labelled_as_such_in_the_evidence(client_with_live_tuner):
    body = client_with_live_tuner.get("/api/briefing").json()
    assert "live_reading" in str(body)
    assert body["tuner"]["source"] == "live_reading"


def test_the_prefill_is_not_recorded_as_a_player_report(client_with_live_tuner):
    """The player did not type it. Calling it their report would confuse sources."""
    body = client_with_live_tuner.get("/api/briefing").json()
    text = str(body)
    assert "live_reading" in text
    # The prefill must not show up among the player's own accepted reports.
    reports = body.get("decisions", {}).get("context", {}).get("reports", [])
    assert reports == []


def test_the_reading_carries_when_it_was_taken(client_with_live_tuner):
    body = client_with_live_tuner.get("/api/briefing").json()
    assert body["tuner"]["read_at"] == "2026-09-13T10:40:00Z"
    assert body["tuner"]["turn"] == 12
