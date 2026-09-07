"""Advisors turn a GameState into ranked Insights. Each module exposes advise(state)."""
from __future__ import annotations

from civ7_advisor.state.models import GameState

from . import checklist, economy, threat, victory
from .base import Insight, Provenance, Severity

ADVISORS = (threat, victory, economy)

__all__ = ["ADVISORS", "Insight", "Provenance", "Severity", "economy", "run_all", "threat", "victory"]


def run_all(state: GameState) -> list[Insight]:
    insights: list[Insight] = []
    for module in ADVISORS:
        insights.extend(module.advise(state))
    return checklist.rank(insights)
