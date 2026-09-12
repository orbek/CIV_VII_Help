"""Geometry for Civ VII's odd-row offset plot coordinates."""
from __future__ import annotations

from math import sqrt

Hex = tuple[int, int]


def hex_distance(a: Hex, b: Hex) -> int:
    """Convert the observed odd-r offset coordinates to axial, then measure."""
    aq, ar = offset_to_axial(a)
    bq, br = offset_to_axial(b)
    dq, dr = aq - bq, ar - br
    return max(abs(dq), abs(dr), abs(dq + dr))


def offset_to_axial(plot: Hex) -> Hex:
    """Odd rows are shifted right: (column, row) -> axial (q, r)."""
    column, row = plot
    return column - (row - (row & 1)) // 2, row


def svg_point(plot: Hex, size: float = 24.0) -> tuple[float, float]:
    """Project odd-r coordinates to pointy-top SVG coordinates."""
    q, r = offset_to_axial(plot)
    return size * sqrt(3) * (q + r / 2), size * 1.5 * r
