from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GeometryFixture:
    x: float
    y: float
    hdg: float
    length: float
    curvature: float | None = None


# --- Line fixtures ---
LINE_START: GeometryFixture = GeometryFixture(0.0, 0.0, 0.0, 100.0, 0.0)
LINE_NONZERO_ORIGIN: GeometryFixture = GeometryFixture(10.0, 20.0, 0.0, 50.0, 0.0)
LINE_ANGLED: GeometryFixture = GeometryFixture(0.0, 0.0, math.pi / 6, 100.0, 0.0)
LINE_NEGATIVE_HDG: GeometryFixture = GeometryFixture(0.0, 0.0, -0.5, 80.0, 0.0)
LINE_BACKWARD: GeometryFixture = GeometryFixture(5.0, 5.0, math.pi, 30.0, 0.0)

# --- Arc fixtures ---
ARC_QUARTER_CIRCLE_LEFT: GeometryFixture = GeometryFixture(
    0.0, 0.0, 0.0, math.pi / 2 * 10.0, 0.1
)
ARC_QUARTER_CIRCLE_RIGHT: GeometryFixture = GeometryFixture(
    0.0, 0.0, 0.0, math.pi / 2 * 10.0, -0.1
)
ARC_HALF_CIRCLE_LEFT: GeometryFixture = GeometryFixture(
    0.0, 0.0, 0.0, math.pi * 5.0, 0.2
)
ARC_GENTLE_LEFT: GeometryFixture = GeometryFixture(0.0, 0.0, 0.0, 100.0, 0.005)
ARC_GENTLE_RIGHT: GeometryFixture = GeometryFixture(0.0, 0.0, 0.0, 100.0, -0.005)
ARC_NONZERO_ORIGIN: GeometryFixture = GeometryFixture(50.0, -30.0, 0.5, 60.0, 0.02)
ARC_NONZERO_HDG: GeometryFixture = GeometryFixture(0.0, 0.0, math.pi / 3, 80.0, 0.03)
ARC_TIGHT: GeometryFixture = GeometryFixture(100.0, 200.0, 1.0, 30.0, 0.05)

# --- Edge-case fixtures ---
ARC_NEAR_ZERO_POS: GeometryFixture = GeometryFixture(0.0, 0.0, 0.0, 100.0, 1e-10)
ARC_NEAR_ZERO_NEG: GeometryFixture = GeometryFixture(0.0, 0.0, 0.0, 100.0, -1e-10)
ARC_AT_EPS_BOUNDARY: GeometryFixture = GeometryFixture(0.0, 0.0, 0.0, 100.0, 1e-12)
ARC_EXACT_ZERO: GeometryFixture = GeometryFixture(0.0, 0.0, 0.0, 100.0, 0.0)


def make_fixture(
    x: float = 0.0,
    y: float = 0.0,
    hdg: float = 0.0,
    length: float = 100.0,
    curvature: float | None = None,
) -> GeometryFixture:
    return GeometryFixture(x=x, y=y, hdg=hdg, length=length, curvature=curvature)
