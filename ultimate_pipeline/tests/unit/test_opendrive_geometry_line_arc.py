from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

from opendrive_geometry.model import Pose2D, Vec2, Bounds2D, GeometrySegment
from opendrive_geometry.primitives import (
    evaluate_line,
    evaluate_arc,
    sample_line,
    sample_arc,
    curvature_line,
    curvature_arc,
    line_bounds,
    arc_bounds,
)
from opendrive_geometry.errors import GeometryOutOfRangeError


# =============================================================================
# 1. Line analytical tests
# =============================================================================

class TestLineEvaluate:
    """Analytical tests for evaluate_line()."""

    def test_start_pose(self):
        pose = evaluate_line(10.0, 20.0, 0.5, 100.0, 0.0)
        assert pose == Pose2D(10.0, 20.0, 0.5)

    def test_end_pose(self):
        L, h = 100.0, 0.5
        pose = evaluate_line(10.0, 20.0, h, L, L)
        expected = Pose2D(10.0 + L * math.cos(h), 20.0 + L * math.sin(h), h)
        assert pose == expected

    def test_midpoint_linearity(self):
        x0, y0, hdg0, L = 0.0, 0.0, math.pi / 6, 50.0
        s1, s2, s3 = 0.0, 25.0, 50.0
        p1 = evaluate_line(x0, y0, hdg0, L, s1)
        p3 = evaluate_line(x0, y0, hdg0, L, s3)
        p2 = evaluate_line(x0, y0, hdg0, L, s2)
        assert abs(p2.x - (p1.x + p3.x) / 2.0) < 1e-12
        assert abs(p2.y - (p1.y + p3.y) / 2.0) < 1e-12

    def test_heading_invariant(self):
        hdgs = [0.0, math.pi / 4, math.pi / 2, math.pi, -math.pi / 3]
        for h in hdgs:
            pose = evaluate_line(0.0, 0.0, h, 10.0, 5.0)
            assert pose.hdg == h

    def test_tangent_direction(self):
        h = 0.789
        pose = evaluate_line(0.0, 0.0, h, 100.0, 50.0)
        direction = pose.direction()
        expected = Vec2(math.cos(h), math.sin(h))
        assert direction.x == pytest.approx(expected.x)
        assert direction.y == pytest.approx(expected.y)

    def test_curvature(self):
        assert curvature_line() == 0.0

    def test_clamp_above_zero(self):
        # Tiny negative s should be clamped
        pose = evaluate_line(0.0, 0.0, 0.0, 10.0, -1e-13)
        assert pose.x == 0.0

    def test_clamp_below_length(self):
        pose = evaluate_line(0.0, 0.0, 0.0, 10.0, 10.0 + 1e-13)
        assert pose.x == 10.0

    def test_out_of_range_raises(self):
        with pytest.raises(GeometryOutOfRangeError):
            evaluate_line(0.0, 0.0, 0.0, 10.0, -0.1)
        with pytest.raises(GeometryOutOfRangeError):
            evaluate_line(0.0, 0.0, 0.0, 10.0, 10.1)

    def test_axis_aligned(self):
        h = 0.0
        p0 = evaluate_line(1.0, 2.0, h, 100.0, 0.0)
        p100 = evaluate_line(1.0, 2.0, h, 100.0, 100.0)
        assert p0 == Pose2D(1.0, 2.0, 0.0)
        assert p100 == Pose2D(101.0, 2.0, 0.0)

    def test_vertical_up(self):
        h = math.pi / 2
        p50 = evaluate_line(0.0, 0.0, h, 100.0, 50.0)
        assert abs(p50.x) < 1e-12
        assert p50.y == pytest.approx(50.0)


class TestLineSample:

    def test_sample_count(self):
        poses = sample_line(0.0, 0.0, 0.0, 100.0, 10.0)
        assert len(poses) == 11  # 0, 10, 20, ..., 100

    def test_first_and_last(self):
        poses = sample_line(5.0, 5.0, math.pi / 3, 60.0, 60.0)
        assert poses[0] == evaluate_line(5.0, 5.0, math.pi / 3, 60.0, 0.0)
        assert poses[-1] == evaluate_line(5.0, 5.0, math.pi / 3, 60.0, 60.0)

    def test_uniform_spacing(self):
        poses = sample_line(0.0, 0.0, 0.0, 100.0, 10.0)
        for i in range(len(poses) - 1):
            d = (poses[i + 1].position() - poses[i].position()).length()
            assert d == pytest.approx(10.0, abs=1e-12)

    def test_short_segment(self):
        poses = sample_line(0.0, 0.0, 0.0, 1.0, 10.0)
        assert len(poses) == 2
        assert poses[0].x == 0.0
        assert poses[-1].x == 1.0

    def test_invalid_spacing_raises(self):
        with pytest.raises(ValueError):
            sample_line(0.0, 0.0, 0.0, 10.0, 0.0)
        with pytest.raises(ValueError):
            sample_line(0.0, 0.0, 0.0, 10.0, -1.0)


class TestLineBounds:

    def test_axis_aligned(self):
        b = line_bounds(5.0, 10.0, 0.0, 20.0)
        assert b == Bounds2D(5.0, 25.0, 10.0, 10.0)

    def test_negative_x(self):
        b = line_bounds(0.0, 0.0, math.pi, 10.0)
        assert b.x_min == -10.0
        assert b.x_max == 0.0

    def test_contains_start_and_end(self):
        b = line_bounds(0.0, 0.0, math.pi / 4, 10.0)
        s2 = 10.0 / math.sqrt(2)
        assert b.contains(Vec2(0.0, 0.0))
        assert b.contains(Vec2(s2, s2))


# =============================================================================
# 2. Arc analytical tests
# =============================================================================

class TestArcEvaluate:

    def test_zero_curvature_falls_back_to_line(self):
        p_arc = evaluate_arc(10.0, 20.0, 0.5, 100.0, 0.0, 50.0)
        p_line = evaluate_line(10.0, 20.0, 0.5, 100.0, 50.0)
        assert p_arc == p_line

    def test_start_pose(self):
        pose = evaluate_arc(1.0, 2.0, 0.3, 100.0, 0.01, 0.0)
        assert pose == Pose2D(1.0, 2.0, 0.3)

    def test_quarter_circle_left(self):
        R = 10.0
        k = 1.0 / R
        L = (math.pi / 2) * R
        pose = evaluate_arc(0.0, 0.0, 0.0, L, k, L)
        assert pose.x == pytest.approx(R, abs=1e-9)
        assert pose.y == pytest.approx(R, abs=1e-9)
        assert pose.hdg == pytest.approx(math.pi / 2, abs=1e-12)

    def test_half_circle_left(self):
        R = 5.0
        k = 1.0 / R
        L = math.pi * R
        pose = evaluate_arc(0.0, 0.0, 0.0, L, k, L)
        assert pose.x == pytest.approx(0.0, abs=1e-9)
        assert pose.y == pytest.approx(2 * R, abs=1e-9)
        assert pose.hdg == pytest.approx(math.pi, abs=1e-12)

    def test_quarter_circle_right(self):
        R = 10.0
        k = -1.0 / R
        L = (math.pi / 2) * R
        pose = evaluate_arc(0.0, 0.0, 0.0, L, k, L)
        assert pose.x == pytest.approx(R, abs=1e-9)
        assert pose.y == pytest.approx(-R, abs=1e-9)
        assert pose.hdg == pytest.approx(-math.pi / 2, abs=1e-12)

    def test_full_circle_left(self):
        R = 7.0
        k = 1.0 / R
        L = 2.0 * math.pi * R
        pose = evaluate_arc(0.0, 0.0, 0.0, L, k, L)
        assert pose.x == pytest.approx(0.0, abs=1e-9)
        assert pose.y == pytest.approx(0.0, abs=1e-9)
        hdg_norm = pose.hdg % (2 * math.pi)
        assert hdg_norm == pytest.approx(0.0, abs=1e-12)

    def test_negative_curvature_start_heading(self):
        k = -0.05
        L = 30.0
        pose = evaluate_arc(0.0, 0.0, math.pi / 3, L, k, L)
        expected_hdg = math.pi / 3 + k * L
        assert pose.hdg == pytest.approx(expected_hdg, abs=1e-12)

    def test_curvature_positive(self):
        assert curvature_arc(0.05) == 0.05

    def test_curvature_negative(self):
        assert curvature_arc(-0.03) == -0.03

    def test_curvature_zero(self):
        assert curvature_arc(0.0) == 0.0

    def test_mid_arc_heading(self):
        k, L = 0.02, 100.0
        pose = evaluate_arc(0.0, 0.0, 0.0, L, k, 25.0)
        assert pose.hdg == 0.5

    def test_clamp_above_zero(self):
        pose = evaluate_arc(0.0, 0.0, 0.0, 10.0, 0.1, -1e-13)
        assert pose.x == 0.0

    def test_clamp_below_length(self):
        pose = evaluate_arc(0.0, 0.0, 0.0, 10.0, 0.1, 10.0 + 1e-13)
        assert pose.x == pytest.approx(
            (math.sin(1.0) - 0.0) / 0.1, abs=1e-9
        )

    def test_out_of_range_raises(self):
        with pytest.raises(GeometryOutOfRangeError):
            evaluate_arc(0.0, 0.0, 0.0, 10.0, 0.01, -0.1)
        with pytest.raises(GeometryOutOfRangeError):
            evaluate_arc(0.0, 0.0, 0.0, 10.0, 0.01, 10.1)

    def test_heading_is_exact_function(self):
        k = 0.03
        for s in [0, 10, 30, 50]:
            pose = evaluate_arc(0.0, 0.0, 0.2, 100.0, k, s)
            assert pose.hdg == pytest.approx(0.2 + k * s, abs=1e-15)

    def test_tangent_direction(self):
        k = 0.02
        pose = evaluate_arc(0.0, 0.0, math.pi / 4, 100.0, k, 30.0)
        expected_hdg = math.pi / 4 + k * 30.0
        direction = pose.direction()
        expected_dir = Vec2(math.cos(expected_hdg), math.sin(expected_hdg))
        assert direction.x == pytest.approx(expected_dir.x, abs=1e-12)
        assert direction.y == pytest.approx(expected_dir.y, abs=1e-12)

    def test_endpoint_closed_form(self):
        k = 0.015
        L = 80.0
        x0, y0, h0 = 3.0, 7.0, 0.4
        pose = evaluate_arc(x0, y0, h0, L, k, L)
        expected_x = x0 + (math.sin(h0 + k * L) - math.sin(h0)) / k
        expected_y = y0 + (math.cos(h0) - math.cos(h0 + k * L)) / k
        expected_h = h0 + k * L
        assert pose.x == pytest.approx(expected_x)
        assert pose.y == pytest.approx(expected_y)
        assert pose.hdg == pytest.approx(expected_h)


class TestArcSample:

    def test_sample_count(self):
        poses = sample_arc(0.0, 0.0, 0.0, 100.0, 0.01, 10.0)
        assert len(poses) == 11

    def test_first_and_last(self):
        L, k = 50.0, 0.02
        poses = sample_arc(5.0, 5.0, 0.0, L, k, 50.0)
        assert poses[0] == evaluate_arc(5.0, 5.0, 0.0, L, k, 0.0)
        assert poses[-1] == evaluate_arc(5.0, 5.0, 0.0, L, k, L)

    def test_uniform_spacing_along_arc(self):
        k = 0.01
        L = 100.0
        poses = sample_arc(0.0, 0.0, 0.0, L, k, 10.0)
        for i in range(len(poses) - 1):
            d = (poses[i + 1].position() - poses[i].position()).length()
            # Chords are slightly shorter than arc length, so allow ~0.5% tolerance
            assert d == pytest.approx(10.0, abs=0.05)

    def test_arc_chord_convergence(self):
        k = 0.001
        L = 100.0
        poses = sample_arc(0.0, 0.0, 0.0, L, k, 1.0)
        for i in range(len(poses) - 1):
            d = (poses[i + 1].position() - poses[i].position()).length()
            assert d == pytest.approx(1.0, abs=5e-4)

    def test_short_arc(self):
        poses = sample_arc(0.0, 0.0, 0.0, 0.5, 0.1, 10.0)
        assert len(poses) == 2
        assert poses[0] == evaluate_arc(0.0, 0.0, 0.0, 0.5, 0.1, 0.0)
        assert poses[-1] == evaluate_arc(0.0, 0.0, 0.0, 0.5, 0.1, 0.5)

    def test_invalid_spacing_raises(self):
        with pytest.raises(ValueError):
            sample_arc(0.0, 0.0, 0.0, 10.0, 0.01, 0.0)
        with pytest.raises(ValueError):
            sample_arc(0.0, 0.0, 0.0, 10.0, 0.01, -1.0)


class TestArcBounds:

    def test_quarter_circle_bounds(self):
        R = 10.0
        k = 1.0 / R
        L = (math.pi / 2) * R
        b = arc_bounds(0.0, 0.0, 0.0, L, k)
        assert b.x_min == pytest.approx(0.0, abs=1e-9)
        assert b.y_min == pytest.approx(0.0, abs=1e-9)
        assert b.x_max == pytest.approx(R, abs=1e-2)
        assert b.y_max == pytest.approx(R, abs=1e-2)

    def test_negative_curvature_bounds(self):
        R = 5.0
        k = -1.0 / R
        L = (math.pi / 2) * R
        b = arc_bounds(0.0, 0.0, 0.0, L, k)
        assert b.x_max == pytest.approx(R, abs=5e-1)
        assert b.y_min == pytest.approx(-R, abs=1e-2)


# =============================================================================
# 3. Cross-validation: line that should match simple motion
# =============================================================================

class TestCrossValidation:

    @pytest.mark.parametrize("s", [0.0, 10.0, 25.0, 50.0, 80.0, 100.0])
    def test_line_forward_matches_naive(self, s):
        x0, y0, hdg0, L = 0.0, 0.0, 0.0, 100.0
        p1 = evaluate_line(x0, y0, hdg0, L, s)
        p2 = Pose2D(x0 + s, y0, hdg0)
        assert p1 == p2

    @pytest.mark.parametrize("s", [0.0, 10.0, 25.0, 50.0, 80.0, 100.0])
    def test_arc_small_curvature_approximates_line(self, s):
        k = 1e-10
        L = 100.0
        p_arc = evaluate_arc(0.0, 0.0, 0.0, L, k, s)
        p_line = evaluate_line(0.0, 0.0, 0.0, L, s)
        assert p_arc.x == pytest.approx(p_line.x, abs=1e-6)
        assert p_arc.y == pytest.approx(p_line.y, abs=1e-6)


# =============================================================================
# 4. Visualization file tests: map_plotter._sample_geometry
# =============================================================================

def _canonical_arc_point(x0, y0, hdg, length, curvature, s):
    """Canonical arc evaluator returning (x, y)."""
    from opendrive_geometry.primitives import evaluate_arc
    p = evaluate_arc(x0, y0, hdg, length, curvature, s)
    return (p.x, p.y)


def _build_geom(x0, y0, hdg, length, gtype="line", curvature=0.0):
    """Build an XML geometry element matching what map_plotter/map_diff receive."""
    s_attr = "0"  # start s is unused by samplers
    geom = ET.fromstring(
        f'<geometry s="{s_attr}" x="{x0}" y="{y0}" hdg="{hdg}" length="{length}"/>'
    )
    if gtype == "line":
        geom.append(ET.SubElement(geom, "line"))
    elif gtype == "arc":
        arc = ET.SubElement(geom, "arc")
        arc.set("curvature", str(curvature))
    return geom


class TestMapPlotterSampleGeometry:
    """map_plotter._sample_geometry must match canonical evaluator."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from ultimate_pipeline.visualization.map_plotter import MapPlotter
        self._sample = MapPlotter._sample_geometry

    def _check_last_point(self, geom, step, expected_x, expected_y, abs_tol=1e-9):
        xs, ys = self._sample(geom, step=step)
        assert len(xs) > 0, "sample returned empty xs"
        assert abs(xs[-1] - expected_x) < abs_tol, f"x mismatch: got {xs[-1]}, expected {expected_x}"
        assert abs(ys[-1] - expected_y) < abs_tol, f"y mismatch: got {ys[-1]}, expected {expected_y}"

    # --- Line tests ---

    @pytest.mark.parametrize("x0,y0,hdg,length", [
        (0.0, 0.0, 0.0, 100.0),
        (10.0, 20.0, 0.5, 50.0),
        (-5.0, 3.0, -0.3, 80.0),
        (1.0, 2.0, 0.3, 100.0),
    ])
    def test_line_endpoint(self, x0, y0, hdg, length):
        geom = _build_geom(x0, y0, hdg, length, gtype="line")
        p = evaluate_line(x0, y0, hdg, length, length)
        self._check_last_point(geom, step=1.0, expected_x=p.x, expected_y=p.y)

    def test_line_forward(self):
        """map_plotter samples at integer s: 0..int(length). Last sample=100."""
        geom = _build_geom(0, 0, 0, 100, gtype="line")
        p = evaluate_line(0, 0, 0, 100, 100)
        self._check_last_point(geom, step=1.0, expected_x=p.x, expected_y=p.y)

    # --- Arc tests ---

    @pytest.mark.parametrize("x0,y0,hdg,length,k", [
        (0.0, 0.0, 0.0, 100.0, 0.0),
        (10.0, 20.0, 0.5, 50.0, 0.0),
        (0.0, 0.0, 0.0, 100.0, 1e-15),
    ])
    def test_arc_near_zero_curvature_falls_back_to_line(self, x0, y0, hdg, length, k):
        """|k| < 1e-12 must fall back to line formula."""
        geom = _build_geom(x0, y0, hdg, length, gtype="arc", curvature=k)
        p = evaluate_line(x0, y0, hdg, length, length)
        self._check_last_point(geom, step=1.0, expected_x=p.x, expected_y=p.y)

    def test_arc_tiny_curvature_uses_arc_formula(self):
        """|k|=1e-8 > 1e-12 uses arc formula; check vs canonical arc."""
        k = 1e-8
        geom = _build_geom(0, 0, 0, 100.0, gtype="arc", curvature=k)
        p = evaluate_arc(0, 0, 0, 100.0, k, 100.0)
        self._check_last_point(geom, step=1.0, expected_x=p.x, expected_y=p.y)

    @pytest.mark.parametrize("x0,y0,hdg,length,k", [
        (0.0, 0.0, 0.0, 100.0, 0.01),
        (0.0, 0.0, 0.0, 100.0, -0.01),
        (10.0, 20.0, 1.0, 80.0, -0.02),
        (100.0, 200.0, 0.5, 30.0, 0.2),
        (5.0, 5.0, 0.5, 100.0, 0.01),
    ])
    def test_arc_endpoint(self, x0, y0, hdg, length, k):
        geom = _build_geom(x0, y0, hdg, length, gtype="arc", curvature=k)
        p = evaluate_arc(x0, y0, hdg, length, k, length)
        self._check_last_point(geom, step=1.0, expected_x=p.x, expected_y=p.y)

    def test_arc_quarter_circle(self):
        """map_plotter uses integer s sampling, so last sample=floor(L)."""
        R = 10.0
        k = 1.0 / R
        L = int(math.pi / 2 * R)  # integer length matches sampling
        geom = _build_geom(0, 0, 0, L, gtype="arc", curvature=k)
        p = evaluate_arc(0, 0, 0, L, k, L)
        self._check_last_point(geom, step=1.0, expected_x=p.x, expected_y=p.y)

    def test_arc_half_circle(self):
        """map_plotter uses integer s sampling, so last sample=floor(L)."""
        R = 5.0
        k = 1.0 / R
        L = int(math.pi * R)  # integer length matches sampling
        geom = _build_geom(0, 0, 0, L, gtype="arc", curvature=k)
        p = evaluate_arc(0, 0, 0, L, k, L)
        self._check_last_point(geom, step=1.0, expected_x=p.x, expected_y=p.y)

    def test_arc_negative_curvature(self):
        geom = _build_geom(10, 20, 1.0, 80, gtype="arc", curvature=-0.02)
        p = evaluate_arc(10, 20, 1.0, 80, -0.02, 80)
        self._check_last_point(geom, step=1.0, expected_x=p.x, expected_y=p.y)

    def test_arc_exact_zero_curvature(self):
        """Arc with curvature=0 must match line, NOT return (x0, y0)."""
        x0, y0, h0, L = 1.0, 2.0, 0.3, 100.0
        geom = _build_geom(x0, y0, h0, L, gtype="arc", curvature=0.0)
        p = evaluate_line(x0, y0, h0, L, L)
        self._check_last_point(geom, step=1.0, expected_x=p.x, expected_y=p.y)

    def test_arc_start_pose(self):
        x0, y0, h0, L, k = 5.0, 5.0, 0.5, 100.0, 0.01
        geom = _build_geom(x0, y0, h0, L, gtype="arc", curvature=k)
        xs, ys = self._sample(geom, step=1.0)
        assert len(xs) > 0
        assert abs(xs[0] - x0) < 1e-12
        assert abs(ys[0] - y0) < 1e-12

    def test_nonzero_step(self):
        x0, y0, h0, L, k = 0.0, 0.0, 0.0, 100.0, 0.0
        geom = _build_geom(x0, y0, h0, L, gtype="line")
        xs, ys = self._sample(geom, step=5.0)
        assert len(xs) == 21  # 0, 5, 10, ..., 100

    def test_invalid_geometry_returns_empty(self):
        geom = ET.fromstring('<geometry x="abc" y="def" hdg="0" length="0"/>')
        xs, ys = self._sample(geom, step=1.0)
        assert xs == []
        assert ys == []


# =============================================================================
# 5. Visualization file tests: map_diff._sample_geometry
# =============================================================================

class TestMapDiffSampleGeometry:
    """map_diff._sample_geometry must match canonical evaluator."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from ultimate_pipeline.visualization.map_diff import _sample_geometry
        self._sample = _sample_geometry

    def _check_last_point(self, geom, step, expected_x, expected_y, abs_tol=1e-9):
        pts = self._sample(geom, step=step)
        assert len(pts) > 0, "sample returned empty list"
        assert abs(pts[-1][0] - expected_x) < abs_tol, f"x mismatch: got {pts[-1][0]}, expected {expected_x}"
        assert abs(pts[-1][1] - expected_y) < abs_tol, f"y mismatch: got {pts[-1][1]}, expected {expected_y}"

    # --- Line tests ---

    @pytest.mark.parametrize("x0,y0,hdg,length", [
        (0.0, 0.0, 0.0, 100.0),
        (10.0, 20.0, 0.5, 50.0),
        (-5.0, 3.0, -0.3, 80.0),
    ])
    def test_line_endpoint(self, x0, y0, hdg, length):
        geom = _build_geom(x0, y0, hdg, length, gtype="line")
        p = evaluate_line(x0, y0, hdg, length, length)
        self._check_last_point(geom, step=5.0, expected_x=p.x, expected_y=p.y)

    # --- Arc tests ---

    @pytest.mark.parametrize("x0,y0,hdg,length,k", [
        (0.0, 0.0, 0.0, 100.0, 0.0),
        (10.0, 20.0, 0.5, 50.0, 0.0),
        (0.0, 0.0, 0.0, 100.0, 1e-15),
    ])
    def test_arc_near_zero_curvature_falls_back_to_line(self, x0, y0, hdg, length, k):
        geom = _build_geom(x0, y0, hdg, length, gtype="arc", curvature=k)
        p = evaluate_line(x0, y0, hdg, length, length)
        self._check_last_point(geom, step=5.0, expected_x=p.x, expected_y=p.y)

    @pytest.mark.parametrize("x0,y0,hdg,length,k", [
        (0.0, 0.0, 0.0, 100.0, 0.01),
        (0.0, 0.0, 0.0, 100.0, -0.01),
        (10.0, 20.0, 1.0, 80.0, -0.02),
        (100.0, 200.0, 0.5, 30.0, 0.2),
    ])
    def test_arc_endpoint(self, x0, y0, hdg, length, k):
        geom = _build_geom(x0, y0, hdg, length, gtype="arc", curvature=k)
        p = evaluate_arc(x0, y0, hdg, length, k, length)
        self._check_last_point(geom, step=5.0, expected_x=p.x, expected_y=p.y)

    def test_arc_exact_zero_curvature(self):
        x0, y0, h0, L = 1.0, 2.0, 0.3, 100.0
        geom = _build_geom(x0, y0, h0, L, gtype="arc", curvature=0.0)
        p = evaluate_line(x0, y0, h0, L, L)
        self._check_last_point(geom, step=5.0, expected_x=p.x, expected_y=p.y)

    def test_arc_quarter_circle(self):
        R = 10.0
        k = 1.0 / R
        L = (math.pi / 2) * R
        geom = _build_geom(0, 0, 0, L, gtype="arc", curvature=k)
        p = evaluate_arc(0, 0, 0, L, k, L)
        self._check_last_point(geom, step=5.0, expected_x=p.x, expected_y=p.y)
