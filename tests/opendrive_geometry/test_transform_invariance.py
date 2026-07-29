from __future__ import annotations

import math

import pytest

from tests.opendrive_geometry.analytical import line_pose_at, arc_pose_at, AnalyticalPose
from tests.opendrive_geometry.fixtures import make_fixture


def _check_pose(actual: AnalyticalPose, expected: AnalyticalPose, tol: float = 1e-9):
    assert abs(actual.x - expected.x) < tol, f"x: {actual.x} != {expected.x}"
    assert abs(actual.y - expected.y) < tol, f"y: {actual.y} != {expected.y}"
    assert abs(actual.hdg - expected.hdg) < tol, f"hdg: {actual.hdg} != {expected.hdg}"


class TestLineTranslationInvariance:
    def test_line_forward_translate(self):
        fx = make_fixture(x=100.0, y=200.0, length=50.0)
        p = line_pose_at(fx, 25.0)
        _check_pose(p, AnalyticalPose(125.0, 200.0, 0.0))

    def test_line_reverse_translate(self):
        fx = make_fixture(x=-50.0, y=-75.0, length=40.0)
        p = line_pose_at(fx, 20.0)
        _check_pose(p, AnalyticalPose(-30.0, -75.0, 0.0))


class TestLineRotationInvariance:
    def test_line_rotated_90(self):
        fx = make_fixture(hdg=math.pi / 2, length=100.0)
        p = line_pose_at(fx, 100.0)
        _check_pose(p, AnalyticalPose(0.0, 100.0, math.pi / 2))

    def test_line_rotated_45(self):
        fx = make_fixture(hdg=math.pi / 4, length=math.sqrt(2) * 100.0)
        p = line_pose_at(fx, fx.length)
        _check_pose(p, AnalyticalPose(100.0, 100.0, math.pi / 4))

    def test_line_rotated_negative(self):
        fx = make_fixture(hdg=-math.pi / 3, length=50.0)
        p = line_pose_at(fx, 50.0)
        _check_pose(p, AnalyticalPose(25.0, -25.0 * math.sqrt(3), -math.pi / 3))


class TestArcTranslationInvariance:
    def test_arc_translated(self):
        k = 0.05
        s = 30.0
        h = k * s
        fx = make_fixture(x=40.0, y=60.0, length=s, curvature=k)
        p = arc_pose_at(fx, s)
        dx = math.sin(h) / k
        dy = (1.0 - math.cos(h)) / k
        _check_pose(p, AnalyticalPose(40.0 + dx, 60.0 + dy, h))

    def test_arc_large_translate(self):
        k = 0.02
        s = 40.0
        h = k * s
        fx = make_fixture(x=1000.0, y=-500.0, length=s, curvature=k)
        p = arc_pose_at(fx, s)
        dx = math.sin(h) / k
        dy = (1.0 - math.cos(h)) / k
        _check_pose(p, AnalyticalPose(1000.0 + dx, -500.0 + dy, h))


class TestArcRotationInvariance:
    def test_arc_rotated_quarter_turn(self):
        k = 0.1
        h0 = math.pi / 2
        s = 10.0
        h = h0 + k * s
        fx = make_fixture(hdg=h0, length=s, curvature=k)
        p = arc_pose_at(fx, s)
        dx = (math.sin(h) - math.sin(h0)) / k
        dy = (math.cos(h0) - math.cos(h)) / k
        _check_pose(p, AnalyticalPose(dx, dy, h))

    def test_arc_rotated_arbitrary(self):
        k = 0.03
        h0 = 0.7
        s = 60.0
        h = h0 + k * s
        fx = make_fixture(hdg=h0, length=s, curvature=k)
        p = arc_pose_at(fx, s)
        dx = (math.sin(h) - math.sin(h0)) / k
        dy = (math.cos(h0) - math.cos(h)) / k
        _check_pose(p, AnalyticalPose(dx, dy, h))
