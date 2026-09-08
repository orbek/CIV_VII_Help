"""Advisors turn a GameState into ranked Insights. Each module exposes advise(state)."""
from __future__ import annotations

from civ7_advisor.state.models import GameState

from . import checklist, economy, intel, production, threat, victory
from .base import Insight, Provenance, Severity

ADVISORS = (threat, victory, economy, production)

# intel is exported but deliberately absent from ADVISORS: it is a feed, not an advisor.
__all__ = ["ADVISORS", "Insight", "Provenance", "Severity", "economy", "intel", "production",
           "run_all", "threat", "victory"]


def run_all(state: GameState) -> list[Insight]:
    insights: list[Insight] = []
    for module in ADVISORS:
        insights.extend(module.advise(state))
    return checklist.rank(insights)
