"""Geometry for Civ VII's skewed axial plot coordinates."""
from __future__ import annotations

from math import sqrt

Hex = tuple[int, int]


def hex_distance(a: Hex, b: Hex) -> int:
    """Distance on the observed q/r axes (q+r is the implicit third cube axis)."""
    dq, dr = a[0] - b[0], a[1] - b[1]
    return max(abs(dq), abs(dr), abs(dq + dr))


def svg_point(plot: Hex, size: float = 24.0) -> tuple[float, float]:
    """Project the skewed axes to pointy-top SVG coordinates."""
    q, r = plot
    return size * sqrt(3) * (q + r / 2), size * 1.5 * r
