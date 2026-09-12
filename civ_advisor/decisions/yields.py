"""Yield decisions: which settlement, which next act, and why now.

One implementation for every yield family. What differs between families is only what a
`Family` records: which stat it is about, which mechanic key finds its guides, and whether
the catalog documents any specific build for it. A family with no reviewed guide produces
no steps at all rather than borrowed ones.

Ranking is by stated reasons, in a fixed order, and each decision carries the reason it
sits where it does. There is no numeric strategic-utility score, because there is nothing
to compute one from: "best" depends on what the player is trying to do, which is why the
objective they supply is what breaks the tie between two feasible options.

The order:

  1. An urgent, freshly recorded defensive constraint outranks a yield decision.
  2. A stated objective decides between options that are otherwise both feasible.
  3. Established applicability beats an assumed one: a confirmed option outranks a
     conditional one, which outranks an inspection.
  4. Supported timing and cost evidence beats an undated guess.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from civ_advisor.advisors.base import Severity

from . import candidates
from .context import LARGEST, OBJECTIVES, SOONEST, DecisionContext, Previews
from .models import ActionCandidate, Applicability, DecisionCard

# The ratio at or above which a gap is not worth a decision of its own.
ON_PACE_RATIO = 1.0


@dataclass(frozen=True)
class Family:
    """One yield the advisor can hold a decision about.

    `mechanic_key` is how its guides are found in the catalog; a family whose key matches
    nothing reviewed is reported with its observation and an explicit statement that no
    instructions are available, which is the plan's rule rather than a fallback.
    """

    stat: str            # the PlayerTurn attribute and comparison id
    label: str           # what to call the yield in a sentence
    mechanic_key: str    # catalog mechanic key

    @property
    def unit(self) -> str:
        return f"{self.label} per turn"


FAMILIES: dict[str, Family] = {
    "culture": Family("culture", "culture", "culture"),
    "science": Family("science", "science", "science"),
    "gold": Family("gold", "gold", "gold"),
    "production": Family("production", "production", "production"),
    "food": Family("food", "food", "food"),
    # Expansion is deliberately absent: nothing in the reviewed catalog explains founding
    # a settlement, so it cannot be promoted to a decision. The economy advisor's
    # settlement-slack observation still appears, grouped, with no invented steps.
}


@dataclass(frozen=True)
class Comparison:
    """A deterministic comparison of supplied previews, with the arithmetic shown.

    Every figure in here came from the player's own dated preview. Nothing is defaulted:
    a metric that was not supplied leaves the comparison incomplete and named as such.
    """

    winner: str | None
    objective: str | None
    lines: tuple[str, ...]
    incomplete: tuple[str, ...]


def compare(context: DecisionContext, city: str, items: tuple[str, ...],
            objective: str | None, family: Family) -> Comparison:
    """Rank the supplied options for this family against the stated objective.

    With no objective there is no winner: the two candidates answer different questions
    and picking one would be asserting a goal the player never stated.
    """
    previews = {item: context.previews(city, item, stat=family.stat) for item in items}
    incomplete = tuple(
        f"{item}: {', '.join(p.missing('completion_turns', 'yield_delta'))}"
        for item, p in previews.items()
        if p.missing("completion_turns", "yield_delta")
    )
    usable = {i: p for i, p in previews.items() if not p.missing("completion_turns", "yield_delta")}
    if len(usable) < 2 or objective is None:
        return Comparison(None, objective, (), incomplete)

    if objective == SOONEST:
        winner = min(usable, key=lambda i: (usable[i].completion_turns, -usable[i].yield_delta))
    elif objective == LARGEST:
        winner = max(usable, key=lambda i: (usable[i].yield_delta, -usable[i].completion_turns))
    else:
        return Comparison(None, objective, (), incomplete)

    lines = [f"Your stated objective is {OBJECTIVES[objective].format(yield_label=family.label)}."]
    for item, preview in sorted(usable.items()):
        parts = [f"{_title(context, item)}: {_n(preview.completion_turns)} turns to complete",
                 f"{_n(preview.yield_delta)} {family.unit}"]
        if preview.gold_upkeep is not None:
            parts.append(f"{_n(preview.gold_upkeep)} gold upkeep")
        if preview.happiness_cost is not None:
            parts.append(f"{_n(preview.happiness_cost)} local happiness")
        lines.append("; ".join(parts) + f" ({_source_note(preview)}).")

    ordered = sorted(usable.items(), key=lambda kv: kv[1].completion_turns)
    quickest, slowest = ordered[0], ordered[-1]
    if quickest[0] != slowest[0]:
        turn_gap = _n(slowest[1].completion_turns - quickest[1].completion_turns)
        yield_gap = _n(slowest[1].yield_delta - quickest[1].yield_delta)
        if slowest[1].yield_delta > quickest[1].yield_delta:
            lines.append(
                f"Opportunity cost: {_title(context, slowest[0])} eventually adds "
                f"{yield_gap} more {family.unit} than {_title(context, quickest[0])}, "
                f"but takes {turn_gap} turns longer to start paying anything.")
        else:
            lines.append(
                f"{_title(context, quickest[0])} is both quicker and no worse on "
                f"{family.label} among these figures.")

    upkeeps = {i: p.gold_upkeep for i, p in usable.items() if p.gold_upkeep is not None}
    if upkeeps and context.net_gold is not None and isinstance(context.net_gold.value, (int, float)):
        net = float(context.net_gold.value)
        if len(set(upkeeps.values())) == 1:
            cost = next(iter(upkeeps.values()))
            lines.append(
                f"Either option's stated {_n(cost)} gold upkeep would take your net gold "
                f"from {_n(net)} to {_n(net - cost)} per turn, all else equal — a scenario "
                "estimate from these figures, not a forecast of your income.")
        else:
            detail = "; ".join(
                f"{_title(context, i)} to {_n(net - c)}" for i, c in sorted(upkeeps.items()))
            lines.append(f"Upkeep would take your net gold from {_n(net)} per turn to {detail}, "
                         "all else equal — a scenario estimate, not a forecast.")

    lines.append("This follows from the figures above and the objective you stated. "
                 "It is not a claim about the best play available in the game.")
    return Comparison(winner, objective, tuple(lines), incomplete)


def _source_note(preview: Previews) -> str:
    """Which source each preview's figures came from, honestly. A ruleset figure is a
    fact about the installed game; a player's own reading is a dated observation of one
    settlement. Saying "your figures" about a number the player never typed would record
    one source as the other -- the exact confusion this project's provenance labelling
    exists to prevent."""
    if not preview.ruleset_filled:
        return f"your figures, read on turn {preview.observed_turn}"
    if preview.observed_turn is None:
        return "your installed ruleset"
    return f"your installed ruleset and your own figures, read on turn {preview.observed_turn}"


def decide(context: DecisionContext, family: Family) -> DecisionCard | None:
    """This family's decision for this context, or None when there is nothing to decide."""
    comparison_fact = context.comparisons.get(family.stat)
    if comparison_fact is None:
        return None
    ratio = float(comparison_fact.value) if comparison_fact.value is not None else None
    target = _target_settlement(context)

    if target is None:
        # Not one human settlement has a logged queue. There is nothing to name, and
        # guessing a settlement would be worse than saying so.
        if ratio is not None and ratio >= ON_PACE_RATIO:
            return None
        return _no_target_card(context, ratio, family)

    behind = ratio is not None and ratio < ON_PACE_RATIO
    queued = _queued_item(context, target, family)
    if not behind and queued is None:
        return None

    why_now = _why_now(context, target, ratio, queued, family)
    options = context.available_options(target.city)
    family_options = tuple(
        item for item in (options or ())
        if family.stat in context.catalog.yields_for_item(item)
    )
    objective = context.objective(target.city)
    comparison = compare(context, target.city, family_options, objective, family)

    preferred, alternatives, reason = _rank(
        context, target, why_now, family_options, comparison, options, queued, family)
    if preferred is None and not alternatives:
        return None

    severity = _severity(context, behind, queued is not None)
    unknowns = _unknowns(context, target, options, comparison, family)
    evidence_ids = tuple(dict.fromkeys(
        sum((c.evidence_ids for c in ((preferred,) if preferred else ()) + alternatives), ())
    ))
    return DecisionCard(
        id=f"decision.{family.stat}.{target.city}",
        subject=f"{family.label.capitalize()} in {target.name}", severity=severity,
        priority_reason=reason,
        insight_ids=tuple(i for i in context.insight_ids
                          if i.startswith((f"economy.behind.{family.stat}", "production."))),
        preferred=preferred, alternatives=alternatives, evidence_ids=evidence_ids,
        evidence_mode=context.evidence_mode,
        observed_turns=tuple(sorted({f.observed_turn for f in
                                     context.ledger.resolve(evidence_ids)
                                     if f.observed_turn is not None})),
        unknowns=unknowns, family=family.stat,
    )


# ---- ranking ---------------------------------------------------------------------

def _rank(context: DecisionContext, target, why_now: str, family_options: tuple[str, ...],
          comparison: Comparison, options: tuple[str, ...] | None, queued: str | None,
          family: Family) -> tuple[ActionCandidate | None,
                                   tuple[ActionCandidate, ...], str]:
    built: list[ActionCandidate] = []
    reason: str

    if comparison.winner is not None:
        # The player supplied the options and their previews, and stated an objective.
        # This is the only situation in which a specific building can be named.
        chosen = candidates.named_build(
            context, target.city, target.name, comparison.winner, why_now,
            context.previews(target.city, comparison.winner, stat=family.stat), family.mechanic_key,
            trade_offs=comparison.lines)
        if chosen is not None:
            built.append(chosen)
        for item in sorted(set(family_options) - {comparison.winner}):
            other = candidates.named_build(
                context, target.city, target.name, item, why_now,
                context.previews(target.city, item, stat=family.stat), family.mechanic_key,
                trade_offs=comparison.lines)
            if other is not None:
                built.append(other)
        objective_text = OBJECTIVES[comparison.objective].format(yield_label=family.label)
        # "figures are available for both" rather than "you supplied their previews": a
        # figure here may be the player's own reading or one read from their installed
        # ruleset (Civ VI only) -- see `_source_note`, which states which for each line
        # above. This sentence must not claim the player typed what the ruleset filled.
        reason = (f"You confirmed both options are offered in {target.name}, figures are "
                  f"available for both, and you stated {objective_text}; "
                  "that objective and the shorter completion estimate decide it.")
    elif family_options:
        # Options confirmed, but not enough preview figures to compare them. Ask for
        # exactly what is missing rather than choosing on a partial reading.
        for item in sorted(family_options):
            candidate = candidates.named_build(
                context, target.city, target.name, item, why_now,
                context.previews(target.city, item, stat=family.stat), family.mechanic_key)
            if candidate is not None:
                built.append(candidate)
        inspection = candidates.inspect_options(
            context, target.city, target.name, why_now, family.mechanic_key, family.label)
        if inspection is not None:
            built.append(inspection)
        reason = (f"{len(family_options)} confirmed {family.label} option(s) in "
                  f"{target.name}, but the previews needed to choose between them are not "
                  "all supplied.")
    elif options == ():
        # The player looked and there were none. That makes the requirement the question,
        # and no build order is invented in the meantime.
        candidate = candidates.inspect_requirement(
            context, target.city, target.name, why_now, family.mechanic_key, family.stat,
            family.label)
        if candidate is not None:
            built.append(candidate)
        reason = (f"You reported no {family.label} option is offered in {target.name}, so "
                  "the requirement is what to look at, not the build.")
    else:
        inspection = candidates.inspect_options(
            context, target.city, target.name, why_now, family.mechanic_key, family.label)
        if inspection is not None:
            built.append(inspection)
        reason = ("Which options this settlement can build is not in any log, so the next "
                  "useful act is looking.")

    # The specialist alternative is only relevant where the reviewed catalog explains it.
    specialist = candidates.compare_specialist(context, target.city, target.name, why_now,
                                               family.label)
    if specialist is not None:
        built.append(specialist)

    if context.defense_is_urgent:
        reason = ("Deferred: a freshly recorded attack objective against your city tiles "
                  "outranks a yield decision this turn. " + reason)
    if not built:
        return None, (), reason
    return built[0], tuple(built[1:]), reason


def _severity(context: DecisionContext, behind: bool, addressed: bool) -> Severity:
    if context.defense_is_urgent:
        # Present, but never at a severity that competes with the defensive alert.
        return Severity.INFO
    if addressed:
        return Severity.INFO
    return Severity.ADVISE if behind else Severity.INFO


def _why_now(context: DecisionContext, target, ratio: float | None,
             queued: str | None, family: Family) -> str:
    parts = []
    if ratio is not None:
        comparison = context.comparisons[family.stat]
        parts.append(f"On turn {comparison.observed_turn} your {family.label} is "
                     f"{ratio:.0%} of the observed rival median.")
    if queued is not None:
        parts.append(f"{target.name} is already building "
                     f"{_title(context, queued)}, so the gap is being addressed; "
                     "this is the timing, not a second thing to queue.")
    elif target.idle:
        parts.append(f"{target.name}'s queue was logged empty on turn "
                     f"{target.observed_turn}, so its next choice is unspent.")
    elif target.turns_to_complete == 0:
        parts.append(f"{target.name} finishes {_title(context, target.item)} this turn at "
                     f"the logged rate, which makes its next choice worth deciding now.")
    elif target.turns_to_complete is not None:
        parts.append(f"{target.name} has about {target.turns_to_complete} turn"
                     f"{'' if target.turns_to_complete == 1 else 's'} left on "
                     f"{_title(context, target.item)} at the logged rate.")
    if context.defense_is_urgent and context.defense_titles:
        parts.append("Check the defensive alert first: " + context.defense_titles[0] + ".")
    return " ".join(parts)


def _unknowns(context: DecisionContext, target, options: tuple[str, ...] | None,
              comparison: Comparison, family: Family) -> tuple[str, ...]:
    out = []
    if options is None:
        out.append(f"Which options {target.name} is offered — no log records availability.")
    if comparison.incomplete:
        out.append("Preview figures still missing: " + "; ".join(comparison.incomplete) + ".")
    if context.unobserved_settlements:
        count = context.unobserved_settlements
        out.append(f"{count} of your settlements {'has' if count == 1 else 'have'} no logged "
                   f"queue; {'its' if count == 1 else 'their'} production is unknown, not idle.")
    if context.age is not None:
        out.append(f"The Age was recorded as {context.age.value} on turn "
                   f"{context.age.observed_turn}; no log states the current Age, so nothing "
                   "Age-gated is treated as established.")
    else:
        out.append("No Age has been observed, so nothing Age-gated is treated as established.")
    if context.net_gold is None:
        out.append("Net gold per turn is unknown: no maintenance was recorded, and a "
                   "balance alone is not affordability.")
    if context.happiness is None:
        out.append("Happiness was not recorded this turn.")
    else:
        out.append("Local happiness room in this settlement is unknown; the empire total "
                   "cannot stand in for it.")
    return tuple(out)


# ---- target selection ------------------------------------------------------------

def _target_settlement(context: DecisionContext):
    """Which settlement this decision is about.

    Preference order: an idle logged queue, then the one finishing soonest. Only logged
    settlements are eligible — an unobserved settlement cannot be named, and the card's
    unknowns say how many were left out.
    """
    if not context.settlements:
        return None
    idle = [s for s in context.settlements if s.idle]
    if idle:
        return sorted(idle, key=lambda s: (-s.observed_turn, s.city))[0]
    dated = [s for s in context.settlements if s.turns_to_complete is not None]
    if dated:
        return sorted(dated, key=lambda s: (s.turns_to_complete, s.city))[0]
    return sorted(context.settlements, key=lambda s: s.city)[0]


def _queued_item(context: DecisionContext, target, family: Family) -> str | None:
    """Whether this settlement is already building something documented as this yield."""
    if not target.item:
        return None
    documented = context.catalog.yields_for_item(target.item)
    return target.item if family.stat in documented else None


def _no_target_card(context: DecisionContext, ratio: float | None,
                    family: Family) -> DecisionCard:
    comparison = context.comparisons.get(family.stat)
    evidence = tuple(i for i in (
        comparison.id if comparison else None,
        context.coverage_fact_id,
    ) if i)
    return DecisionCard(
        id=f"decision.{family.stat}.unobserved",
        subject=family.label.capitalize(), severity=Severity.INFO,
        priority_reason=("No settlement of yours has a logged build queue, so there is no "
                         "settlement to name."),
        insight_ids=tuple(i for i in context.insight_ids
                          if i.startswith(f"economy.behind.{family.stat}")),
        evidence_ids=evidence, evidence_mode=context.evidence_mode, family=family.stat,
        observed_turns=tuple(sorted({f.observed_turn for f in context.ledger.resolve(evidence)
                                     if f.observed_turn is not None})),
        unknowns=(
            f"Your {family.label} is behind the observed field, but no settlement's "
            "production is recorded, so no queue can be inspected from here."
            if ratio is not None and ratio < ON_PACE_RATIO
            else "No settlement's production is recorded.",
        ),
    )


def _title(context: DecisionContext, item: str) -> str:
    entry = next(iter(context.catalog.for_item(item)), None)
    if entry is not None:
        return entry.title
    return item.removeprefix("BUILDING_").removeprefix("UNIT_").replace("_", " ").title()


def _n(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:g}" if value % 1 else f"{int(value)}"


def decide_all(context: DecisionContext) -> tuple[DecisionCard, ...]:
    """Every yield family's decision, with the near-duplicates folded together.

    A family that has nothing to decide returns nothing, and a family with no reviewed
    guide produces no candidate at all — so it never becomes a card with borrowed steps.

    Then the deduplication that matters for the brief: when several yields are behind in
    the *same* settlement and the answer to each is the same inspection, they become one
    card naming the worst gap and listing the others. Five cards reading "inspect this
    settlement's X options" would be five true statements that between them push a real
    alert out of view. A family whose gap is already being addressed by that settlement's
    queue keeps its own card, because its message is about timing rather than the gap.
    """
    behind: dict[str, list[tuple[Family, DecisionCard, float]]] = {}
    separate: list[DecisionCard] = []
    for family in FAMILIES.values():
        card = decide(context, family)
        if card is None:
            continue
        comparison = context.comparisons.get(family.stat)
        ratio = float(comparison.value) if comparison and comparison.value is not None else 1.0
        target = card.id.split(".", 2)[2] if card.id.count(".") >= 2 else ""
        if ratio >= ON_PACE_RATIO or _queued_for(context, target, family):
            separate.append(card)
        else:
            behind.setdefault(target, []).append((family, card, ratio))

    folded: list[DecisionCard] = []
    for group in behind.values():
        group.sort(key=lambda row: (row[2], row[0].stat))
        _, worst, _ = group[0]
        others = tuple((f.label, round(r, 4)) for f, _, r in group[1:])
        if others:
            listed = ", ".join(f"{label} at {ratio:.0%}" for label, ratio in others)
            worst = replace(
                worst,
                also_behind=others,
                priority_reason=(
                    worst.priority_reason
                    + f" {len(others)} other yield(s) trail the field in the same "
                      f"settlement ({listed}); the same inspection covers them, so they "
                      "are folded in here rather than repeated."),
            )
        folded.append(worst)
    return tuple(sorted(folded + separate, key=lambda c: (-c.severity, c.id)))


def _queued_for(context: DecisionContext, city: str, family: Family) -> bool:
    target = context.settlement(city)
    return target is not None and _queued_item(context, target, family) is not None


__all__ = ["FAMILIES", "Comparison", "Family", "ON_PACE_RATIO", "compare", "decide",
           "decide_all"]
