# -*- coding: utf-8 -*-
"""Elevation-subsystem audit (post-audit-phase-e): elevation_profile_builder.py
(F4 piecewise DEM elevation profile fitter) had zero test coverage despite
being a real, wired producer for release evidence (see
ultimate_pipeline/tools/phase_f4_piecewise_profiles.py, which calls
build_profiles_on_copy on the pinned candidate and records max_deviation_m in
its evidence JSON/markdown).

This file covers the pure functions (`_resample_chain`, `fit_piecewise_cubic`,
`_linear_segments`, `build_profile_element`) and pins one real, documented gap:
`_subdivide_overshoot` (called from `fit_piecewise_cubic`) is a no-op -- it
never checks deviation or inserts knots despite its docstring and the
`max_deviation_m` parameter threading all the way from the public
`build_profiles_on_copy` API down to it. This is NOT fixed here: implementing
real overshoot subdivision is new smoothing/repair logic, which this session's
standing policy requires separate, deliberate authorization for (a prior
"obvious" smoothing fix regressed 0 -> 6,024 new position seams when actually
tested). The test below documents the current behavior so it cannot silently
regress further, and so future readers don't assume the deviation bound is
enforced.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.elevation_profile_builder import (
    _linear_segments,
    _resample_chain,
    build_profile_element,
    fit_piecewise_cubic,
)


class TestResampleChain:
    def test_empty_polyline_returns_empty(self):
        assert _resample_chain([], spacing_m=5.0) == []

    def test_single_point_returns_origin_only(self):
        out = _resample_chain([(1.0, 2.0)], spacing_m=5.0)
        assert out == [(0.0, 1.0, 2.0)]

    def test_straight_line_resampled_at_spacing(self):
        out = _resample_chain([(0.0, 0.0), (20.0, 0.0)], spacing_m=5.0)
        s_vals = [p[0] for p in out]
        assert s_vals[0] == 0.0
        assert s_vals[-1] == 20.0
        # Monotonically increasing s.
        assert all(b > a for a, b in zip(s_vals, s_vals[1:]))

    def test_zero_length_segment_is_skipped(self):
        # Duplicate consecutive point must not produce a NaN/zero-division step.
        out = _resample_chain([(0.0, 0.0), (0.0, 0.0), (10.0, 0.0)], spacing_m=5.0)
        assert out[-1][0] == 10.0


class TestFitPiecewiseCubic:
    def test_fewer_than_two_samples_returns_empty(self):
        assert fit_piecewise_cubic([(0.0, 1.0)]) == []
        assert fit_piecewise_cubic([]) == []

    def test_two_samples_uses_linear_fallback(self):
        # scipy CubicSpline requires >= 3 points in this module's own gating
        # (`len(samples) >= 3`), so 2 samples always take the linear path.
        segs = fit_piecewise_cubic([(0.0, 10.0), (10.0, 20.0)])
        assert len(segs) == 1
        s0, a, b, c, d = segs[0]
        assert s0 == 0.0
        assert a == 10.0
        assert b == 1.0  # slope = (20-10)/10
        assert c == 0.0 and d == 0.0

    def test_segments_are_ordered_by_s_regardless_of_input_order(self):
        segs = fit_piecewise_cubic([(10.0, 5.0), (0.0, 0.0), (20.0, 8.0)])
        s_vals = [seg[0] for seg in segs]
        assert s_vals == sorted(s_vals)

    def test_segment_count_matches_knot_count_minus_one(self):
        samples = [(0.0, 0.0), (10.0, 1.0), (20.0, 2.0), (30.0, 1.0)]
        segs = fit_piecewise_cubic(samples)
        assert len(segs) == len(samples) - 1

    def test_max_deviation_m_is_accepted_but_not_enforced(self):
        """Pins a known, documented gap (see module-level docstring above):
        the `max_deviation_m` overshoot-subdivision path is unimplemented, so
        passing a very tight bound does not change the emitted segment count
        even when the natural cubic spline clearly overshoots a sharp spike.
        This test exists to prevent a future silent regression where the
        parameter starts being *silently ignored differently* (e.g. crashing)
        rather than remaining a well-defined no-op; it does NOT assert that
        deviation is bounded, because it isn't.
        """
        samples = [(0.0, 0.0), (10.0, 0.0), (20.0, 50.0), (30.0, 0.0), (40.0, 0.0)]
        segs_tight = fit_piecewise_cubic(samples, max_deviation_m=0.01)
        segs_loose = fit_piecewise_cubic(samples, max_deviation_m=1000.0)
        assert len(segs_tight) == len(segs_loose) == len(samples) - 1


class TestLinearSegments:
    def test_builds_slope_between_consecutive_samples(self):
        segs = _linear_segments([(0.0, 0.0), (10.0, 5.0), (20.0, 5.0)])
        assert len(segs) == 2
        assert segs[0] == (0.0, 0.0, 0.5, 0.0, 0.0)
        assert segs[1] == (10.0, 5.0, 0.0, 0.0, 0.0)

    def test_skips_zero_length_span(self):
        segs = _linear_segments([(0.0, 0.0), (0.0, 5.0), (10.0, 5.0)])
        assert len(segs) == 1
        assert segs[0][0] == 0.0


class TestBuildProfileElement:
    def test_replaces_existing_profile(self):
        road = ET.Element("road", id="1", length="10.0")
        old_profile = ET.SubElement(road, "elevationProfile")
        ET.SubElement(old_profile, "elevation", s="0", a="999", b="0", c="0", d="0")

        build_profile_element(road, [(0.0, 1.0, 0.1, 0.0, 0.0)])

        profiles = road.findall("elevationProfile")
        assert len(profiles) == 1
        elevs = profiles[0].findall("elevation")
        assert len(elevs) == 1
        assert elevs[0].get("a") == "1.000000"

    def test_empty_segments_leaves_no_profile(self):
        road = ET.Element("road", id="1", length="10.0")
        build_profile_element(road, [])
        assert road.find("elevationProfile") is None

    def test_empty_segments_removes_stale_existing_profile(self):
        road = ET.Element("road", id="1", length="10.0")
        old_profile = ET.SubElement(road, "elevationProfile")
        ET.SubElement(old_profile, "elevation", s="0", a="1", b="0", c="0", d="0")
        build_profile_element(road, [])
        assert road.find("elevationProfile") is None
