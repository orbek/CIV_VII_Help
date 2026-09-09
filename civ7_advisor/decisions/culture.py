"""The culture pilot's view of the general yield decision.

Culture is the family the first release worked through end to end, and the only one the
reviewed catalog documents specific buildings for, so it is the only one that can reach a
named-build comparison. This module is that family bound into the generic implementation
in `yields.py` — it exists so the pilot has a name, not because culture is special-cased.
"""
from __future__ import annotations

from .context import DecisionContext
from .models import DecisionCard
from .yields import FAMILIES, Comparison

FAMILY = FAMILIES["culture"]


def decide(context: DecisionContext) -> DecisionCard | None:
    from .yields import decide as decide_family
    return decide_family(context, FAMILY)


def compare(context: DecisionContext, city: str, items: tuple[str, ...],
            objective: str | None) -> Comparison:
    from .yields import compare as compare_family
    return compare_family(context, city, items, objective, FAMILY)


__all__ = ["FAMILY", "compare", "decide"]
