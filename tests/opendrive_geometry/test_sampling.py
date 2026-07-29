from __future__ import annotations

import math

import pytest

from opendrive_geometry.primitives import sample_line, sample_arc, evaluate_line, evaluate_arc


class TestSampleLineGuaranteedEndpoint:
    def test_first_sample_at_s_zero(self):
        poses = sample_line(5.0, 10.0, 0.3, 100.0, 10.0)
        assert abs(poses[0].x - 5.0) < 1e-12
        assert abs(poses[0].y - 10.0) < 1e-12
        assert abs(poses[0].hdg - 0.3) < 1e-12

    def test_last_sample_at_s_length(self):
        poses = sample_line(5.0, 10.0, 0.3, 100.0, 10.0)
        last = evaluate_line(5.0, 10.0, 0.3, 100.0, 100.0)
        assert abs(poses[-1].x - last.x) < 1e-12
        assert abs(poses[-1].y - last.y) < 1e-12

    def test_endpoint_appears_exactly_once(self):
        poses = sample_line(0.0, 0.0, 0.0, 100.0, 10.0)
        count_end = sum(1 for p in poses if abs(p.x - 100.0) < 1e-9)
        assert count_end == 1, f"endpoint appears {count_end} times"

    def test_samples_monotonic_in_s(self):
        poses = sample_line(0.0, 0.0, 0.0, 100.0, 10.0)
        xs = [p.x for p in poses]
        assert all(xs[i] <= xs[i + 1] for i in range(len(xs) - 1))

    def test_non_divisible_spacing_includes_endpoint(self):
        poses = sample_line(0.0, 0.0, 0.0, 100.0, 7.0)
        assert abs(poses[-1].x - 100.0) < 1e-9

    def test_zero_length_rejected(self):
        with pytest.raises(ValueError, match="length must be positive"):
            sample_line(0.0, 0.0, 0.0, 0.0, 10.0)

    def test_negative_length_rejected(self):
        with pytest.raises(ValueError, match="length must be positive"):
            sample_line(0.0, 0.0, 0.0, -10.0, 10.0)


class TestSampleArcGuaranteedEndpoint:
    def test_first_sample_at_s_zero(self):
        poses = sample_arc(0.0, 0.0, 0.0, math.pi * 5.0, 0.2, 10.0)
        assert abs(poses[0].x - 0.0) < 1e-12
        assert abs(poses[0].y - 0.0) < 1e-12
        assert abs(poses[0].hdg - 0.0) < 1e-12

    def test_last_sample_at_s_length(self):
        L = math.pi * 5.0
        poses = sample_arc(0.0, 0.0, 0.0, L, 0.2, 10.0)
        last = evaluate_arc(0.0, 0.0, 0.0, L, 0.2, L)
        assert abs(poses[-1].x - last.x) < 1e-9
        assert abs(poses[-1].y - last.y) < 1e-9
        assert abs(poses[-1].hdg - last.hdg) < 1e-9

    def test_non_divisible_spacing_includes_endpoint(self):
        L = 100.0
        poses = sample_arc(0.0, 0.0, 0.0, L, 0.01, 7.0)
        last = evaluate_arc(0.0, 0.0, 0.0, L, 0.01, L)
        assert abs(poses[-1].x - last.x) < 1e-9
        assert abs(poses[-1].y - last.y) < 1e-9

    def test_endpoint_appears_exactly_once(self):
        poses = sample_arc(0.0, 0.0, 0.0, 100.0, 0.01, 10.0)
        count_end = sum(1 for p in poses if abs(p.x - poses[-1].x) < 1e-9 and abs(p.y - poses[-1].y) < 1e-9)
        assert count_end == 1, f"endpoint appears {count_end} times"

    def test_samples_monotonic_in_s(self):
        poses = sample_arc(0.0, 0.0, 0.0, 100.0, 0.01, 10.0)
        if len(poses) > 1:
            dists = [math.hypot(poses[i + 1].x - poses[i].x, poses[i + 1].y - poses[i].y) for i in range(len(poses) - 1)]
            assert all(d > 0 for d in dists)

    def test_short_arc_has_both_endpoints(self):
        poses = sample_arc(0.0, 0.0, 0.0, 3.0, 0.1, 10.0)
        assert len(poses) >= 2
        assert abs(poses[0].x - 0.0) < 1e-12

    def test_zero_length_rejected(self):
        with pytest.raises(ValueError, match="length must be positive"):
            sample_arc(0.0, 0.0, 0.0, 0.0, 0.1, 10.0)

    def test_negative_length_rejected(self):
        with pytest.raises(ValueError, match="length must be positive"):
            sample_arc(0.0, 0.0, 0.0, -10.0, 0.1, 10.0)
