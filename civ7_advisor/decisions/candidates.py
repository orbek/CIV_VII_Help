"""Build `ActionCandidate`s from reviewed guides and observed evidence.

Every candidate here gets its steps from the catalog, not from this module's imagination.
Two rules are enforced structurally rather than remembered:

  - a named build is never `READY`. Whether an option is offered in a settlement is
    unknown from the logs, so the strongest a named item can be is CONDITIONAL — and only
    once the player has confirmed it is offered.
  - a candidate whose guide is not reviewed gets no steps, and therefore cannot be a
    candidate at all. The observation stays visible; the how-to does not get invented.
"""
from __future__ import annotations

from civ7_advisor.advisors.base import Provenance
from civ7_advisor.knowledge.catalog import GuideEntry

from .context import DecisionContext, Previews, age_prerequisite
from .models import ActionCandidate, Applicability, Prerequisite

WORKFLOW_GUIDE = "guide.official.settlements"
CULTURE_GUIDE = "guide.culture"
SPECIALISTS_GUIDE = "guide.specialists"

NO_INSTRUCTIONS = ("No reviewed guide covers this mechanic, so no steps are offered. "
                   "The observation above stands on its own.")


def _instructive(context: DecisionContext, *guide_ids: str) -> tuple[GuideEntry, ...]:
    """The named guides that may actually back an instruction."""
    entries = []
    for guide_id in guide_ids:
        entry = context.catalog.get(guide_id)
        if entry is not None and entry.instructive:
            entries.append(entry)
    return tuple(entries)


def _version_note(entries: tuple[GuideEntry, ...]) -> tuple[str, ...]:
    """Say when a step depends on a game version we cannot confirm is installed."""
    scoped = [e for e in entries if e.supported_rulesets]
    if not scoped:
        return ()
    rulesets = sorted({r for e in scoped for r in e.supported_rulesets})
    return (f"These steps describe {', '.join(rulesets)}; the installed version is not "
            "recorded in any log, so the panels may be arranged differently.",)


def inspect_culture_options(context: DecisionContext, city: str, name: str,
                            why_now: str, unknowns: tuple[str, ...] = ()) -> ActionCandidate | None:
    """Go and look at what this settlement can actually build.

    The default candidate whenever availability is unknown, which is always until the
    player says otherwise. It is an inspection, so it can be recommended outright without
    asserting anything about what is on offer.
    """
    entries = _instructive(context, WORKFLOW_GUIDE, CULTURE_GUIDE)
    if not entries:
        return None
    steps = (f"Open {name} and its production list.",) + tuple(
        step for entry in entries for step in entry.instructions
    )[:4]
    return ActionCandidate(
        id=f"action.culture.inspect.{city}",
        title=f"Inspect {name}'s culture options",
        target=name, why_now=why_now, applicability=Applicability.INSPECT,
        steps=steps + ("Note the completion time, the culture change and the maintenance "
                       "each option previews, so they can be compared here.",),
        evidence_ids=_culture_evidence(context, city),
        guide_ids=tuple(e.id for e in entries),
        prerequisites=(("options offered in this settlement", Prerequisite.UNKNOWN),),
        trade_offs=("Looking costs a moment and commits nothing.",),
        unknowns=unknowns + ("Which options this settlement is offered is not in any log.",),
        provenance=Provenance.FAIR,
    )


def named_culture_build(context: DecisionContext, city: str, name: str, item: str,
                        why_now: str, previews: Previews,
                        trade_offs: tuple[str, ...] = ()) -> ActionCandidate | None:
    """A specific building, named only because the player confirmed it is on offer."""
    entry = next(iter(_instructive(context, *[e.id for e in context.catalog.for_item(item)])), None)
    if entry is None:
        return None
    workflow = _instructive(context, WORKFLOW_GUIDE)
    confirmed_available = item in (context.available_options(city) or ())
    prerequisites: list[tuple[str, Prerequisite]] = [
        ("offered in this settlement",
         Prerequisite.MET if confirmed_available else Prerequisite.UNKNOWN),
        ("Age and ruleset applicability", age_prerequisite(context)),
        ("a legal placement",
         Prerequisite.MET if context.flagged(city, "placement_legal", item) else Prerequisite.UNKNOWN),
    ]
    unknowns: list[str] = []
    if not confirmed_available:
        unknowns.append(f"Whether {entry.title} is offered in {name} at all.")
    unknowns.append("The installed ruleset is not recorded, so no figure for this building "
                    "is taken from any guide — only from your own preview.")
    missing = previews.missing("completion_turns", "culture_delta")
    if missing:
        unknowns.append("Not supplied from the preview: " + ", ".join(missing) + ".")
    return ActionCandidate(
        id=f"action.culture.build.{city}.{item}",
        title=f"Build {entry.title} in {name}",
        target=name, why_now=why_now,
        # Never READY: availability, Age applicability and placement legality are all
        # things only the screen can settle, so this stays conditional by construction.
        applicability=Applicability.CONDITIONAL,
        steps=tuple(entry.instructions) + tuple(
            step for e in workflow for step in e.instructions[1:3]),
        evidence_ids=_culture_evidence(context, city) + previews.fact_ids,
        guide_ids=(entry.id,) + tuple(e.id for e in workflow),
        prerequisites=tuple(prerequisites),
        trade_offs=trade_offs + _version_note((entry,) + workflow),
        unknowns=tuple(unknowns),
        provenance=Provenance.FAIR,
    )


def inspect_culture_requirement(context: DecisionContext, city: str,
                                name: str, why_now: str) -> ActionCandidate | None:
    """The player looked and no culture option was offered. Ask what is required.

    Deliberately does not single out one building. We have guides for a couple of culture
    buildings, but nothing establishes which of them this settlement could unlock, and
    picking one to ask about would smuggle in an assumption the logs cannot support.
    """
    workflow = _instructive(context, WORKFLOW_GUIDE, CULTURE_GUIDE)
    if not workflow:
        return None
    documented = sorted(
        entry.title
        for item in context.catalog.item_yields
        if "culture" in context.catalog.yields_for_item(item)
        for entry in context.catalog.for_item(item)
    )
    examples = (f" The reviewed guides here cover {', '.join(documented)}, which may or may "
                "not be the options this Age offers you." if documented else "")
    return ActionCandidate(
        id=f"action.culture.requirement.{city}",
        title=f"Find out what a culture option in {name} would require",
        target=name, why_now=why_now, applicability=Applicability.INSPECT,
        steps=(f"In {name}'s production list, read what the game says is required for the "
               "culture options it shows as unavailable." + examples,
               "Check whether a research, civic or Age condition is what is missing, and "
               "whether another available option already covers culture here.",
               "Keep the existing queue in the meantime rather than switching to something "
               "you have not confirmed is offered."),
        evidence_ids=_culture_evidence(context, city),
        guide_ids=tuple(e.id for e in workflow),
        prerequisites=(("the requirement itself", Prerequisite.UNKNOWN),),
        trade_offs=("The current queue keeps its progress while you look.",),
        unknowns=("No log records unlocks, research or requirements, so this can only be "
                  "read in game.",),
        provenance=Provenance.FAIR,
    )


def compare_specialist(context: DecisionContext, city: str, name: str,
                       why_now: str) -> ActionCandidate | None:
    """The specialist alternative — as a local check, never as a recommendation.

    Empire happiness cannot validate a specialist: the cost is local and only the
    settlement's own display shows it. So this is always an inspection with the missing
    local figures named.
    """
    entries = _instructive(context, SPECIALISTS_GUIDE, WORKFLOW_GUIDE)
    if not entries:
        return None
    return ActionCandidate(
        id=f"action.culture.specialist.{city}",
        title=f"Check whether a specialist in {name} is supportable",
        target=name, why_now=why_now, applicability=Applicability.INSPECT,
        steps=tuple(step for entry in entries for step in entry.instructions)[:4],
        evidence_ids=_culture_evidence(context, city),
        guide_ids=tuple(e.id for e in entries),
        prerequisites=(("a free specialist slot here", Prerequisite.UNKNOWN),
                       ("local food and happiness room", Prerequisite.UNKNOWN)),
        trade_offs=("A specialist takes local food and happiness that this settlement may "
                    "need for growth.",),
        unknowns=("Specialist slots and local happiness room are not in any log; the "
                  "empire happiness total cannot stand in for them.",),
        provenance=Provenance.FAIR,
    )


def _culture_evidence(context: DecisionContext, city: str) -> tuple[str, ...]:
    ids = []
    if context.culture_comparison is not None:
        ids.append(context.culture_comparison.id)
    settlement = context.settlement(city)
    if settlement is not None:
        ids.append(settlement.queue_fact_id)
    if context.coverage_fact_id:
        ids.append(context.coverage_fact_id)
    if context.net_gold is not None:
        ids.append(context.net_gold.id)
    return tuple(ids)


__all__ = ["NO_INSTRUCTIONS", "compare_specialist", "inspect_culture_options",
           "inspect_culture_requirement", "named_culture_build"]
