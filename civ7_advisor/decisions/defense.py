"""The defensive decision: what is threatening which frontier, and what to look at.

Oracle by construction. Every fact behind it comes from the AI's own planning logs, so
this card does not exist in fair mode — not with its sentences removed, but at all.

Two things it will not do. It will not read silence as safety: no recorded contact means
these logs recorded none, and the card says so whenever coverage is thin. And it will not
present a dated objective as an order in force; `advisors.tactical` has already separated
those, and the severity here follows that separation rather than the loudest available
label.
"""
from __future__ import annotations

from civ7_advisor.advisors import tactical
from civ7_advisor.advisors.base import Severity

from . import candidates
from .context import DecisionContext
from .models import DecisionCard


def decide(context: DecisionContext) -> DecisionCard | None:
    """The defensive decision for this context, or None when there is nothing to decide."""
    if context.evidence_mode != "oracle" or not context.defense_facts:
        return None
    goals = [g for g in tactical.attack_goals(context.state) if g["fresh"]]
    dated = [g for g in tactical.attack_goals(context.state) if not g["fresh"]]
    if not goals and not dated:
        return None

    target = _threatened_settlement(context)
    name = target.name if target is not None else "your frontier"
    why_now = _why_now(context, goals, dated)

    built = []
    if target is not None:
        reinforce = candidates.reinforce_settlement(context, target.city, target.name, why_now)
        if reinforce is not None:
            built.append(reinforce)
    exposed = candidates.withdraw_exposed_unit(context, name, why_now)
    if exposed is not None and _has_exposed_units(context):
        built.append(exposed)
    if not built:
        return None

    severity = Severity.CRITICAL if goals else Severity.ADVISE
    evidence = tuple(dict.fromkeys(
        sum((c.evidence_ids for c in built), ()) + tuple(f.id for f in context.defense_facts)
    ))
    return DecisionCard(
        id=f"decision.defense.{target.city if target is not None else 'frontier'}",
        subject=f"Defence of {name}", severity=severity,
        priority_reason=(
            "A freshly recorded attack objective against your city tiles outranks every "
            "yield decision this turn."
            if goals else
            "The last recorded objective against your city tiles is several turns old, so "
            "this is a frontier to re-inspect rather than an emergency — and no newer plan "
            "has been logged either way."),
        insight_ids=tuple(i for i in context.insight_ids if i.startswith("tactical.")),
        preferred=built[0], alternatives=tuple(built[1:]), evidence_ids=evidence,
        evidence_mode=context.evidence_mode,
        observed_turns=tuple(sorted({f.observed_turn for f in
                                     context.ledger.resolve(evidence)
                                     if f.observed_turn is not None})),
        unknowns=_unknowns(context),
    )


def _threatened_settlement(context: DecisionContext):
    """The logged settlement nearest a recorded objective, or None.

    Only settlements with a logged queue are eligible, and the plots the AI targets are
    tiles rather than named settlements — so when nothing can be matched the card stays
    about the frontier rather than naming a settlement we guessed at.
    """
    if not context.settlements:
        return None
    if len(context.settlements) == 1:
        return context.settlements[0]
    # With several logged settlements and no way to tie a plot to one of them, naming any
    # would be a guess. The unknowns say so.
    return None


def _has_exposed_units(context: DecisionContext) -> bool:
    return any(i.startswith("tactical.own_exposed") for i in context.insight_ids)


def _why_now(context: DecisionContext, goals: list[dict], dated: list[dict]) -> str:
    parts = []
    if goals:
        observed = max(g["turn"] for g in goals)
        who = ", ".join(sorted({g["name"] for g in goals}))
        parts.append(f"Turn {observed}: {who} recorded an attack objective on tiles the AI "
                     "classifies as yours.")
    if dated:
        observed = max(g["turn"] for g in dated)
        age = context.analysis_turn - observed
        who = ", ".join(sorted({g["name"] for g in dated}))
        parts.append(f"{who}'s last recorded objective was turn {observed}, "
                     f"{age} turn{'' if age == 1 else 's'} ago, and nothing newer has been "
                     "logged either way.")
    coverage = context.ledger.get(f"defense.coverage.{context.analysis_turn}")
    if coverage is not None and coverage.value == 0:
        parts.append("No rival position was recorded near you at all this turn, which is a "
                     "gap in these logs rather than a quiet frontier.")
    return " ".join(parts)


def _unknowns(context: DecisionContext) -> tuple[str, ...]:
    out = ["No log records a settlement's garrison, its walls, or what it can build to "
           "defend itself.",
           "These are the AI's own plans, not what you can see in game; a plan can be "
           "abandoned without anything being logged."]
    if len(context.settlements) > 1:
        out.append("The AI targets plots rather than named settlements, so which of your "
                   "settlements is meant cannot be established from the logs.")
    if context.unobserved_settlements:
        out.append(f"{context.unobserved_settlements} of your settlements have no logged "
                   "queue, so their defensive production is unknown.")
    odds = [i for i in context.insight_ids if i.startswith("tactical.odds.")]
    if odds:
        out.append("The attack estimate shown with this is the AI's own confidence "
                   "reading, not a combat probability.")
    return tuple(out)


__all__ = ["decide"]
