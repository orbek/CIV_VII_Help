"""Does a tuner reading actually reach the browser? Nothing else is proof.

Earlier phases proved a provider worked while nothing whatsoever reached the page --
every check called the provider directly. These tests go through the HTTP payload a
real dashboard request gets, not through `capture()` or a builder function's return
value.
"""
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civ_advisor.api.app import create_app
from civ_advisor.games.civ6 import CIV6
from civ_advisor.games.civ7 import CIV7
from civ_advisor.tuner.base import (
    BuildOption, CityAmenities, Maintenance, SettlementOptions, TUNER_OFF, TunerReading,
)
from civ_advisor.tuner.client import open_tuner

from tests.test_tuner_client import FakeGame, replies


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


# ---- a tuner reading actually cited by a real decision card ----------------------
#
# CIV6's own knowledge catalog is deliberately empty (no Civ VI guide has been
# reviewed yet -- see civ_advisor/knowledge/civ6/guides.json), so no decision family
# can ever name a specific building for it: `named_build` needs a reviewed catalog
# entry for the item, which does not exist there. Proving a card actually CITES a
# tuner-filled figure -- the path that turns a reading into advice, not just a
# reachable JSON blob -- therefore needs CIV VII's reviewed catalog and its
# behind-on-culture fixture, with the tuner swapped in as CIV VII's own fixture data
# doesn't otherwise carry one. The tuner's `build_options()` is independent of the
# active game's `tuner_backed` declaration (that only gates the capability report), so
# this is a legitimate way to exercise the citation path over HTTP.

CULTURE_COLUMN = 15   # "Culture" in Player_Stats.csv, zero-based
BEHIND_CITY = "LOC_CITY_NAME_TEST1"


def _behind_on_culture_dir(tmp_path: Path, fixture_dir: Path) -> Path:
    """A log directory whose human trails worst on *culture*, with one logged queue for
    BEHIND_CITY -- so the culture family owns a card naming a settlement, exactly like
    tests/test_api.py's `_behind_dir`."""
    d = tmp_path / "logs"
    shutil.copytree(fixture_dir, d)
    (d / "CityBuildQueue.csv").write_text(
        "Game Turn, Player, City, Production Added, Current Item, Current Production, "
        "Production Needed, Overflow\n"
        f"82, 0, {BEHIND_CITY}, 20.0, UNIT_WARRIOR, 25.0, 30, 0.0\n"
    )
    stats = d / "Player_Stats.csv"
    rows = stats.read_text().splitlines()
    index = next(i for i, r in enumerate(rows)
                 if [c.strip() for c in r.split(",")[:2]] == ["81", "0"])
    cells = rows[index].split(",")
    cells[CULTURE_COLUMN] = " 1.0"
    rows.insert(index + 1, ",".join(cells))
    stats.write_text("\n".join(rows) + "\n")
    return d


class _LiveMonumentTuner:
    """Answers for BEHIND_CITY only: it read that a Monument would take 4 turns there.
    Never asked to supply anything else, so it never leaks into a candidate this
    scenario is not testing."""

    available = True
    reason = None
    unavailable = None

    def reading(self):
        return TunerReading(turn=82, read_at="2026-09-13T09:00:00Z", state="GameCore_Tuner")

    def amenities(self):
        return ()

    def maintenance(self):
        return None

    def build_options(self):
        return (SettlementOptions(city=BEHIND_CITY,
                                  options=(BuildOption(item="BUILDING_MONUMENT", turns=4),)),)


@pytest.fixture
def client_tuner_cites_a_decision(tmp_path, fixture_dir):
    profile = CIV7.__class__(**{**CIV7.__dict__, "tuner": _LiveMonumentTuner})
    with TestClient(create_app(_behind_on_culture_dir(tmp_path, fixture_dir),
                               poll_interval=60, profile=profile, archiving=False)) as c:
        yield c


def _submit(client, session: str, epoch: int, label: str, value, unit=None):
    """Submit one report exactly as the Refine form would: read the current context
    revision, then post with it as `base_revision`."""
    revision = client.get("/api/context").json()["revision"]
    resp = client.post("/api/context", json={
        "id": f"report.{BEHIND_CITY}.{label}", "subject": BEHIND_CITY, "label": label,
        "value": value, "unit": unit, "observed_turn": 82, "session": session,
        "reported_at": "2026-09-13T09:05:00Z", "epoch": epoch, "base_revision": revision,
    })
    assert resp.status_code == 200, resp.text
    return resp


def _culture_card(body: dict) -> dict:
    return next(c for c in body["decisions"]["cards"]
               if c["id"].startswith("decision.culture."))


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
    # Beside the prose, the distinction itself: a consumer must not have to match on
    # wording to learn which absence this is.
    assert briefing["tuner"]["unavailable"] == "not_enabled"


def test_build_options_reach_the_refine_prefill(client_with_live_tuner):
    body = client_with_live_tuner.get("/api/briefing").json()
    assert "BUILDING_GRANARY" in str(body)
    options = body["tuner"]["build_options"][0]["options"]
    assert options[0]["item"] == "BUILDING_GRANARY"
    assert options[0]["turns"] == 4


def test_a_live_reading_is_cited_by_a_real_decision_card(client_tuner_cites_a_decision):
    """`tuner_to_dict`'s `source: "live_reading"` is a constant the tuner section emits
    unconditionally -- it holds even with the tuner off, so it proves nothing on its
    own. What matters is whether a `live_reading` fact shows up in the evidence the page
    actually renders for a card: `decisions.evidence`, reached by a card citing it.

    Here the player has confirmed BUILDING_MONUMENT is offered in a settlement that is
    genuinely behind on culture, but has typed no completion-turns figure at all: the
    only source for that figure is the tuner. The card must name the building anyway,
    citing the tuner's own fact -- not a blank, not a player figure that was never
    entered.
    """
    c = client_tuner_cites_a_decision
    session = c.get("/api/status").json()["session"]
    epoch = c.get("/api/status").json()["epoch"]
    _submit(c, session, epoch, "available_options", "BUILDING_MONUMENT")

    body = c.get("/api/briefing").json()
    card = _culture_card(body)
    assert card["preferred"]["id"].endswith("BUILDING_MONUMENT")

    tuner_fact_id = f"tuner.build_option.{BEHIND_CITY}.BUILDING_MONUMENT.82"
    assert tuner_fact_id in card["preferred"]["evidence_ids"]

    evidence = {f["id"]: f for f in body["decisions"]["evidence"]}
    fact = evidence[tuner_fact_id]     # non-defaulting: a missing citation fails loudly
    assert fact["kind"] == "live_reading"
    assert fact["value"] == 4
    assert fact["observed_turn"] == 82
    assert fact["reported_at"] == "2026-09-13T09:00:00Z"

    # No player ever typed this figure. Confirming it is the only source cited proves
    # the reverse of the leak this feature exists to prevent: it must never be labelled
    # as something the player reported.
    assert fact["kind"] != "player_report"


def test_the_prefill_only_becomes_the_players_word_when_they_say_so(
        client_tuner_cites_a_decision):
    """The single most important claim this feature makes: a pre-fill is a suggestion
    until a human acts, and the act -- posting it through the same endpoint the Refine
    form uses -- is what changes its source kind. Nothing short of that POST may.

    A `.get()` chain that defaults empty proves nothing here: it would pass whether the
    key is absent, present-but-empty, or the schema changed entirely. Every read below
    indexes the real key directly, so a missing or renamed field fails the test instead
    of silently reading as `[]`.
    """
    c = client_tuner_cites_a_decision
    session = c.get("/api/status").json()["session"]
    epoch = c.get("/api/status").json()["epoch"]
    _submit(c, session, epoch, "available_options", "BUILDING_MONUMENT")

    before = c.get("/api/briefing").json()
    # Non-defaulting: `["reports"]`, not `.get("reports", [])`. The player has confirmed
    # availability but never typed a completion-turns figure, so nothing about THIS
    # figure is in their own accepted context yet.
    before_reports = before["decisions"]["context"]["reports"]
    assert [r["label"] for r in before_reports] == ["available_options"]
    before_evidence = {f["id"]: f for f in before["decisions"]["evidence"]}
    assert all(f["kind"] != "player_report" for f in before_evidence.values())
    tuner_fact_id = f"tuner.build_option.{BEHIND_CITY}.BUILDING_MONUMENT.82"
    assert before_evidence[tuner_fact_id]["kind"] == "live_reading"

    # The pre-fill itself, exactly as the Refine form would show it and exactly as it
    # would submit it unedited: same item, same value, same unit.
    live_options = before["tuner"]["build_options"][0]
    assert live_options["city"] == BEHIND_CITY
    prefill = live_options["options"][0]
    assert prefill["item"] == "BUILDING_MONUMENT"
    assert prefill["turns"] == 4

    # The player presses Record without editing the pre-filled value.
    _submit(c, session, epoch, "preview.BUILDING_MONUMENT.completion_turns",
            prefill["turns"], "turns")

    after = c.get("/api/briefing").json()
    after_reports = after["decisions"]["context"]["reports"]
    posted = next(r for r in after_reports
                 if r["label"] == "preview.BUILDING_MONUMENT.completion_turns")
    assert posted["value"] == 4 and posted["subject"] == BEHIND_CITY

    card = _culture_card(after)
    report_fact_id = f"report.{BEHIND_CITY}.preview.BUILDING_MONUMENT.completion_turns"
    assert report_fact_id in card["preferred"]["evidence_ids"]
    # The player's own confirmation now stands in for the tuner's -- this decision no
    # longer needs to ask the tuner for this figure at all.
    assert tuner_fact_id not in card["preferred"]["evidence_ids"]

    evidence = {f["id"]: f for f in after["decisions"]["evidence"]}
    fact = evidence[report_fact_id]
    assert fact["kind"] == "player_report"
    assert fact["value"] == 4


def test_the_reading_carries_when_it_was_taken(client_with_live_tuner):
    body = client_with_live_tuner.get("/api/briefing").json()
    assert body["tuner"]["read_at"] == "2026-09-13T10:40:00Z"
    assert body["tuner"]["turn"] == 12


# ---- the turn a live figure is filed under -------------------------------------
#
# Driven end to end through a real socket, because the defect lived exactly where the
# other fakes do not reach: `Civ6Tuner._turn` defaulted to 0 and nothing ever set it,
# so every live figure in production was filed under turn 0 while every fake in this
# file handed back `turn=12` on the object and hid it. Here nobody sets a turn on
# anything -- the game's REPLY names it, the client parses it out, and the payload is
# checked for what it carries.


@pytest.fixture
def live_game_on_turn_59():
    game = FakeGame(replies(turn=59))
    try:
        yield game
    finally:
        game.close()


@pytest.fixture
def client_against_a_socket(civ6_dir, live_game_on_turn_59):
    profile = _profile_with_tuner(
        lambda: open_tuner(port=live_game_on_turn_59.port, timeout=3.0))
    with TestClient(create_app(civ6_dir, poll_interval=60, profile=profile,
                               archiving=False)) as c:
        yield c


def test_a_live_figure_is_filed_under_the_turn_the_game_named(client_against_a_socket):
    """Not turn 0, and not the logs' last complete turn: the turn the running game
    itself answered with when it was asked for these very figures."""
    body = client_against_a_socket.get("/api/briefing").json()
    tuner = body["tuner"]
    assert tuner["available"] is True
    assert tuner["turn"] == 59
    assert tuner["turn"] != 0
    assert tuner["maintenance_read"]["turn"] == 59
    assert tuner["maintenance"]["net_gold"] == 7


def test_the_live_turn_is_not_borrowed_from_the_logs(client_against_a_socket):
    """The socket reads the live game; the logs are complete only through the last
    FINISHED turn. They disagree exactly when the player is mid-turn, and the reading
    must carry its own answer rather than being quietly reconciled to the snapshot's."""
    body = client_against_a_socket.get("/api/briefing").json()
    logged_turn = body["status"]["analysis_turn"]
    assert body["tuner"]["turn"] == 59
    assert body["tuner"]["turn"] != logged_turn
