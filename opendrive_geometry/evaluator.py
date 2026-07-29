from __future__ import annotations
import math
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Sequence

from opendrive_geometry.model import Pose2D, Bounds2D, ProjectionResult, GeometrySegment, Vec2
from opendrive_geometry.primitives import (
    evaluate_line,
    evaluate_arc,
    sample_line,
    sample_arc,
    line_bounds,
    arc_bounds,
    curvature_line,
    curvature_arc,
    evaluate_param_poly3,
    sample_param_poly3,
    param_poly3_endpoint,
    param_poly3_curvature_at,
    param_poly3_bounds,
    VALID_P_RANGES,
)
from opendrive_geometry.errors import InvalidEvaluationRangeError, UnsupportedGeometryError


class RangePolicy(Enum):
    STRICT = "strict"
    CLAMP = "clamp"
    EXTRAPOLATE = "extrapolate"


@dataclass(frozen=True)
class EvaluationPolicy:
    range_policy: RangePolicy = RangePolicy.STRICT
    arc_linearization_epsilon: float = 1e-12
    include_endpoint: bool = True


class ReferenceLineEvaluator(Protocol):
    def pose_at(self, segment: GeometrySegment, s: float) -> Pose2D:
        ...

    def curvature_at(self, segment: GeometrySegment, s: float) -> float:
        ...

    def sample(
        self, segment: GeometrySegment, spacing_m: float
    ) -> Sequence[Pose2D]:
        ...

    def bounds(self, segment: GeometrySegment) -> Bounds2D:
        ...

    def project(
        self, segment: GeometrySegment, point: Pose2D
    ) -> ProjectionResult:
        ...


def _apply_range_policy(s: float, length: float, policy: RangePolicy) -> float:
    if not math.isfinite(s):
        raise InvalidEvaluationRangeError(s, 0.0, length)
    if policy == RangePolicy.STRICT:
        if s < -1e-12 or s > length + 1e-12:
            raise InvalidEvaluationRangeError(s, 0.0, length)
        return max(0.0, min(s, length))
    if policy == RangePolicy.CLAMP:
        return max(0.0, min(s, length))
    return s


class LineArcEvaluator:
    def __init__(self, policy: EvaluationPolicy | None = None):
        self.policy = policy or EvaluationPolicy()

    def pose_at(
        self,
        segment: GeometrySegment,
        s: float,
        curvature: float = 0.0,
    ) -> Pose2D:
        length = segment.length
        s_local = _apply_range_policy(s, length, self.policy.range_policy)
        if segment.geometry_type == "line":
            return evaluate_line(segment.x0, segment.y0, segment.hdg0, length, s_local)
        if segment.geometry_type == "arc":
            return evaluate_arc(segment.x0, segment.y0, segment.hdg0, length, curvature, s_local)
        raise UnsupportedGeometryError(segment.geometry_type)

    def curvature_at(
        self,
        segment: GeometrySegment,
        s: float,
        curvature: float = 0.0,
    ) -> float:
        _apply_range_policy(s, segment.length, self.policy.range_policy)
        if segment.geometry_type == "line":
            return curvature_line()
        if segment.geometry_type == "arc":
            return curvature_arc(curvature)
        raise UnsupportedGeometryError(segment.geometry_type)

    def endpoint(
        self,
        segment: GeometrySegment,
        curvature: float = 0.0,
    ) -> Pose2D:
        return self.pose_at(segment, segment.length, curvature)

    def sample(
        self,
        segment: GeometrySegment,
        spacing_m: float,
        curvature: float = 0.0,
    ) -> Sequence[Pose2D]:
        if segment.geometry_type == "line":
            return sample_line(segment.x0, segment.y0, segment.hdg0, segment.length, spacing_m)
        if segment.geometry_type == "arc":
            return sample_arc(segment.x0, segment.y0, segment.hdg0, segment.length, curvature, spacing_m)
        raise UnsupportedGeometryError(segment.geometry_type)

    def bounds(
        self,
        segment: GeometrySegment,
        curvature: float = 0.0,
    ) -> Bounds2D:
        if segment.geometry_type == "line":
            return line_bounds(segment.x0, segment.y0, segment.hdg0, segment.length)
        if segment.geometry_type == "arc":
            return arc_bounds(segment.x0, segment.y0, segment.hdg0, segment.length, curvature)
        raise UnsupportedGeometryError(segment.geometry_type)


class ParamPoly3Evaluator:
    def __init__(self, policy: EvaluationPolicy | None = None):
        self.policy = policy or EvaluationPolicy()

    def pose_at(
        self,
        segment: GeometrySegment,
        s: float,
        aU: float = 0.0, bU: float = 0.0, cU: float = 0.0, dU: float = 0.0,
        aV: float = 0.0, bV: float = 0.0, cV: float = 0.0, dV: float = 0.0,
        p_range: str | None = None,
    ) -> Pose2D:
        s_local = _apply_range_policy(s, segment.length, self.policy.range_policy)
        return evaluate_param_poly3(
            segment.x0, segment.y0, segment.hdg0, segment.length,
            aU, bU, cU, dU, aV, bV, cV, dV, p_range, s_local,
            allow_extrapolation=self.policy.range_policy == RangePolicy.EXTRAPOLATE,
        )

    def curvature_at(
        self,
        segment: GeometrySegment,
        s: float,
        aU: float = 0.0, bU: float = 0.0, cU: float = 0.0, dU: float = 0.0,
        aV: float = 0.0, bV: float = 0.0, cV: float = 0.0, dV: float = 0.0,
        p_range: str | None = None,
    ) -> float:
        s_local = _apply_range_policy(s, segment.length, self.policy.range_policy)
        return param_poly3_curvature_at(
            aU, bU, cU, dU, aV, bV, cV, dV,
            p_range, segment.length, s_local,
            allow_extrapolation=self.policy.range_policy == RangePolicy.EXTRAPOLATE,
        )

    def endpoint(
        self,
        segment: GeometrySegment,
        aU: float = 0.0, bU: float = 0.0, cU: float = 0.0, dU: float = 0.0,
        aV: float = 0.0, bV: float = 0.0, cV: float = 0.0, dV: float = 0.0,
        p_range: str | None = None,
    ) -> Pose2D:
        return self.pose_at(segment, segment.length, aU, bU, cU, dU, aV, bV, cV, dV, p_range)

    def sample(
        self,
        segment: GeometrySegment,
        spacing_m: float,
        aU: float = 0.0, bU: float = 0.0, cU: float = 0.0, dU: float = 0.0,
        aV: float = 0.0, bV: float = 0.0, cV: float = 0.0, dV: float = 0.0,
        p_range: str | None = None,
    ) -> Sequence[Pose2D]:
        return sample_param_poly3(
            segment.x0, segment.y0, segment.hdg0, segment.length,
            aU, bU, cU, dU, aV, bV, cV, dV, p_range, spacing_m,
        )

    def bounds(
        self,
        segment: GeometrySegment,
        aU: float = 0.0, bU: float = 0.0, cU: float = 0.0, dU: float = 0.0,
        aV: float = 0.0, bV: float = 0.0, cV: float = 0.0, dV: float = 0.0,
        p_range: str | None = None,
    ) -> Bounds2D:
        return param_poly3_bounds(
            segment.x0, segment.y0, segment.hdg0, segment.length,
            aU, bU, cU, dU, aV, bV, cV, dV, p_range,
        )
