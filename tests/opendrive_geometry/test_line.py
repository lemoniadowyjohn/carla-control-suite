from __future__ import annotations

import math

import pytest

from tests.opendrive_geometry.analytical import line_pose_at, AnalyticalPose
from tests.opendrive_geometry.fixtures import (
    LINE_START,
    LINE_NONZERO_ORIGIN,
    LINE_ANGLED,
    LINE_NEGATIVE_HDG,
    LINE_BACKWARD,
    make_fixture,
)


def _check_pose(actual: AnalyticalPose, expected: AnalyticalPose, tol: float = 1e-12):
    assert abs(actual.x - expected.x) < tol, f"x: {actual.x} != {expected.x}"
    assert abs(actual.y - expected.y) < tol, f"y: {actual.y} != {expected.y}"
    assert abs(actual.hdg - expected.hdg) < tol, f"hdg: {actual.hdg} != {expected.hdg}"


class TestLineStartPose:
    def test_origin_forward_start(self):
        p = line_pose_at(LINE_START, 0.0)
        _check_pose(p, AnalyticalPose(0.0, 0.0, 0.0))

    def test_nonzero_origin_start(self):
        p = line_pose_at(LINE_NONZERO_ORIGIN, 0.0)
        _check_pose(p, AnalyticalPose(10.0, 20.0, 0.0))

    def test_angled_start(self):
        p = line_pose_at(LINE_ANGLED, 0.0)
        _check_pose(p, AnalyticalPose(0.0, 0.0, math.pi / 6))

    def test_negative_hdg_start(self):
        p = line_pose_at(LINE_NEGATIVE_HDG, 0.0)
        _check_pose(p, AnalyticalPose(0.0, 0.0, -0.5))


class TestLineEndPose:
    def test_origin_forward_end(self):
        p = line_pose_at(LINE_START, LINE_START.length)
        _check_pose(p, AnalyticalPose(100.0, 0.0, 0.0))

    def test_nonzero_origin_end(self):
        p = line_pose_at(LINE_NONZERO_ORIGIN, LINE_NONZERO_ORIGIN.length)
        _check_pose(p, AnalyticalPose(60.0, 20.0, 0.0))

    def test_angled_end(self):
        L = LINE_ANGLED.length
        p = line_pose_at(LINE_ANGLED, L)
        _check_pose(p, AnalyticalPose(L * math.cos(math.pi / 6), L * math.sin(math.pi / 6), math.pi / 6))

    def test_backward_end(self):
        L = LINE_BACKWARD.length
        p = line_pose_at(LINE_BACKWARD, L)
        _check_pose(p, AnalyticalPose(5.0 - L, 5.0, math.pi))


class TestLineMidPose:
    def test_origin_forward_mid(self):
        p = line_pose_at(LINE_START, 50.0)
        _check_pose(p, AnalyticalPose(50.0, 0.0, 0.0))

    def test_origin_forward_quarter(self):
        p = line_pose_at(LINE_START, 25.0)
        _check_pose(p, AnalyticalPose(25.0, 0.0, 0.0))

    def test_nonzero_origin_mid(self):
        p = line_pose_at(LINE_NONZERO_ORIGIN, 25.0)
        _check_pose(p, AnalyticalPose(35.0, 20.0, 0.0))


class TestLineEdgeCases:
    def test_zero_length(self):
        fx = make_fixture(length=0.0)
        p = line_pose_at(fx, 0.0)
        _check_pose(p, AnalyticalPose(0.0, 0.0, 0.0))

    def test_negative_s_clamped(self):
        p = line_pose_at(LINE_START, -10.0)
        _check_pose(p, AnalyticalPose(0.0, 0.0, 0.0))

    def test_s_beyond_length_clamped(self):
        p = line_pose_at(LINE_START, 200.0)
        _check_pose(p, AnalyticalPose(100.0, 0.0, 0.0))

    def test_large_length(self):
        fx = make_fixture(length=1e6)
        p = line_pose_at(fx, 1e6)
        _check_pose(p, AnalyticalPose(1e6, 0.0, 0.0))

    def test_curvature_none_line(self):
        p = line_pose_at(make_fixture(), 50.0)
        _check_pose(p, AnalyticalPose(50.0, 0.0, 0.0))
