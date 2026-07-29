from __future__ import annotations

import math
from dataclasses import dataclass

from tests.opendrive_geometry.fixtures import GeometryFixture


@dataclass(frozen=True)
class AnalyticalPose:
    x: float
    y: float
    hdg: float


def line_pose_at(fx: GeometryFixture, s: float) -> AnalyticalPose:
    if fx.curvature is not None and abs(fx.curvature) >= 1e-15:
        raise ValueError(f"line_pose_at called with nonzero curvature: {fx.curvature}")
    s_clamped = max(0.0, min(s, fx.length))
    return AnalyticalPose(
        x=fx.x + s_clamped * math.cos(fx.hdg),
        y=fx.y + s_clamped * math.sin(fx.hdg),
        hdg=fx.hdg,
    )


def line_curvature() -> float:
    return 0.0


def arc_pose_at(fx: GeometryFixture, s: float) -> AnalyticalPose:
    k = fx.curvature
    if k is None:
        raise ValueError("arc_pose_at requires curvature")
    s_clamped = max(0.0, min(s, fx.length))
    if abs(k) < 1e-15:
        return line_pose_at(fx, s_clamped)
    h = fx.hdg + k * s_clamped
    return AnalyticalPose(
        x=fx.x + (math.sin(h) - math.sin(fx.hdg)) / k,
        y=fx.y + (math.cos(fx.hdg) - math.cos(h)) / k,
        hdg=h,
    )


def arc_curvature(fx: GeometryFixture) -> float:
    if fx.curvature is None:
        raise ValueError("arc_curvature requires curvature")
    return fx.curvature
