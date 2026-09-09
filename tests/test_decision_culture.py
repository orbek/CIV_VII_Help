"""The culture pilot, branch by branch, plus the plan's worked refinement case.

These are synthetic scenarios on purpose: they are separate from the player's own save
and, critically, separate from any figure on a wiki page. Every number a comparison uses
here is supplied by the "player" as a dated preview, which is the only way a figure is
allowed into a recommendation at all.
"""
from __future__ import annotations

import pytest

from civ7_advisor.advisors import run_all
from civ7_advisor.advisors.base import Severity
from civ7_advisor.decisions import culture
from civ7_advisor.decisions.context import (
    AVAILABLE_OPTIONS,
    LARGEST,
    LOCAL_HAPPINESS_OK,
    NO_DISPLACEMENT,
    OBJECTIVE,
    PLACEMENT_LEGAL,
    SOONEST,
    ContextConflict,
    ContextStore,
    build_context,
    preview_label,
)
from civ7_advisor.decisions.models import Applicability, PlayerContext, PlayerReport, Prerequisite
from civ7_advisor.ingest.tactical import OperationRow
from tests.factories import build_queue_row, city_target, game_state, snapshot

CITY = "LOC_CITY_NAME_TEST1"
MONUMENT = "BUILDING_MONUMENT"
AMPHITHEATER = "BUILDING_AMPHITHEATER"


def behind_state(item: str = "UNIT_WARRIOR", *, current: float = 25.0, needed: float = 30.0,
                 added: float = 20.0, culture: float = 11.0, rival_culture: float = 17.2,
                 net_gold: float | None = 10.0, turn: int = 33):
    """A settlement behind on culture, with one logged queue.

    Modelled on the plan's turn-33 regression scenario: culture 11.0 against a 17.2 rival
    median, with a nearly finished Warrior. It is a reconstruction of an earlier
    observation, not a claim about anyone's current turn.
    """
    maintenance = None if net_gold is None else int(20.0 - net_gold)
    human = {"culture": culture, "gold": 20.0}
    if maintenance is not None:
        human |= {"total_maintenance": maintenance, "unit_maintenance": maintenance,
                  "building_maintenance": 0}
    human |= {"happiness_total": 5, "happiness_threshold": 20, "cities": 1, "towns": 0}
    state = game_state(
        turn=turn, rivals={1: "Rival One", 2: "Rival Two"},
        human_stats=human,
        rival_stats={1: {"culture": rival_culture}, 2: {"culture": rival_culture}},
    )
    state.build_queues = [build_queue_row(state.latest_turn, 0, CITY, item,
                                          added=added, current=current, needed=needed)]
    return state


def context_for(state, reports: tuple[PlayerReport, ...] = (), oracle: bool = True,
                revision: int = 0):
    snap = snapshot(state, run_all(state))
    player = PlayerContext(session=snap.session, revision=revision, reports=reports)
    return build_context(snap, player, oracle=oracle)


def report(label: str, value, *, subject: str = CITY, turn: int = 33, unit: str | None = None):
    """A player report. Per-item flags carry the item in their id, because two confirmed
    placements are two distinct facts and the ledger refuses to file them under one id."""
    suffix = f".{value}" if label in (PLACEMENT_LEGAL, LOCAL_HAPPINESS_OK, NO_DISPLACEMENT) else ""
    return PlayerReport(id=f"report.{subject}.{label}{suffix}", subject=subject, label=label,
                        value=value, unit=unit, observed_turn=turn, session="session-1",
                        reported_at="2026-09-08T12:00:00")


# ---- the base card ---------------------------------------------------------------

def test_the_card_names_a_settlement_a_timing_and_a_practical_next_step():
    """The plan's minimum: not just the yield deficit."""
    card = culture.decide(context_for(behind_state()))
    assert card is not None and card.id == f"decision.culture.{CITY}"
    assert card.subject == "Culture in Test1" and card.severity is Severity.ADVISE
    action = card.preferred
    assert action.applicability is Applicability.INSPECT
    assert action.target == "Test1"
    # A timing reason, tied to the observed queue rather than to the deficit alone.
    assert "about 1 turn left on Warrior at the logged rate" in action.why_now
    assert "your culture is 64% of the observed rival median" in action.why_now
    assert action.steps and any("production list" in s for s in action.steps)
    assert "guide.culture" in action.guide_ids
    assert "guide.official.settlements" in action.guide_ids     # the officially sourced workflow
    # Every citation resolves to a real observation.
    facts = card.evidence_ids
    assert facts and len(context_for(behind_state()).ledger.resolve(facts)) == len(facts)
    assert card.observed_turns


def test_availability_is_never_assumed_so_no_building_is_named_unprompted():
    card = culture.decide(context_for(behind_state()))
    assert all(MONUMENT not in c.id for c in card.candidates)
    assert "not in any log" in card.preferred.unknowns[-1]
    assert any("Which options Test1 is offered" in u for u in card.unknowns)
    assert card.preferred.prerequisites == (("options offered in this settlement",
                                             Prerequisite.UNKNOWN),)


def test_the_specialist_alternative_demands_a_local_check_first():
    card = culture.decide(context_for(behind_state()))
    specialist = next(c for c in card.candidates if "specialist" in c.id)
    assert specialist.applicability is Applicability.INSPECT
    assert dict(specialist.prerequisites)["a free specialist slot here"] is Prerequisite.UNKNOWN
    assert any("empire happiness total cannot stand in" in u for u in specialist.unknowns)


def test_identical_state_produces_an_identical_decision():
    first = culture.decide(context_for(behind_state()))
    second = culture.decide(context_for(behind_state()))
    assert first == second


# ---- section 6 branches ----------------------------------------------------------

def test_an_immediate_attack_objective_defers_culture_without_hiding_it():
    state = behind_state()
    state.targets = [city_target(state.complete_through_turn, 1, owner=0, x=4, y=5)]
    state.operations = [OperationRow(state.complete_through_turn, 1, "Attack Enemy City",
                                     (4, 5), ("Goal 4:5",))]
    context = build_context(snapshot(state, run_all(state)))
    assert context.defense_is_urgent
    card = culture.decide(context)
    assert card is not None                                  # still present, not hidden
    assert card.severity is Severity.INFO                    # not competing with the alert
    assert card.priority_reason.startswith("Deferred: a freshly recorded attack objective")
    assert "Check the defensive alert first" in card.preferred.why_now


def test_a_dated_attack_objective_does_not_defer_the_decision():
    """A plan the AI stopped re-emitting is evidence, not an emergency."""
    state = behind_state()
    old = state.complete_through_turn - 9
    state.targets = [city_target(old, 1, owner=0, x=4, y=5)]
    state.operations = [OperationRow(old, 1, "Attack Enemy City", (4, 5), ("Goal 4:5",))]
    context = build_context(snapshot(state, run_all(state)))
    assert context.defense_is_urgent is False
    card = culture.decide(context)
    assert not card.priority_reason.startswith("Deferred")


def test_a_culture_item_already_queued_reports_timing_instead_of_a_duplicate():
    state = behind_state(item=MONUMENT, current=10.0, needed=60.0, added=10.0)
    card = culture.decide(context_for(state))
    assert card.severity is Severity.INFO
    assert "already building Monument" in card.preferred.why_now
    assert "not a second thing to queue" in card.preferred.why_now


def test_an_idle_settlement_is_preferred_over_one_that_is_nearly_finished():
    """And only settlements with a logged queue are eligible at all."""
    state = behind_state()
    state.build_queues = [
        build_queue_row(state.latest_turn, 0, "LOC_CITY_NAME_BUSY", "UNIT_WARRIOR",
                        added=20.0, current=25.0, needed=30.0),
        build_queue_row(state.latest_turn, 0, "LOC_CITY_NAME_IDLE", "",
                        added=0.0, current=0.0, needed=0.0),
    ]
    card = culture.decide(context_for(state))
    assert card.subject == "Culture in Idle"
    assert "queue was logged empty" in card.preferred.why_now


def test_unobserved_settlements_are_named_as_unknown_not_treated_as_idle():
    state = behind_state()
    state.turns[state.complete_through_turn][0] = type(
        state.turns[state.complete_through_turn][0])(
        **(state.turns[state.complete_through_turn][0].__dict__ | {"cities": 4, "towns": 2}))
    card = culture.decide(context_for(state))
    assert any("5 of your settlements have no logged queue" in u for u in card.unknowns)
    assert any("unknown, not idle" in u for u in card.unknowns)


def test_no_logged_queue_at_all_names_no_settlement():
    state = behind_state()
    state.build_queues = []
    card = culture.decide(context_for(state))
    assert card.id == "decision.culture.unobserved"
    assert card.preferred is None and card.candidates == ()
    assert "no settlement to name" in card.priority_reason


def test_unknown_net_gold_is_stated_rather_than_assumed_affordable():
    card = culture.decide(context_for(behind_state(net_gold=None)))
    assert any("Net gold per turn is unknown" in u for u in card.unknowns)
    assert any("a balance alone is not affordability" in u for u in card.unknowns)


def test_local_happiness_room_is_never_inferred_from_the_empire_total():
    card = culture.decide(context_for(behind_state()))
    assert any("Local happiness room in this settlement is unknown" in u for u in card.unknowns)


def test_the_age_is_reported_as_dated_and_gates_nothing():
    from tests.factories import kill

    state = behind_state()
    state.events = [kill(state.complete_through_turn, 1, 0)]
    context = context_for(state)
    assert context.age is not None and context.age.value == "AGE_ANTIQUITY"
    card = culture.decide(context)
    assert any("no log states the current Age" in u for u in card.unknowns)


def test_a_reported_absence_of_options_turns_the_decision_into_a_prerequisite_check():
    """The player looked and there was nothing. That makes the requirement the question —
    and no build order is invented."""
    card = culture.decide(context_for(behind_state(), (report(AVAILABLE_OPTIONS, ""),)))
    assert "no culture option is offered" in card.priority_reason
    action = card.preferred
    assert action.applicability is Applicability.INSPECT
    # It asks what a culture option would require, without singling out a building
    # nothing establishes this settlement could actually unlock.
    assert action.title == "Find out what a culture option in Test1 would require"
    assert any("Keep the existing queue" in s for s in action.steps)
    assert any("may or may not be the options this Age offers you" in s for s in action.steps)
    assert dict(action.prerequisites)["the requirement itself"] is Prerequisite.UNKNOWN


def test_confirmed_options_without_previews_ask_for_exactly_what_is_missing():
    reports = (report(AVAILABLE_OPTIONS, f"{MONUMENT},{AMPHITHEATER}"),
               report(preview_label(MONUMENT, "completion_turns"), 4, unit="turns"))
    card = culture.decide(context_for(behind_state(), reports))
    assert "previews needed to choose between them are not all supplied" in card.priority_reason
    assert all(c.applicability is not Applicability.READY for c in card.candidates)
    missing = next(u for u in card.unknowns if u.startswith("Preview figures still missing"))
    assert "yield_delta" in missing and MONUMENT in missing
    assert f"{AMPHITHEATER}: completion_turns, yield_delta" in missing


def test_a_named_build_stays_conditional_even_when_the_player_confirmed_it():
    reports = (report(AVAILABLE_OPTIONS, MONUMENT),
               report(preview_label(MONUMENT, "completion_turns"), 4),
               report(preview_label(MONUMENT, "yield_delta"), 3))
    card = culture.decide(context_for(behind_state(), reports))
    named = next(c for c in card.candidates if c.id.endswith(MONUMENT))
    assert named.applicability is Applicability.CONDITIONAL
    prerequisites = dict(named.prerequisites)
    assert prerequisites["offered in this settlement"] is Prerequisite.MET
    # Age applicability is never established, so the action can never be unconditional.
    assert prerequisites["Age and ruleset applicability"] is Prerequisite.UNKNOWN
    assert prerequisites["a legal placement"] is Prerequisite.UNKNOWN
    assert any("no figure for this building is taken from any guide" in u for u in named.unknowns)
    assert "guide.building.monument" in named.guide_ids


def test_a_guide_that_is_not_reviewed_yields_no_steps_and_no_candidate():
    """No reviewed source means the observation stands alone; steps are not invented."""
    import json

    from civ7_advisor.knowledge.catalog import load_catalog

    raw = json.loads(load_catalog.__module__ and _catalog_json())
    for row in raw["entries"]:
        row["review_status"] = "link_only"
        row["instructions"] = []
    stripped = load_catalog(json.dumps(raw))
    snap = snapshot(behind_state(), run_all(behind_state()))
    context = build_context(snap, catalog=stripped)
    assert culture.decide(context) is None


def _catalog_json() -> str:
    from importlib import resources
    return resources.files("civ7_advisor.knowledge").joinpath("guides.json").read_text("utf-8")


# ---- the worked refinement acceptance case (plan section 6) ----------------------

def refinement_reports(objective: str) -> tuple[PlayerReport, ...]:
    """The plan's hypothetical previews. Not general rules for either building."""
    return (
        report(OBJECTIVE, objective),
        report(AVAILABLE_OPTIONS, f"{MONUMENT},{AMPHITHEATER}"),
        report(PLACEMENT_LEGAL, MONUMENT), report(PLACEMENT_LEGAL, AMPHITHEATER),
        report(LOCAL_HAPPINESS_OK, MONUMENT), report(LOCAL_HAPPINESS_OK, AMPHITHEATER),
        report(NO_DISPLACEMENT, MONUMENT), report(NO_DISPLACEMENT, AMPHITHEATER),
        report(preview_label(MONUMENT, "completion_turns"), 4, unit="turns"),
        report(preview_label(MONUMENT, "yield_delta"), 3, unit="culture per turn"),
        report(preview_label(MONUMENT, "gold_upkeep"), 2, unit="gold per turn"),
        report(preview_label(MONUMENT, "happiness_cost"), 2, unit="happiness per turn"),
        report(preview_label(AMPHITHEATER, "completion_turns"), 6, unit="turns"),
        report(preview_label(AMPHITHEATER, "yield_delta"), 5, unit="culture per turn"),
        report(preview_label(AMPHITHEATER, "gold_upkeep"), 2, unit="gold per turn"),
        report(preview_label(AMPHITHEATER, "happiness_cost"), 2, unit="happiness per turn"),
    )


def test_the_worked_case_chooses_monument_and_shows_what_it_gives_up():
    card = culture.decide(context_for(behind_state(net_gold=10.0), refinement_reports(SOONEST)))
    chosen = card.preferred
    assert chosen.id.endswith(MONUMENT), "the sooner completion wins the stated objective"
    assert chosen.applicability is Applicability.CONDITIONAL
    assert [c.id.rsplit(".", 1)[-1] for c in card.alternatives][0] == AMPHITHEATER

    shown = " ".join(chosen.trade_offs)
    assert "next culture increase as soon as possible" in shown
    assert "Monument: 4 turns to complete; 3 culture per turn" in shown
    assert "Amphitheater: 6 turns to complete; 5 culture per turn" in shown
    # The opportunity cost, with the arithmetic.
    assert "Amphitheater eventually adds 2 more culture per turn than Monument" in shown
    assert "takes 2 turns longer" in shown
    # The upkeep effect on the supplied net gold, labelled as a scenario estimate.
    assert "take your net gold from 10 to 8 per turn" in shown
    assert "not a forecast of your income" in shown
    assert "not a claim about the best play available in the game" in shown

    # The how-to names the city and its own preview, and links both items.
    steps = " ".join(chosen.steps)
    assert "production list" in steps and "legal" in steps.lower()
    assert "guide.building.monument" in chosen.guide_ids
    assert "guide.official.settlements" in chosen.guide_ids
    assert "guide.building.amphitheater" in card.alternatives[0].guide_ids
    assert "reason" not in card.priority_reason or "objective" in card.priority_reason
    assert "shorter completion estimate decide it" in card.priority_reason


def test_changing_the_objective_changes_the_choice_and_explains_the_delay():
    card = culture.decide(context_for(behind_state(net_gold=10.0), refinement_reports(LARGEST)))
    assert card.preferred.id.endswith(AMPHITHEATER)
    shown = " ".join(card.preferred.trade_offs)
    assert "largest eventual culture increase" in shown
    assert "takes 2 turns longer" in shown


def test_returning_compare_the_options_would_fail_the_case():
    """Guard against the failure the plan calls out by name."""
    card = culture.decide(context_for(behind_state(net_gold=10.0), refinement_reports(SOONEST)))
    assert card.preferred is not None
    assert card.preferred.title == "Build Monument in Test1"


def test_withdrawing_the_previews_removes_the_choice_and_asks_only_for_what_is_missing():
    kept = tuple(r for r in refinement_reports(SOONEST)
                 if "yield_delta" not in r.label)
    card = culture.decide(context_for(behind_state(net_gold=10.0), kept))
    assert card.preferred.applicability is not Applicability.READY
    assert "not all supplied" in card.priority_reason
    missing = next(u for u in card.unknowns if u.startswith("Preview figures still missing"))
    assert "yield_delta" in missing and "completion_turns" not in missing


def test_withdrawing_availability_removes_the_named_choice_entirely():
    kept = tuple(r for r in refinement_reports(SOONEST) if r.label != AVAILABLE_OPTIONS)
    card = culture.decide(context_for(behind_state(net_gold=10.0), kept))
    assert all(not c.id.endswith((MONUMENT, AMPHITHEATER)) for c in card.candidates)
    assert card.preferred.applicability is Applicability.INSPECT


def test_no_objective_means_no_winner_because_the_goal_decides():
    kept = tuple(r for r in refinement_reports(SOONEST) if r.label != OBJECTIVE)
    context = context_for(behind_state(net_gold=10.0), kept)
    comparison = culture.compare(context, CITY, (MONUMENT, AMPHITHEATER), None)
    assert comparison.winner is None and comparison.lines == ()
    card = culture.decide(context)
    assert "not all supplied" in card.priority_reason or "confirmed culture option" in card.priority_reason
    assert all(c.applicability is not Applicability.READY for c in card.candidates)


def test_a_missing_metric_is_missing_and_never_zero():
    context = context_for(behind_state(), (
        report(AVAILABLE_OPTIONS, f"{MONUMENT},{AMPHITHEATER}"),
        report(OBJECTIVE, SOONEST),
        report(preview_label(MONUMENT, "completion_turns"), 4),
        report(preview_label(MONUMENT, "yield_delta"), 3),
        report(preview_label(AMPHITHEATER, "completion_turns"), 6),
    ))
    comparison = culture.compare(context, CITY, (MONUMENT, AMPHITHEATER), SOONEST)
    assert comparison.winner is None, "one usable option is not a comparison"
    assert comparison.incomplete == (f"{AMPHITHEATER}: yield_delta",)
    preview = context.previews(CITY, AMPHITHEATER)
    assert preview.yield_delta is None and preview.completion_turns == 6


# ---- the player-context concurrency contract (plan section 4) --------------------

def make_store(session: str = "session-1", epoch: int = 1) -> ContextStore:
    store = ContextStore()
    store.session, store.epoch = session, epoch
    return store


def test_an_accepted_report_moves_the_context_revision_even_with_no_new_logs():
    store = make_store()
    before = store.revision
    store.submit(report(OBJECTIVE, SOONEST), epoch=1, base_revision=before)
    assert store.revision == before + 1
    assert store.context().for_subject(CITY)[0].label == OBJECTIVE
    # Resubmitting the same value changes nothing.
    store.submit(report(OBJECTIVE, SOONEST), epoch=1, base_revision=store.revision)
    assert store.revision == before + 1


def test_a_form_opened_before_a_reload_cannot_attach_to_the_new_session():
    store = make_store(session="session-2", epoch=2)
    with pytest.raises(ContextConflict) as caught:
        store.submit(report(OBJECTIVE, SOONEST), epoch=1, base_revision=0)
    assert caught.value.reason == "session_changed"
    assert "reloaded since the form was opened" in caught.value.detail
    assert store.context().reports == ()


def test_a_stale_submission_is_accepted_when_nothing_it_depends_on_moved():
    store = make_store()
    store.submit(report(OBJECTIVE, SOONEST), epoch=1, base_revision=0)
    accepted = store.submit(
        report(preview_label(MONUMENT, "yield_delta"), 3), epoch=1, base_revision=0,
        dependencies={"queue": "UNIT_WARRIOR@33"},
        current_dependencies={"queue": "UNIT_WARRIOR@33"},
    )
    assert accepted.base_revision == 1


def test_a_stale_submission_is_refused_when_a_dependency_changed():
    store = make_store()
    store.submit(report(OBJECTIVE, SOONEST), epoch=1, base_revision=0)
    with pytest.raises(ContextConflict) as caught:
        store.submit(report(preview_label(MONUMENT, "yield_delta"), 3), epoch=1,
                     base_revision=0, dependencies={"queue": "UNIT_WARRIOR@33"},
                     current_dependencies={"queue": "BUILDING_MONUMENT@34"})
    assert caught.value.reason == "stale_revision"
    assert "queue" in caught.value.detail
    assert caught.value.current.revision == 1     # the caller is told what stands now


def test_only_a_relevant_change_invalidates_a_report():
    store = make_store()
    store.submit(report(preview_label(MONUMENT, "yield_delta"), 3), epoch=1, base_revision=0)
    store.submit(report(OBJECTIVE, SOONEST, subject="LOC_CITY_NAME_OTHER"),
                 epoch=1, base_revision=store.revision)
    assert store.invalidate("LOC_CITY_NAME_UNRELATED", "a rival did something") == ()
    assert len(store.context().reports) == 2
    dropped = store.invalidate(CITY, "this settlement's queue changed")
    assert dropped == (f"report.{CITY}.preview.{MONUMENT}.yield_delta",)
    assert [r.subject for r in store.context().reports] == ["LOC_CITY_NAME_OTHER"]


def test_a_field_the_panel_does_not_collect_is_refused():
    store = make_store()
    with pytest.raises(ContextConflict) as caught:
        store.submit(report("free_text_hopes", "build a wonder"), epoch=1, base_revision=0)
    assert caught.value.reason == "unknown_label"


def test_adopting_a_new_epoch_discards_every_report():
    store = make_store()
    store.submit(report(OBJECTIVE, SOONEST), epoch=1, base_revision=0)
    state = behind_state()
    snap = snapshot(state, run_all(state), session="session-9", epoch=2)
    store.adopt(snap)
    assert store.context().reports == ()
    assert store.session == "session-9" and store.revision == 2


def test_accepted_context_is_reflected_in_the_context_revision():
    """Phase 4 attaches commentary to a decision identity that includes this, so an
    accepted preview that changes the recommendation cannot keep old prose beside it."""
    reports = refinement_reports(SOONEST)
    context = context_for(behind_state(), reports, revision=7)
    assert context.context_revision == 7
    assert context.catalog_revision
    assert culture.decide(context).preferred.id.endswith(MONUMENT)
