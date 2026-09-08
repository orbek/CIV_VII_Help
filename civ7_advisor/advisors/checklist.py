"""Merge advisor output into one ranked, de-duplicated to-do list."""
from __future__ import annotations

from .base import Insight

ADVISOR_ORDER = {"threat": 0, "tactical": 1, "victory": 2, "economy": 3, "production": 4}


def rank(insights: list[Insight]) -> list[Insight]:
    """Most severe first, then most recent, then threat > victory > economy > production, then id.
    Duplicate ids keep the first (i.e. most severe) occurrence."""
    ordered = sorted(
        insights,
        key=lambda i: (-int(i.severity), -i.turn, ADVISOR_ORDER.get(i.advisor, 99), i.id),
    )
    seen: set[str] = set()
    out: list[Insight] = []
    for insight in ordered:
        if insight.id in seen:
            continue
        seen.add(insight.id)
        out.append(insight)
    return out
