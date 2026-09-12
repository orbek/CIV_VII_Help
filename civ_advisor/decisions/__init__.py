"""Structured decisions: evidence, action candidates and the cards the UI renders.

Advisors produce ranked `Insight`s. This package turns those into decisions that can be
acted on: each one names a target, a next step, the observations it rests on and the
reviewed guide that explains how to do it in game. Nothing here invents a number, a
prerequisite or a URL — every claim resolves to an `EvidenceFact` or a `GuideEntry`.

A family the reviewed catalog does not cover produces no card at all rather than one with
borrowed steps, so its observations stay in the grouped insight stream where they can be
read without being dressed up as instructions.
"""
from __future__ import annotations

from .context import DecisionContext
from .models import DecisionCard


def decide_all(context: DecisionContext) -> tuple[DecisionCard, ...]:
    """Every decision this context supports, most severe first.

    Defence leads when it is live: a freshly recorded attack objective is not something to
    weigh against a yield gap. Below that, the worst-behind yield comes first.
    """
    from . import defense, yields

    cards = list(yields.decide_all(context))
    defensive = defense.decide(context)
    if defensive is not None:
        cards.insert(0, defensive)
    return tuple(sorted(cards, key=lambda c: -c.severity))


__all__ = ["DecisionCard", "DecisionContext", "decide_all"]
