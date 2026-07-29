from __future__ import annotations

import math

import pytest

from tests.opendrive_geometry.analytical import arc_pose_at, AnalyticalPose
from tests.opendrive_geometry.fixtures import (
    ARC_QUARTER_CIRCLE_LEFT,
    ARC_QUARTER_CIRCLE_RIGHT,
    ARC_HALF_CIRCLE_LEFT,
    ARC_GENTLE_LEFT,
    ARC_GENTLE_RIGHT,
    ARC_NONZERO_ORIGIN,
    ARC_NONZERO_HDG,
    ARC_TIGHT,
    ARC_NEAR_ZERO_POS,
    ARC_NEAR_ZERO_NEG,
    ARC_AT_EPS_BOUNDARY,
    ARC_EXACT_ZERO,
    make_fixture,
)


def _check_pose(actual: AnalyticalPose, expected: AnalyticalPose, tol: float = 1e-9):
    assert abs(actual.x - expected.x) < tol, f"x: {actual.x} != {expected.x}"
    assert abs(actual.y - expected.y) < tol, f"y: {actual.y} != {expected.y}"
    assert abs(actual.hdg - expected.hdg) < tol, f"hdg: {actual.hdg} != {expected.hdg}"


class TestArcQuarterCircle:
    def test_quarter_circle_left_start(self):
        p = arc_pose_at(ARC_QUARTER_CIRCLE_LEFT, 0.0)
        _check_pose(p, AnalyticalPose(0.0, 0.0, 0.0))

    def test_quarter_circle_left_end(self):
        p = arc_pose_at(ARC_QUARTER_CIRCLE_LEFT, ARC_QUARTER_CIRCLE_LEFT.length)
        _check_pose(p, AnalyticalPose(10.0, 10.0, math.pi / 2))

    def test_quarter_circle_left_mid(self):
        p = arc_pose_at(ARC_QUARTER_CIRCLE_LEFT, ARC_QUARTER_CIRCLE_LEFT.length / 2)
        R = 10.0
        _check_pose(p, AnalyticalPose(R * math.sin(math.pi / 4), R * (1 - math.cos(math.pi / 4)), math.pi / 4), tol=1e-8)

    def test_quarter_circle_right_start(self):
        p = arc_pose_at(ARC_QUARTER_CIRCLE_RIGHT, 0.0)
        _check_pose(p, AnalyticalPose(0.0, 0.0, 0.0))

    def test_quarter_circle_right_end(self):
        p = arc_pose_at(ARC_QUARTER_CIRCLE_RIGHT, ARC_QUARTER_CIRCLE_RIGHT.length)
        _check_pose(p, AnalyticalPose(10.0, -10.0, -math.pi / 2))


class TestArcHalfCircle:
    def test_half_circle_left_end(self):
        R = 5.0
        p = arc_pose_at(ARC_HALF_CIRCLE_LEFT, ARC_HALF_CIRCLE_LEFT.length)
        _check_pose(p, AnalyticalPose(0.0, 10.0, math.pi))

    def test_half_circle_left_mid(self):
        p = arc_pose_at(ARC_HALF_CIRCLE_LEFT, ARC_HALF_CIRCLE_LEFT.length / 2)
        R = 5.0
        _check_pose(p, AnalyticalPose(R, R, math.pi / 2), tol=1e-8)


class TestArcGentleCurves:
    def test_gentle_left_end(self):
        p = arc_pose_at(ARC_GENTLE_LEFT, ARC_GENTLE_LEFT.length)
        dx = math.sin(0.005 * 100.0) / 0.005
        dy = (1.0 - math.cos(0.005 * 100.0)) / 0.005
        _check_pose(p, AnalyticalPose(dx, dy, 0.5), tol=1e-8)

    def test_gentle_right_end(self):
        p = arc_pose_at(ARC_GENTLE_RIGHT, ARC_GENTLE_RIGHT.length)
        dx = math.sin(-0.005 * 100.0) / (-0.005)
        dy = (1.0 - math.cos(-0.005 * 100.0)) / (-0.005)
        _check_pose(p, AnalyticalPose(dx, dy, -0.5), tol=1e-8)


class TestArcNonzeroPose:
    def test_nonzero_origin_end(self):
        p = arc_pose_at(ARC_NONZERO_ORIGIN, ARC_NONZERO_ORIGIN.length)
        k = ARC_NONZERO_ORIGIN.curvature
        h0 = ARC_NONZERO_ORIGIN.hdg
        s = ARC_NONZERO_ORIGIN.length
        h = h0 + k * s
        dx = (math.sin(h) - math.sin(h0)) / k
        dy = (math.cos(h0) - math.cos(h)) / k
        _check_pose(p, AnalyticalPose(50.0 + dx, -30.0 + dy, h), tol=1e-8)

    def test_nonzero_hdg_end(self):
        k = ARC_NONZERO_HDG.curvature
        h0 = ARC_NONZERO_HDG.hdg
        s = ARC_NONZERO_HDG.length
        h = h0 + k * s
        dx = (math.sin(h) - math.sin(h0)) / k
        dy = (math.cos(h0) - math.cos(h)) / k
        p = arc_pose_at(ARC_NONZERO_HDG, s)
        _check_pose(p, AnalyticalPose(dx, dy, h), tol=1e-8)

    def test_tight_curve_mid(self):
        p = arc_pose_at(ARC_TIGHT, ARC_TIGHT.length / 2)
        k = ARC_TIGHT.curvature
        h0 = ARC_TIGHT.hdg
        s = ARC_TIGHT.length / 2
        h = h0 + k * s
        dx = (math.sin(h) - math.sin(h0)) / k
        dy = (math.cos(h0) - math.cos(h)) / k
        _check_pose(p, AnalyticalPose(100.0 + dx, 200.0 + dy, h), tol=1e-8)


class TestArcEdgeCases:
    def test_zero_length(self):
        fx = make_fixture(length=0.0, curvature=0.1)
        p = arc_pose_at(fx, 0.0)
        _check_pose(p, AnalyticalPose(0.0, 0.0, 0.0))

    def test_negative_s_clamped(self):
        p = arc_pose_at(ARC_GENTLE_LEFT, -1.0)
        _check_pose(p, AnalyticalPose(0.0, 0.0, 0.0))

    def test_s_beyond_length_clamped(self):
        p = arc_pose_at(ARC_GENTLE_LEFT, 200.0)
        _check_pose(p, arc_pose_at(ARC_GENTLE_LEFT, ARC_GENTLE_LEFT.length))

    def test_near_zero_positive(self):
        p = arc_pose_at(ARC_NEAR_ZERO_POS, 50.0)
        _check_pose(p, AnalyticalPose(50.0, 0.0, 5e-9), tol=1e-6)

    def test_near_zero_negative(self):
        p = arc_pose_at(ARC_NEAR_ZERO_NEG, 50.0)
        _check_pose(p, AnalyticalPose(50.0, 0.0, -5e-9), tol=1e-6)

    def test_at_eps_boundary(self):
        p = arc_pose_at(ARC_AT_EPS_BOUNDARY, 50.0)
        _check_pose(p, AnalyticalPose(50.0, 0.0, 5e-11), tol=1e-8)

    def test_exact_zero_curvature(self):
        p = arc_pose_at(ARC_EXACT_ZERO, 50.0)
        _check_pose(p, AnalyticalPose(50.0, 0.0, 0.0), tol=1e-12)

    def test_consecutive_arcs_same_curvature(self):
        k = 0.05
        fx1 = make_fixture(length=10.0, curvature=k)
        p1 = arc_pose_at(fx1, 10.0)
        fx2 = make_fixture(x=p1.x, y=p1.y, hdg=p1.hdg, length=10.0, curvature=k)
        p2 = arc_pose_at(fx2, 10.0)
        fx_combined = make_fixture(length=20.0, curvature=k)
        p_combined = arc_pose_at(fx_combined, 20.0)
        _check_pose(p2, p_combined, tol=1e-12)
