"""How your economy compares to the field, and which lever to pull."""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from civ_advisor.state.models import GameState

from .base import Insight, Provenance, Severity

BEHIND_RATIO = 0.75     # human / rival median below this is flagged
FAR_BEHIND_RATIO = 0.5  # below this the worst stat is WARN instead of ADVISE
CELEBRATION_NEAR = 0.9  # happiness total / threshold at/above which a celebration is "imminent"

# PlayerTurn attribute -> (label, the Civ VII lever to pull)
YIELDS: dict[str, tuple[str, str]] = {
    "science": ("science", "Use the detailed city preview to compare science base yields, placement, "
                           "adjacency, specialists, and maintenance before choosing the next build."),
    "culture": ("culture", "Use the detailed city preview to compare culture from buildings, wonders, "
                           "adjacency, specialists, and the opportunity cost of overbuilding."),
    "gold": ("gold", "Inspect the yield and maintenance breakdown, then choose the route, building, "
                     "improvement, or specialist with the best current net-gold gain."),
    "production": ("production", "Compare production improvements, buildings, adjacency, and town "
                                 "specializations in the current settlement preview."),
    "food": ("food", "Compare food improvements and specialists in the growth preview; choose the option "
                     "whose before-and-after yields support this settlement's role."),
}


@dataclass(frozen=True)
class YieldComparison:
    stat: str
    label: str
    human: float
    rival_median: float
    leader_name: str
    leader_value: float
    ratio: float  # human / rival median


def comparison(state: GameState) -> list[YieldComparison]:
    t = state.complete_through_turn
    human = state.at(state.HUMAN, t)
    rivals = [(r, state.at(r.id, t)) for r in state.rivals()]
    rivals = [(r, pt) for r, pt in rivals if pt is not None]
    if human is None or not rivals:
        return []
    out: list[YieldComparison] = []
    for attr, (label, _) in YIELDS.items():
        median = statistics.median(getattr(pt, attr) for _, pt in rivals)
        if median <= 0:
            continue
        leader, leader_value = max(((r, getattr(pt, attr)) for r, pt in rivals), key=lambda x: x[1])
        value = getattr(human, attr)
        out.append(YieldComparison(attr, label, value, median, leader.name, leader_value, value / median))
    return out


def behind(state: GameState) -> list[YieldComparison]:
    """Every yield the human trails the rival median on by more than BEHIND_RATIO, worst first."""
    return sorted((c for c in comparison(state) if c.ratio < BEHIND_RATIO), key=lambda c: c.ratio)


def advise(state: GameState) -> list[Insight]:
    t = state.complete_through_turn
    human = state.at(state.HUMAN, t)
    if human is None:
        return []
    out: list[Insight] = []
    common = dict(advisor="economy", turn=t)

    for index, c in enumerate(behind(state)):
        if index == 0:
            severity = Severity.WARN if c.ratio < FAR_BEHIND_RATIO else Severity.ADVISE
        else:
            severity = Severity.INFO
        out.append(Insight(
            id=f"economy.behind.{c.stat}", severity=severity, provenance=Provenance.FAIR,
            title=f"Your {c.label} is {'far ' if c.ratio < FAR_BEHIND_RATIO else ''}behind the field",
            recommendation=YIELDS[c.stat][1],
            why=f"Turn {t}: your {c.label} {c.human:.1f} vs rival median {c.rival_median:.1f} "
                f"({c.ratio:.0%}); leader {c.leader_name} at {c.leader_value:.1f}.",
            subject_player=state.HUMAN, **common,
        ))

    slack = human.settlement_cap - human.settlements
    if slack >= 1:
        out.append(Insight(
            id="economy.settlement_slack", severity=Severity.ADVISE, provenance=Provenance.FAIR,
            title="You have room to expand",
            recommendation="Consider a Settler only if you have a strong site and can absorb its happiness "
                           "and economic costs; cap room alone does not make expansion optimal.",
            why=f"Turn {t}: {slack} of {human.settlement_cap} settlement slots unused "
                f"({human.settlements} settlements).",
            subject_player=state.HUMAN, **common,
        ))
    if human.settlements_over_cap > 0:
        out.append(Insight(
            id="economy.over_cap", severity=Severity.WARN, provenance=Provenance.FAIR,
            title="You are over your settlement cap",
            recommendation="Stop settling and inspect the current happiness breakdown; raise the cap if an "
                           "available civic, attribute, or effect explicitly does so.",
            why=f"Turn {t}: {human.settlements_over_cap} settlement(s) over a cap of {human.settlement_cap}.",
            subject_player=state.HUMAN, **common,
        ))
    if human.net_gold is not None and human.net_gold < 0:
        out.append(Insight(
            id="economy.negative_gold", severity=Severity.WARN, provenance=Provenance.FAIR,
            title="You are losing gold every turn",
            recommendation="Inspect the gold and maintenance breakdown, then cut the least valuable upkeep "
                           "or choose the available option with the best verified net-gold gain.",
            why=f"Turn {t}: gold yield {human.gold:.1f} minus maintenance {human.total_maintenance} "
                f"= {human.net_gold:+.1f} per turn (balance {human.gold_balance:.0f}).",
            subject_player=state.HUMAN, **common,
        ))

    progress = human.celebration_progress
    if progress is not None and progress >= CELEBRATION_NEAR:
        out.append(Insight(
            id="economy.celebration", severity=Severity.INFO, provenance=Provenance.FAIR,
            title="A celebration is imminent",
            recommendation="Review the celebration choices when it triggers and pick the effect that best "
                           "supports your current plan.",
            why=f"Turn {t}: happiness {human.happiness_total} of {human.happiness_threshold} ({progress:.0%}).",
            subject_player=state.HUMAN, **common,
        ))
    for rival in state.rivals():
        pt = state.at(rival.id, t)
        rp = pt.celebration_progress if pt else None
        if rp is not None and rp >= CELEBRATION_NEAR:
            out.append(Insight(
                id=f"economy.rival_celebration.{rival.id}", severity=Severity.INFO, provenance=Provenance.ORACLE,
                title=f"{rival.name} is about to celebrate",
                recommendation=f"Expect a temporary surge from {rival.name}; don't read their next few "
                               f"turns as their baseline.",
                why=f"Turn {t}: {rival.name}'s happiness {pt.happiness_total} of {pt.happiness_threshold} ({rp:.0%}).",
                subject_player=rival.id, **common,
            ))
    return out
