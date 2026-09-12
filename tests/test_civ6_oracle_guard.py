import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from civ_advisor.advisors import intel, run_all
from civ_advisor.advisors.base import Provenance
from civ_advisor.api.app import create_app
from civ_advisor.api.serialize import ORACLE_THREAT_FIELDS, state_to_dict
from civ_advisor.games.civ6 import CIV6
from civ_advisor.games.base import Capability
from civ_advisor.ingest.load import load_logs
from civ_advisor.state.build import build_state

# Every string this phase's Oracle material would put on the wire.
#
# NOT "combat_desire" (the underscore form): that string is also the JSON key for
# `Capability.COMBAT_DESIRE`'s entry in the capability declaration
# (`game.active.capabilities.combat_desire`), which is legitimately present in every
# response regardless of the Oracle toggle -- a capability declaration says what the
# game CAN support, not the AI's private data itself, and is not Oracle-gated at all.
# Checked this directly: the fair-mode briefing payload contains that exact substring
# by design, so including it here would fail on correct behaviour, the same class of
# false positive the docstring warns about for intel.py's own rule-stating text.
ORACLE_MARKERS = (
    "combat desire", "standing negative modifier",
    "research goal", "scored these techs", "scored these civics",
    "scored these policy cards", "TECH_", "CIVIC_", "POLICY_",
    "Likes civs who respect the environment",
    "They dislike civilizations with a small standing army",
)

# Vocabulary that would mean the advisor had inferred a victory path from
# scored tech and civic preferences. See the phase-3 plan.
VICTORY_WORDS = ("victory", "pursuing", "going for", "winning by", "victory path")


@pytest.fixture(scope="module")
def civ6_state(civ6_dir):
    return build_state(load_logs(civ6_dir, profile=CIV6))


@pytest.fixture(scope="module")
def civ6_client(civ6_dir):
    with TestClient(create_app(civ6_dir, poll_interval=0.01, profile=CIV6)) as client:
        yield client


def test_every_insight_this_phase_adds_is_oracle(civ6_state):
    added = [i for i in run_all(civ6_state)
             if i.id.startswith(("threat.combat_desire.", "threat.grievances."))]

    assert added, "the capture should produce at least one of each"
    assert all(i.provenance is Provenance.ORACLE for i in added)


def test_fair_mode_insights_payload_carries_none_of_it(civ6_client):
    body = json.dumps(civ6_client.get("/api/insights?oracle=0").json())

    assert "threat.combat_desire" not in body
    assert "threat.grievances" not in body
    for marker in ORACLE_MARKERS:
        assert marker not in body, f"fair-mode insights payload leaked {marker!r}"


def test_fair_mode_intel_payload_carries_none_of_it(civ6_client):
    body = json.dumps(civ6_client.get("/api/intel?oracle=0").json())

    assert "ai_score" not in body
    for marker in ORACLE_MARKERS:
        assert marker not in body, f"fair-mode intel payload leaked {marker!r}"


def test_fair_mode_state_payload_drops_every_new_threat_field(civ6_state):
    """ORACLE_THREAT_FIELDS is hand-maintained, so assert the result rather than
    the list: a field added to RivalThreat and forgotten there would ship."""
    fair = state_to_dict(civ6_state, oracle=False)

    for entry in fair["threats"]:
        for field in ("combat_desire", "combat_desire_turn", "combat_desire_prior",
                      "combat_desire_is_highest", "grievances"):
            assert field not in entry, f"fair-mode state payload leaked {field}"
    assert json.dumps(fair).count("Likes civs who respect") == 0


def test_every_field_this_phase_added_to_rivalthreat_is_suppressed(civ6_state):
    """The complement of the test above, stated against the dataclass rather than a
    hand-written list: every RivalThreat field this phase added is Oracle by
    construction, so forgetting one in ORACLE_THREAT_FIELDS must fail here rather
    than ship."""
    from civ_advisor.advisors import threat

    added = {"combat_desire", "combat_desire_turn", "combat_desire_prior",
             "combat_desire_is_highest", "grievances"}
    assert added <= {f.name for f in dataclasses.fields(threat.RivalThreat)}
    assert added <= set(ORACLE_THREAT_FIELDS)


def test_every_rivalthreat_field_is_accounted_for_as_fair_or_oracle():
    """Stronger than the two tests above: rather than checking only the five fields
    THIS phase happened to add, this checks EVERY field `RivalThreat` has. A field
    added by any future task and left out of both the pre-phase-3 fair baseline and
    `ORACLE_THREAT_FIELDS` fails here -- a guard that only checks a remembered list
    decays the moment someone forgets to update the list alongside the dataclass."""
    from civ_advisor.advisors import threat

    # Every field RivalThreat had before this phase (all genuinely visible in fair
    # mode -- land units, fight/kill counts, peace -- none of it is AI-internal).
    fair_baseline = {
        "player", "name", "land_units", "human_land_units", "military_ratio",
        "kills", "losses", "latest_fight", "peace_since", "fights",
        "fights_won", "fights_lost", "latest_combat",
    }
    all_fields = {f.name for f in dataclasses.fields(threat.RivalThreat)}
    unaccounted = all_fields - fair_baseline - set(ORACLE_THREAT_FIELDS)
    assert unaccounted == set(), f"RivalThreat field(s) neither Fair nor Oracle: {unaccounted}"


def test_fair_mode_briefing_payload_carries_none_of_it(civ6_client):
    body = json.dumps(civ6_client.get("/api/briefing?oracle=0").json())

    for marker in ORACLE_MARKERS:
        assert marker not in body, f"fair-mode briefing payload leaked {marker!r}"


def test_oracle_mode_does_show_it(civ6_client):
    """The guard must be a filter, not a deletion: with the toggle on, the
    material is there. A test that only proves absence would pass on a bug that
    dropped the signal entirely."""
    body = json.dumps(civ6_client.get("/api/briefing?oracle=1").json())

    assert "combat desire" in body or "Diplomatic friction" in body


def test_civ6_still_declares_no_victory_paths_and_populates_no_strategies(civ6_state):
    assert not CIV6.supports(Capability.VICTORY_PATHS)
    assert civ6_state.strategies == {}


def test_no_civ6_insight_or_intel_event_infers_a_victory_path(civ6_state):
    """The back door this design has been most careful about: scored tech and
    civic preferences must stay descriptive.

    Excludes `advisors/victory.py`'s own PRE-EXISTING insights: they legitimately
    say "victory score" (the game's real, in-game victory-progress meter -- an
    honest, unrelated concept from phase 1/2a) and checking that against
    the real capture found it fires there, which is correct behaviour, not a
    leak. Excluding just that one advisor keeps the guard broad -- every OTHER
    advisor's insights and every intel event are still scanned, so a future
    task's insight that leaks victory-path vocabulary is still caught here."""
    other_insights = [i for i in run_all(civ6_state) if i.advisor != "victory"]
    text = " ".join(
        [f"{i.title} {i.recommendation} {i.why}" for i in other_insights]
        + [e.text for e in intel.feed(civ6_state)]
    ).lower()

    for word in VICTORY_WORDS:
        assert word not in text, f"a Civ VI claim uses {word!r}"
    for path in ("science victory", "cultural victory", "military victory",
                 "economic victory", "espionage victory"):
        assert path not in text


def test_the_capability_report_tells_the_ui_what_each_game_has(civ6_dir):
    from civ_advisor.api.serialize import capability_report
    from civ_advisor.games.civ7 import CIV7

    six, seven = capability_report(CIV6), capability_report(CIV7)

    assert six[Capability.COMBAT_DESIRE.value]["supported"] is True
    assert seven[Capability.COMBAT_DESIRE.value]["supported"] is False
    assert six[Capability.VICTORY_PATHS.value]["supported"] is False
    # Exhaustive on both sides: the UI must be able to say "not supported",
    # never merely omit.
    assert set(six) == set(seven)
