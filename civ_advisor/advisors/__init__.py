"""Advisors turn a GameState into ranked Insights. Each module exposes advise(state)."""
from __future__ import annotations

from civ_advisor.games.base import GameProfile
from civ_advisor.state.models import GameState

from . import checklist, economy, intel, production, tactical, threat, victory
from .base import Insight, Provenance, Severity

ADVISORS = (threat, tactical, victory, economy, production)

# intel is exported but deliberately absent from ADVISORS: it is a feed, not an advisor.
__all__ = ["ADVISORS", "Insight", "Provenance", "Severity", "economy", "intel", "production",
           "run_all", "tactical", "threat", "victory"]


def run_all(state: GameState, profile: GameProfile | None = None) -> list[Insight]:
    """`profile` is only production's concern (its item-yield catalog is per game); every
    other advisor takes the state alone. `None` keeps every caller that predates a second
    game on Civ VII's own catalog, which is what `production.advise`'s own default does."""
    insights: list[Insight] = []
    for module in ADVISORS:
        if module is production and profile is not None:
            insights.extend(module.advise(state, profile.knowledge_package))
        else:
            insights.extend(module.advise(state))
    return checklist.rank(insights)
