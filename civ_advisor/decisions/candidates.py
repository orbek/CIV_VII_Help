"""Build `ActionCandidate`s from reviewed guides and observed evidence.

Every candidate here gets its steps from the catalog, not from this module's imagination.
Three rules are enforced structurally rather than remembered:

  - a named build is never `READY`. Whether an option is offered in a settlement is
    unknown from the logs, so the strongest a named item can be is CONDITIONAL — and only
    once the player has confirmed it is offered.
  - a candidate whose guide is not reviewed gets no steps, and therefore is not a
    candidate at all. The observation stays visible; the how-to does not get invented.
    This is what keeps a family the catalog does not cover — expansion, today — out of the
    decision brief instead of borrowing another family's instructions.
  - a guide whose steps are scoped to a game version says so on the candidate, because no
    log records which version is installed.
"""
from __future__ import annotations

from civ_advisor.advisors.base import Provenance
from civ_advisor.knowledge.catalog import GuideEntry
from civ_advisor.ruleset.base import BuildingFacts

from .context import DecisionContext, Previews, age_prerequisite
from .evidence import ruleset_fact
from .models import ActionCandidate, Applicability, Prerequisite

WORKFLOW_GUIDE = "guide.official.settlements"
SPECIALISTS_GUIDE = "guide.specialists"
NAVAL_GUIDE = "guide.official.naval_combat"

NO_INSTRUCTIONS = ("No reviewed guide covers this mechanic, so no steps are offered. "
                   "The observation above stands on its own.")


def instructive(context: DecisionContext, *guide_ids: str) -> tuple[GuideEntry, ...]:
    """The named guides that may actually back an instruction."""
    entries = []
    for guide_id in guide_ids:
        entry = context.catalog.get(guide_id)
        if entry is not None and entry.instructive and entry not in entries:
            entries.append(entry)
    return tuple(entries)


def for_mechanic(context: DecisionContext, mechanic_key: str) -> tuple[GuideEntry, ...]:
    """Reviewed guides for a mechanic, the workflow guide first when it applies.

    Ordering matters: the workflow guide is the publisher's own description of where the
    numbers live, so it leads, and a mechanic-specific article supplements it.
    """
    entries = [e for e in context.catalog.for_mechanic(mechanic_key) if e.instructive]
    entries.sort(key=lambda e: (e.id != WORKFLOW_GUIDE, e.id))
    return tuple(entries)


def version_notes(entries: tuple[GuideEntry, ...]) -> tuple[str, ...]:
    """Say when a step depends on a game version we cannot confirm is installed."""
    scoped = [e for e in entries if e.supported_rulesets]
    if not scoped:
        return ()
    rulesets = sorted({r for e in scoped for r in e.supported_rulesets})
    return (f"These steps describe {', '.join(rulesets)}; the installed version is not "
            "recorded in any log, so the panels may be arranged differently.",)


def inspect_options(context: DecisionContext, city: str, name: str, why_now: str,
                    mechanic_key: str, yield_label: str,
                    unknowns: tuple[str, ...] = ()) -> ActionCandidate | None:
    """Go and look at what this settlement can actually build for this yield.

    The default candidate whenever availability is unknown, which is always until the
    player says otherwise. It is an inspection, so it can be recommended outright without
    asserting anything about what is on offer.
    """
    entries = for_mechanic(context, mechanic_key)
    if not entries:
        return None
    steps = (f"Open {name} and its production list.",) + tuple(
        step for entry in entries for step in entry.instructions
    )[:4]
    return ActionCandidate(
        id=f"action.{mechanic_key}.inspect.{city}",
        title=f"Inspect {name}'s {yield_label} options",
        target=name, why_now=why_now, applicability=Applicability.INSPECT,
        steps=steps + (f"Note the completion time, the {yield_label} change and the "
                       "maintenance each option previews, so they can be compared here.",),
        evidence_ids=evidence_for(context, city, mechanic_key),
        guide_ids=tuple(e.id for e in entries),
        prerequisites=(("options offered in this settlement", Prerequisite.UNKNOWN),),
        trade_offs=("Looking costs a moment and commits nothing.",) + version_notes(entries),
        unknowns=unknowns + ("Which options this settlement is offered is not in any log.",),
        provenance=Provenance.FAIR,
    )


def named_build(context: DecisionContext, city: str, name: str, item: str, why_now: str,
                previews: Previews, mechanic_key: str,
                trade_offs: tuple[str, ...] = ()) -> ActionCandidate | None:
    """A specific building, named only because the player confirmed it is on offer."""
    entry = next(iter(instructive(context, *[e.id for e in context.catalog.for_item(item)])), None)
    if entry is None:
        return None
    workflow = instructive(context, WORKFLOW_GUIDE)
    confirmed_available = item in (context.available_options(city) or ())
    prerequisites: list[tuple[str, Prerequisite]] = [
        ("offered in this settlement",
         Prerequisite.MET if confirmed_available else Prerequisite.UNKNOWN),
        ("Age and ruleset applicability", age_prerequisite(context)),
        ("a legal placement",
         Prerequisite.MET if context.flagged(city, "placement_legal", item) else Prerequisite.UNKNOWN),
    ]
    ruleset_facts = context.ruleset.building(item)
    ruleset_ids: tuple[str, ...] = ()
    ruleset_trade_offs: tuple[str, ...] = ()
    if ruleset_facts is not None and ruleset_facts.figures:
        ruleset_ids = tuple(ruleset_fact(context.ledger, f).id
                            for f in ruleset_facts.figures)
        ruleset_trade_offs = (_ruleset_summary(ruleset_facts),)

    unknowns: list[str] = []
    if not confirmed_available:
        unknowns.append(f"Whether {entry.title} is offered in {name} at all.")
    if ruleset_ids:
        unknowns.append("The figures above are read from your installed ruleset, not from "
                        "a guide. What this settlement is offered, and whether a placement "
                        "is legal, are still unknown.")
    else:
        unknowns.append("The installed ruleset is not recorded, so no figure for this "
                        "building is taken from any guide — only from your own preview.")
    unknowns.extend(m.as_unknown() for m in (ruleset_facts.mentions if ruleset_facts else ()))
    missing = previews.missing("completion_turns", "yield_delta")
    if missing:
        unknowns.append("Not supplied from the preview: " + ", ".join(missing) + ".")
    return ActionCandidate(
        id=f"action.{mechanic_key}.build.{city}.{item}",
        title=f"Build {entry.title} in {name}",
        target=name, why_now=why_now,
        # Never READY: availability, Age applicability and placement legality are all
        # things only the screen can settle, so this stays conditional by construction.
        applicability=Applicability.CONDITIONAL,
        steps=tuple(entry.instructions) + tuple(
            step for e in workflow for step in e.instructions[1:3]),
        evidence_ids=evidence_for(context, city, mechanic_key) + previews.fact_ids + ruleset_ids,
        guide_ids=(entry.id,) + tuple(e.id for e in workflow),
        prerequisites=tuple(prerequisites),
        trade_offs=trade_offs + ruleset_trade_offs + version_notes((entry,) + workflow),
        unknowns=tuple(unknowns),
        provenance=Provenance.FAIR,
    )


def _ruleset_summary(facts: BuildingFacts) -> str:
    """One sentence naming what the installed files say, and which file they are.

    Reads every figure off its own label and unit rather than picking out the ones this
    function expects: a building with only a prerequisite row still produces a correct
    sentence, and there is no index into a list that may be empty. Says the file and its
    digest rather than a version, because the database states no version — see
    docs/architecture/adr-002-ruleset-derived-figures.md.
    """
    said = "; ".join(f"{figure.label} {figure.value}"
                     + (f" {figure.unit}" if figure.unit else "")
                     for figure in facts.figures)
    return (f"Your installed ruleset states — {said}. Read from "
            f"{facts.figures[0].identity.describe()}.")


def inspect_requirement(context: DecisionContext, city: str, name: str, why_now: str,
                        mechanic_key: str, stat: str,
                        yield_label: str) -> ActionCandidate | None:
    """The player looked and no option for this yield was offered. Ask what is required.

    Deliberately does not single out one building. The catalog documents a couple of
    buildings for some yields, but nothing establishes which of them this settlement could
    unlock, and picking one to ask about would smuggle in an assumption the logs cannot
    support.
    """
    entries = for_mechanic(context, mechanic_key)
    if not entries:
        return None
    documented = sorted(
        entry.title
        for item in context.catalog.item_yields
        if stat in context.catalog.yields_for_item(item)
        for entry in context.catalog.for_item(item)
    )
    examples = (f" The reviewed guides here cover {', '.join(documented)}, which may or may "
                "not be the options this Age offers you." if documented else "")
    return ActionCandidate(
        id=f"action.{mechanic_key}.requirement.{city}",
        title=f"Find out what a {yield_label} option in {name} would require",
        target=name, why_now=why_now, applicability=Applicability.INSPECT,
        steps=(f"In {name}'s production list, read what the game says is required for the "
               f"{yield_label} options it shows as unavailable." + examples,
               "Check whether a research, civic or Age condition is what is missing, and "
               f"whether another available option already covers {yield_label} here.",
               "Keep the existing queue in the meantime rather than switching to something "
               "you have not confirmed is offered."),
        evidence_ids=evidence_for(context, city, mechanic_key),
        guide_ids=tuple(e.id for e in entries),
        prerequisites=(("the requirement itself", Prerequisite.UNKNOWN),),
        trade_offs=("The current queue keeps its progress while you look.",),
        unknowns=("No log records unlocks, research or requirements, so this can only be "
                  "read in game.",),
        provenance=Provenance.FAIR,
    )


def compare_specialist(context: DecisionContext, city: str, name: str, why_now: str,
                       yield_label: str) -> ActionCandidate | None:
    """The specialist alternative — as a local check, never as a recommendation.

    Empire happiness cannot validate a specialist: the cost is local and only the
    settlement's own display shows it. So this is always an inspection with the missing
    local figures named.
    """
    entries = instructive(context, SPECIALISTS_GUIDE, WORKFLOW_GUIDE)
    if not entries:
        return None
    return ActionCandidate(
        id=f"action.specialist.{city}",
        title=f"Check whether a specialist in {name} is supportable",
        target=name,
        why_now=why_now, applicability=Applicability.INSPECT,
        steps=tuple(step for entry in entries for step in entry.instructions)[:4],
        evidence_ids=evidence_for(context, city, "specialists"),
        guide_ids=tuple(e.id for e in entries),
        prerequisites=(("a free specialist slot here", Prerequisite.UNKNOWN),
                       ("local food and happiness room", Prerequisite.UNKNOWN)),
        trade_offs=(f"A specialist takes local food and happiness that this settlement may "
                    f"need for growth, which may matter more than {yield_label}.",)
        + version_notes(entries),
        unknowns=("Specialist slots and local happiness room are not in any log; the "
                  "empire happiness total cannot stand in for them.",),
        provenance=Provenance.FAIR,
    )


# ---- defence ---------------------------------------------------------------------

def reinforce_settlement(context: DecisionContext, city: str, name: str,
                         why_now: str) -> ActionCandidate | None:
    """Look at what the threatened settlement could actually build to defend itself.

    Nothing in the reviewed catalog describes inspecting a settlement's defences, so this
    borrows nothing: it uses the publisher's own description of the production menu, which
    is where a defensive build is chosen and where its build time is shown.
    """
    entries = instructive(context, WORKFLOW_GUIDE)
    if not entries:
        return None
    return ActionCandidate(
        id=f"action.defense.reinforce.{city}",
        title=f"Check what {name} can build to defend itself",
        target=name, why_now=why_now, applicability=Applicability.INSPECT,
        steps=(f"Open {name}'s production list and read the build time beside each "
               "defensive option it offers, so you know what could arrive in time.",
               "Compare that against what is already queued before replacing it: the "
               "progress on the current item is shown there too.",
               "Nothing here tells you the garrison you already have — check the "
               "settlement's own tiles for that."),
        evidence_ids=evidence_for(context, city, "defense"),
        guide_ids=tuple(e.id for e in entries),
        prerequisites=(("defensive options offered here", Prerequisite.UNKNOWN),
                       ("the garrison already present", Prerequisite.UNKNOWN)),
        trade_offs=("Switching production loses nothing already accumulated, but delays "
                    "whatever it replaces.",) + version_notes(entries),
        unknowns=("No log records what a settlement can build, what defences it has, or "
                  "its walls; all three can only be read in game.",),
        provenance=Provenance.FAIR,
    )


def withdraw_exposed_unit(context: DecisionContext, name: str,
                          why_now: str) -> ActionCandidate | None:
    """Check whether an exposed unit can actually be reached this turn.

    The only defensive case the official guide covers, and it covers it for naval combat
    specifically — which is why the version and the scope are both stated on the candidate.
    """
    entries = instructive(context, NAVAL_GUIDE)
    if not entries:
        return None
    return ActionCandidate(
        id="action.defense.withdraw",
        title="Check the reach of what is threatening your exposed units",
        target=name, why_now=why_now, applicability=Applicability.INSPECT,
        steps=tuple(entries[0].instructions),
        evidence_ids=evidence_for(context, None, "defense"),
        guide_ids=tuple(e.id for e in entries),
        prerequisites=(("the threatening unit's actual range", Prerequisite.UNKNOWN),),
        trade_offs=("Withdrawing gives up the position; holding risks the unit.",)
        + version_notes(entries),
        unknowns=("These steps are written from the publisher's naval combat guide, so "
                  "they describe naval ranges; for a land threat use them only as a "
                  "reminder to check reach before holding position.",),
        provenance=Provenance.ORACLE,   # the sighting that prompts it is intercepted
    )


def evidence_for(context: DecisionContext, city: str | None,
                 mechanic_key: str) -> tuple[str, ...]:
    """The facts a candidate about this settlement and mechanic rests on."""
    ids = []
    stat = mechanic_key if mechanic_key in context.comparisons else None
    if stat:
        ids.append(context.comparisons[stat].id)
    if city is not None:
        settlement = context.settlement(city)
        if settlement is not None:
            ids.append(settlement.queue_fact_id)
    if context.coverage_fact_id:
        ids.append(context.coverage_fact_id)
    if mechanic_key == "defense":
        ids.extend(f.id for f in context.defense_facts)
        coverage = context.ledger.get(f"defense.coverage.{context.analysis_turn}")
        if coverage is not None:
            ids.append(coverage.id)
    elif context.net_gold is not None:
        ids.append(context.net_gold.id)
    return tuple(dict.fromkeys(ids))


__all__ = ["NO_INSTRUCTIONS", "compare_specialist", "evidence_for", "for_mechanic",
           "inspect_options", "inspect_requirement", "instructive", "named_build",
           "reinforce_settlement", "version_notes", "withdraw_exposed_unit"]
