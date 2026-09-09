"""The culture decision: which settlement, which next act, and why now.

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

from dataclasses import dataclass

from civ7_advisor.advisors.base import Severity

from . import candidates
from .context import LARGEST, OBJECTIVES, SOONEST, DecisionContext, Previews
from .models import ActionCandidate, Applicability, DecisionCard

# The culture ratio at or above which the gap is not worth a decision of its own.
ON_PACE_RATIO = 1.0


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
            objective: str | None) -> Comparison:
    """Rank supplied culture options against the stated objective.

    With no objective there is no winner: the two candidates answer different questions
    and picking one would be asserting a goal the player never stated.
    """
    previews = {item: context.previews(city, item) for item in items}
    incomplete = tuple(
        f"{item}: {', '.join(p.missing('completion_turns', 'culture_delta'))}"
        for item, p in previews.items()
        if p.missing("completion_turns", "culture_delta")
    )
    usable = {i: p for i, p in previews.items() if not p.missing("completion_turns", "culture_delta")}
    if len(usable) < 2 or objective is None:
        return Comparison(None, objective, (), incomplete)

    if objective == SOONEST:
        winner = min(usable, key=lambda i: (usable[i].completion_turns, -usable[i].culture_delta))
    elif objective == LARGEST:
        winner = max(usable, key=lambda i: (usable[i].culture_delta, -usable[i].completion_turns))
    else:
        return Comparison(None, objective, (), incomplete)

    lines = [f"Your stated objective is {OBJECTIVES[objective]}."]
    for item, preview in sorted(usable.items()):
        parts = [f"{_title(context, item)}: {_n(preview.completion_turns)} turns to complete",
                 f"{_n(preview.culture_delta)} culture per turn"]
        if preview.gold_upkeep is not None:
            parts.append(f"{_n(preview.gold_upkeep)} gold upkeep")
        if preview.happiness_cost is not None:
            parts.append(f"{_n(preview.happiness_cost)} local happiness")
        lines.append("; ".join(parts) + f" (your figures, read on turn {preview.observed_turn}).")

    ordered = sorted(usable.items(), key=lambda kv: kv[1].completion_turns)
    quickest, slowest = ordered[0], ordered[-1]
    if quickest[0] != slowest[0]:
        turn_gap = _n(slowest[1].completion_turns - quickest[1].completion_turns)
        culture_gap = _n(slowest[1].culture_delta - quickest[1].culture_delta)
        if slowest[1].culture_delta > quickest[1].culture_delta:
            lines.append(
                f"Opportunity cost: {_title(context, slowest[0])} eventually adds "
                f"{culture_gap} more culture per turn than {_title(context, quickest[0])}, "
                f"but takes {turn_gap} turns longer to start paying anything.")
        else:
            lines.append(
                f"{_title(context, quickest[0])} is both quicker and no worse on culture "
                "among the figures you supplied.")

    upkeeps = {i: p.gold_upkeep for i, p in usable.items() if p.gold_upkeep is not None}
    if upkeeps and context.net_gold is not None and isinstance(context.net_gold.value, (int, float)):
        net = float(context.net_gold.value)
        if len(set(upkeeps.values())) == 1:
            cost = next(iter(upkeeps.values()))
            lines.append(
                f"Either option's reported {_n(cost)} gold upkeep would take your net gold "
                f"from {_n(net)} to {_n(net - cost)} per turn, all else equal — a scenario "
                "estimate from these figures, not a forecast of your income.")
        else:
            detail = "; ".join(
                f"{_title(context, i)} to {_n(net - c)}" for i, c in sorted(upkeeps.items()))
            lines.append(f"Upkeep would take your net gold from {_n(net)} per turn to {detail}, "
                         "all else equal — a scenario estimate, not a forecast.")

    lines.append("This follows from the figures you supplied and the objective you stated. "
                 "It is not a claim about the best play available in the game.")
    return Comparison(winner, objective, tuple(lines), incomplete)


def decide(context: DecisionContext) -> DecisionCard | None:
    """The culture decision for this context, or None when there is nothing to decide."""
    comparison_fact = context.culture_comparison
    if comparison_fact is None:
        return None
    ratio = float(comparison_fact.value) if comparison_fact.value is not None else None
    target = _target_settlement(context)

    if target is None:
        # Not one human settlement has a logged queue. There is nothing to name, and
        # guessing a settlement would be worse than saying so.
        if ratio is not None and ratio >= ON_PACE_RATIO:
            return None
        return _no_target_card(context, ratio)

    behind = ratio is not None and ratio < ON_PACE_RATIO
    queued_culture = _queued_culture_item(context, target)
    if not behind and queued_culture is None:
        return None

    why_now = _why_now(context, target, ratio, queued_culture)
    options = context.available_options(target.city)
    culture_options = tuple(
        item for item in (options or ())
        if "culture" in context.catalog.yields_for_item(item)
    )
    objective = context.objective(target.city)
    comparison = compare(context, target.city, culture_options, objective)

    preferred, alternatives, reason = _rank(
        context, target, why_now, culture_options, comparison, options, queued_culture)
    if preferred is None and not alternatives:
        return None

    severity = _severity(context, behind, queued_culture is not None)
    unknowns = _unknowns(context, target, options, comparison)
    evidence_ids = tuple(dict.fromkeys(
        sum((c.evidence_ids for c in ((preferred,) if preferred else ()) + alternatives), ())
    ))
    return DecisionCard(
        id=f"decision.culture.{target.city}",
        subject=f"Culture in {target.name}", severity=severity,
        priority_reason=reason,
        insight_ids=tuple(i for i in context.insight_ids
                          if i.startswith(("economy.behind.culture", "production."))),
        preferred=preferred, alternatives=alternatives, evidence_ids=evidence_ids,
        evidence_mode=context.evidence_mode,
        observed_turns=tuple(sorted({f.observed_turn for f in
                                     context.ledger.resolve(evidence_ids)
                                     if f.observed_turn is not None})),
        unknowns=unknowns,
    )


# ---- ranking ---------------------------------------------------------------------

def _rank(context: DecisionContext, target, why_now: str, culture_options: tuple[str, ...],
          comparison: Comparison, options: tuple[str, ...] | None,
          queued_culture: str | None) -> tuple[ActionCandidate | None,
                                               tuple[ActionCandidate, ...], str]:
    built: list[ActionCandidate] = []
    reason: str

    if comparison.winner is not None:
        # The player supplied the options and their previews, and stated an objective.
        # This is the only situation in which a specific building can be named.
        chosen = candidates.named_culture_build(
            context, target.city, target.name, comparison.winner, why_now,
            context.previews(target.city, comparison.winner),
            trade_offs=comparison.lines)
        if chosen is not None:
            built.append(chosen)
        for item in sorted(set(culture_options) - {comparison.winner}):
            other = candidates.named_culture_build(
                context, target.city, target.name, item, why_now,
                context.previews(target.city, item), trade_offs=comparison.lines)
            if other is not None:
                built.append(other)
        reason = (f"You confirmed both options are offered in {target.name} and supplied "
                  f"their previews, and you stated {OBJECTIVES[comparison.objective]}; "
                  "that objective and the shorter completion estimate decide it.")
    elif culture_options:
        # Options confirmed, but not enough preview figures to compare them. Ask for
        # exactly what is missing rather than choosing on a partial reading.
        for item in sorted(culture_options):
            candidate = candidates.named_culture_build(
                context, target.city, target.name, item, why_now,
                context.previews(target.city, item))
            if candidate is not None:
                built.append(candidate)
        inspection = candidates.inspect_culture_options(
            context, target.city, target.name, why_now)
        if inspection is not None:
            built.append(inspection)
        reason = (f"{len(culture_options)} confirmed culture option(s) in {target.name}, but "
                  "the previews needed to choose between them are not all supplied.")
    elif options == ():
        # The player looked and there were none. That makes the requirement the question,
        # and no build order is invented in the meantime.
        candidate = candidates.inspect_culture_requirement(
            context, target.city, target.name, why_now)
        if candidate is not None:
            built.append(candidate)
        reason = (f"You reported no culture option is offered in {target.name}, so the "
                  "requirement is what to look at, not the build.")
    else:
        inspection = candidates.inspect_culture_options(
            context, target.city, target.name, why_now)
        if inspection is not None:
            built.append(inspection)
        reason = ("Which options this settlement can build is not in any log, so the next "
                  "useful act is looking.")

    specialist = candidates.compare_specialist(context, target.city, target.name, why_now)
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
             queued_culture: str | None) -> str:
    parts = []
    if ratio is not None:
        comparison = context.culture_comparison
        parts.append(f"On turn {comparison.observed_turn} your culture is "
                     f"{ratio:.0%} of the observed rival median.")
    if queued_culture is not None:
        parts.append(f"{target.name} is already building "
                     f"{_title(context, queued_culture)}, so the gap is being addressed; "
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
              comparison: Comparison) -> tuple[str, ...]:
    out = []
    if options is None:
        out.append(f"Which options {target.name} is offered — no log records availability.")
    if comparison.incomplete:
        out.append("Preview figures still missing: " + "; ".join(comparison.incomplete) + ".")
    if context.unobserved_settlements:
        out.append(f"{context.unobserved_settlements} of your settlements have no logged "
                   "queue; their production is unknown, not idle.")
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


def _queued_culture_item(context: DecisionContext, target) -> str | None:
    """Whether this settlement is already building something documented as culture."""
    if not target.item:
        return None
    return target.item if "culture" in context.catalog.yields_for_item(target.item) else None


def _no_target_card(context: DecisionContext, ratio: float | None) -> DecisionCard:
    evidence = tuple(i for i in (
        context.culture_comparison.id if context.culture_comparison else None,
        context.coverage_fact_id,
    ) if i)
    return DecisionCard(
        id="decision.culture.unobserved", subject="Culture", severity=Severity.INFO,
        priority_reason=("No settlement of yours has a logged build queue, so there is no "
                         "settlement to name."),
        insight_ids=tuple(i for i in context.insight_ids if i.startswith("economy.behind.culture")),
        evidence_ids=evidence, evidence_mode=context.evidence_mode,
        observed_turns=tuple(sorted({f.observed_turn for f in context.ledger.resolve(evidence)
                                     if f.observed_turn is not None})),
        unknowns=(
            "Your culture is behind the observed field, but no settlement's production is "
            "recorded, so no queue can be inspected from here."
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


__all__ = ["Comparison", "ON_PACE_RATIO", "compare", "decide"]
