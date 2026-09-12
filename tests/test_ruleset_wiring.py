import pytest

from civ_advisor.advisors import run_all
from civ_advisor.decisions.candidates import named_build
from civ_advisor.decisions.context import Previews, build_context, preview_label
from civ_advisor.decisions.models import PlayerContext, PlayerReport, SourceKind
from civ_advisor.games.base import Capability
from civ_advisor.ruleset.base import NO_RULESET
from civ_advisor.ruleset.civ6 import clear_cache, open_ruleset
from tests.factories import build_queue_row, game_state, snapshot
from tests.ruleset_fixture import make_ruleset

CITY = "LOC_CITY_NAME_TEST1"
AMPHITHEATER = "BUILDING_AMPHITHEATER"


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def snap():
    """A settlement behind on culture with one logged queue — the same shape
    `tests/test_decision_culture.py` uses, so this exercises the real path."""
    state = game_state(turn=33, rivals={1: "Rival One"},
                       human_stats={"culture": 11.0, "gold": 20.0, "cities": 1, "towns": 0},
                       rival_stats={1: {"culture": 17.2}})
    state.build_queues = [build_queue_row(state.latest_turn, 0, CITY, "UNIT_WARRIOR",
                                          added=20.0, current=25.0, needed=30.0)]
    return snapshot(state, run_all(state))


def _ruleset(tmp_path):
    """The fixture database, holding the Amphitheater the shipped catalog already names,
    so the wiring is exercised through a real guide entry rather than a stub."""
    return open_ruleset(make_ruleset(tmp_path, rows={
        "Buildings": [(AMPHITHEATER, "LOC_X", 150, 1, "DISTRICT_THEATER", "",
                       "CIVIC_DRAMA", 0, 0)],
        "Building_YieldChanges": [(AMPHITHEATER, "YIELD_CULTURE", 2)]}))


def test_a_context_without_a_ruleset_is_todays_behaviour(snap):
    context = build_context(snap)

    assert context.ruleset is NO_RULESET
    assert context.ruleset.building("BUILDING_AMPHITHEATER") is None
    assert not [f for f in context.ledger.facts.values()
                if f.source_kind is SourceKind.INSTALLED_RULESET]


def test_a_ruleset_puts_the_real_figures_in_the_ledger(snap, tmp_path):
    context = build_context(snap, ruleset=_ruleset(tmp_path))

    facts = {f.id: f for f in context.ledger.facts.values()
             if f.source_kind is SourceKind.INSTALLED_RULESET}
    assert facts["ruleset.Buildings.BUILDING_AMPHITHEATER.Cost"].value == 150
    assert facts["ruleset.Building_YieldChanges.BUILDING_AMPHITHEATER.YIELD_CULTURE"
                 ".YieldChange"].value == 2


def test_a_named_build_cites_the_ruleset_and_drops_the_no_ruleset_caveat(snap, tmp_path):
    context = build_context(snap, ruleset=_ruleset(tmp_path))

    candidate = named_build(context, CITY, "Test1", AMPHITHEATER,
                            "culture is behind", Previews(item=AMPHITHEATER),
                            "culture")

    assert "ruleset.Buildings.BUILDING_AMPHITHEATER.Cost" in candidate.evidence_ids
    assert not any("installed ruleset is not recorded" in u for u in candidate.unknowns)
    assert any("your installed game files" in t for t in candidate.trade_offs)


def test_a_named_build_without_a_ruleset_keeps_the_caveat_word_for_word(snap):
    """The Civ VII path. This sentence is what the README promises, and a Civ VI feature
    must not have quietly rewritten it."""
    context = build_context(snap)

    candidate = named_build(context, CITY, "Test1", AMPHITHEATER,
                            "culture is behind", Previews(item=AMPHITHEATER),
                            "culture")

    assert ("The installed ruleset is not recorded, so no figure for this building is "
            "taken from any guide — only from your own preview.") in candidate.unknowns


def test_a_named_build_is_still_never_ready_with_a_ruleset(snap, tmp_path):
    """Knowing what a building costs says nothing about whether this settlement is offered
    it. A real cost must not turn a conditional recommendation into a confident one."""
    context = build_context(snap, ruleset=_ruleset(tmp_path))

    candidate = named_build(context, CITY, "Test1", AMPHITHEATER,
                            "culture is behind", Previews(item=AMPHITHEATER),
                            "culture")

    assert candidate.applicability.value == "conditional"
    assert dict(candidate.prerequisites)["offered in this settlement"].value == "unknown"


def test_the_civ6_profile_declares_the_capability_and_the_factory():
    from civ_advisor.games.civ6 import CIV6
    from civ_advisor.games.civ7 import CIV7

    assert CIV6.supports(Capability.INSTALLED_RULESET) and CIV6.ruleset is not None
    assert not CIV7.supports(Capability.INSTALLED_RULESET) and CIV7.ruleset is None


def test_a_game_switch_tears_down_the_cached_ruleset(fixture_dir, civ6_dir, tmp_path, monkeypatch):
    """The lifecycle Task 5 deferred: `open_ruleset` is reachable from the app as of this
    task, so a game switch must close what it opened. Both the detected and the pinned
    switch paths go through `activate()`, so patching the module-level `clear_cache` and
    exercising the pinned path (the simpler of the two to drive deterministically) proves
    the teardown sits somewhere both paths pass through, not just one of them."""
    from fastapi.testclient import TestClient

    from civ_advisor.api.app import create_app
    from civ_advisor.games.civ7 import CIV7
    from civ_advisor.games.selection import GameSelector

    calls = []
    monkeypatch.setattr("civ_advisor.api.app.ruleset_clear_cache", lambda: calls.append(1))

    selector = GameSelector(pinned="civ7", logs_dirs={"civ7": fixture_dir, "civ6": civ6_dir})
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7,
                               selector=selector, storage_base=tmp_path)) as c:
        before = len(calls)
        assert c.post("/api/game", json={"game": "civ6"}).status_code == 200
        after = len(calls)

    assert after > before


# ---- Task 9: the Refine flow itself ----------------------------------------------

def _player_report(item: str, metric: str, value: float, *, turn: int = 33) -> PlayerReport:
    return PlayerReport(id=f"report.{item}.{metric}", subject=CITY,
                        label=preview_label(item, metric), value=value, unit=None,
                        observed_turn=turn, session="session-1", reported_at="2026-09-12T00:00:00")


def test_previews_are_filled_from_the_ruleset_when_the_player_supplied_nothing(snap, tmp_path):
    """spec §7's actual promise: figures can be looked up rather than typed in. With no
    player report at all, the flat yield and the maintenance still show up, read from
    the installed ruleset."""
    context = build_context(snap, ruleset=_ruleset(tmp_path))

    preview = context.previews(CITY, AMPHITHEATER, stat="culture")

    assert preview.yield_delta == 2       # Building_YieldChanges: YIELD_CULTURE = 2
    assert preview.gold_upkeep == 1       # Buildings.Maintenance = 1
    assert preview.ruleset_filled == frozenset({"yield_delta", "gold_upkeep"})


def test_the_players_own_preview_is_never_overridden_by_the_ruleset(snap, tmp_path):
    """The argued precedence: a live observation of this settlement now outranks a
    general fact about the installed file. The ruleset's Amphitheater yield is 2; the
    player's own reading of 5 must win, not be silently replaced."""
    player = PlayerContext(session=snap.session,
                           reports=(_player_report(AMPHITHEATER, "yield_delta", 5.0),))
    context = build_context(snap, player=player, ruleset=_ruleset(tmp_path))

    preview = context.previews(CITY, AMPHITHEATER, stat="culture")

    assert preview.yield_delta == 5.0
    assert "yield_delta" not in preview.ruleset_filled
    # The metric the player did NOT supply is still filled.
    assert preview.gold_upkeep == 1
    assert preview.ruleset_filled == frozenset({"gold_upkeep"})


def test_completion_turns_and_happiness_cost_are_never_filled_from_the_ruleset(snap, tmp_path):
    """What the ruleset cannot know: how long an item takes in this settlement (depends
    on its own production, not a ruleset row) and its local happiness cost (the ruleset
    has no field for it at all -- a decision recorded in `DecisionContext.previews`'s
    docstring, not an oversight). Both must still be asked for."""
    context = build_context(snap, ruleset=_ruleset(tmp_path))

    preview = context.previews(CITY, AMPHITHEATER, stat="culture")

    assert preview.completion_turns is None
    assert preview.happiness_cost is None
    assert preview.missing("completion_turns", "happiness_cost") == (
        "completion_turns", "happiness_cost")


def test_previews_without_a_stat_behave_exactly_as_before(snap, tmp_path):
    """No caller outside yields.py's named families passes `stat`, and none of their
    shape may change: without it, the ruleset is never consulted, matching the
    behaviour before this task."""
    context = build_context(snap, ruleset=_ruleset(tmp_path))

    preview = context.previews(CITY, AMPHITHEATER)

    assert preview.yield_delta is None and preview.gold_upkeep is None
    assert preview.ruleset_filled == frozenset()


def test_the_comparison_text_names_the_ruleset_when_it_filled_a_figure():
    """The evidence-drawer honesty requirement, applied to the comparison prose too:
    "your figures" must never be said about a number the player never typed."""
    from civ_advisor.decisions.yields import _source_note

    all_player = Previews(item=AMPHITHEATER, yield_delta=2, observed_turn=10)
    assert _source_note(all_player) == "your figures, read on turn 10"

    all_ruleset = Previews(item=AMPHITHEATER, yield_delta=2,
                           ruleset_filled=frozenset({"yield_delta", "gold_upkeep"}))
    assert _source_note(all_ruleset) == "your installed ruleset"

    mixed = Previews(item=AMPHITHEATER, yield_delta=2, gold_upkeep=1, observed_turn=10,
                     ruleset_filled=frozenset({"gold_upkeep"}))
    assert _source_note(mixed) == "your installed ruleset and your own figures, read on turn 10"


def test_a_zero_maintenance_building_fills_gold_upkeep_as_zero_not_unstated(snap, tmp_path):
    """Whole-phase review, Important #2: a building the ruleset says costs no gold
    upkeep must fill `gold_upkeep` as 0.0, not leave it None -- the exact defect that let
    a comparison claim "either option costs 1 gold" when the ruleset said one was free."""
    free = "BUILDING_FREE_UPKEEP"
    ruleset = open_ruleset(make_ruleset(tmp_path, rows={"Buildings": [
        (free, "LOC_X", 100, 0, "DISTRICT_CAMPUS", "TECH_WRITING", "", 0, 0)]}))
    context = build_context(snap, ruleset=ruleset)

    preview = context.previews(CITY, free, stat="culture")

    assert preview.gold_upkeep == 0.0
    assert "gold_upkeep" in preview.ruleset_filled


def test_the_api_surfaces_whether_the_ruleset_is_actually_usable_right_now(snap, tmp_path):
    """Whole-phase review, Important #4: `available`/`reason` reached no caller outside
    tests. A player whose ruleset is missing must be told why, somewhere -- not just
    have it computed and discarded. Checks both directions: a working provider reports
    available, a missing database reports the reason `NullRuleset` already wrote."""
    from civ_advisor.api.serialize import decisions_to_dict
    from civ_advisor.decisions import decide_all
    from civ_advisor.ruleset.civ6 import open_ruleset as _open

    working = build_context(snap, ruleset=_ruleset(tmp_path))
    payload = decisions_to_dict(working, decide_all(working))
    assert payload["context"]["ruleset"] == {"available": True, "reason": None}

    missing = _open(tmp_path / "nothing-here.sqlite")
    context = build_context(snap, ruleset=missing)
    payload = decisions_to_dict(context, decide_all(context))
    assert payload["context"]["ruleset"]["available"] is False
    assert "nothing-here.sqlite" in payload["context"]["ruleset"]["reason"]


def test_civ6s_empty_catalog_means_no_recommendation_names_a_building_yet(snap, tmp_path):
    """The whole-phase review's Critical: every candidate-producing path in the decision
    layer (`named_build`, `inspect_options`, `inspect_requirement`, `compare_specialist`)
    requires a reviewed guide entry from the catalog, and Civ VI's guide catalog has
    none. Populating `family_options` from the ruleset (Building_YieldChanges genuinely
    knows which yield a building serves) would not change this: every one of those
    functions independently returns `None` on an empty catalog before it would ever
    reach the ruleset. This records today's argued limitation as a test rather than an
    assumption. It should start failing, in a good way, the moment a real Civ VI guide
    is reviewed and added -- update this test then, rather than treating that as a
    regression."""
    from civ_advisor.decisions import decide_all
    from civ_advisor.knowledge.catalog import load_catalog

    catalog = load_catalog(package="civ_advisor.knowledge.civ6")
    assert catalog.entries == (), "this test's premise no longer holds -- a Civ VI guide exists now"

    context = build_context(snap, catalog=catalog, ruleset=_ruleset(tmp_path))
    assert decide_all(context) == ()
