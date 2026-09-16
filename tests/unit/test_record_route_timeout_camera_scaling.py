# -*- coding: utf-8 -*-
"""Tests for run_perception_safe._compute_record_route_timeout_s camera scaling.

Regression coverage for the RQ3 paired-capture bug documented in
submission/results/perception_rq3_bounded/capture_attempt_log.txt
(2026-05-14): the Town10HD side of a paired capture used a 6-camera rig and
hit "record_route_timeout (60s process budget exhausted)" after completing
only 1 tick, because the timeout formula only scaled with frames/fps and
never accounted for camera_count. A single lightweight camera and a
6-camera rig were held to the same flat 60s floor.
"""
from __future__ import annotations

import pytest

from ultimate_pipeline.tools.run_perception_safe import (
    _compute_record_route_timeout_s,
)


def test_default_camera_count_matches_pre_fix_single_camera_formula():
    """camera_count defaults to 1, which must reproduce the exact old formula
    (floor=60s, duration_s*4+30) so existing single-camera callers/behavior
    are unaffected by this fix."""
    timeout = _compute_record_route_timeout_s(frames=200, fps=10.0)
    assert timeout == pytest.approx(max(60.0, 20.0 * 4.0 + 30.0))


def test_six_camera_rig_gets_a_larger_budget_than_the_old_flat_60s():
    # 8 frames @ 10fps => duration_s=0.8s, well under the old flat 60s floor.
    timeout = _compute_record_route_timeout_s(frames=8, fps=10.0, camera_count=6)
    assert timeout > 60.0
    assert timeout == pytest.approx(360.0)  # 60.0 * 6 floor dominates here


def test_timeout_scales_monotonically_with_camera_count():
    t1 = _compute_record_route_timeout_s(frames=100, fps=10.0, camera_count=1)
    t2 = _compute_record_route_timeout_s(frames=100, fps=10.0, camera_count=2)
    t6 = _compute_record_route_timeout_s(frames=100, fps=10.0, camera_count=6)
    assert t1 < t2 < t6


def test_camera_count_is_floored_at_one_even_if_zero_or_negative_passed():
    timeout = _compute_record_route_timeout_s(frames=200, fps=10.0, camera_count=0)
    assert timeout == pytest.approx(max(60.0, 20.0 * 4.0 + 30.0))


def test_explicit_override_still_wins_over_camera_count_scaling():
    timeout = _compute_record_route_timeout_s(
        frames=8, fps=10.0, camera_count=6, override_timeout_s=42.0
    )
    assert timeout == 42.0


def test_env_timeout_still_wins_over_camera_count_scaling():
    timeout = _compute_record_route_timeout_s(
        frames=8, fps=10.0, camera_count=6, env_timeout_s=90.0
    )
    assert timeout == 90.0


def test_long_duration_large_rig_scales_past_the_floor():
    # 20 frames @ 10fps = 2.0s duration; with 6 cameras the multiplier term
    # (2.0 * 24 + 180 = 228) is still under the floor (360), so the floor
    # dominates. Use a longer duration so the multiplier term wins, proving
    # the formula isn't JUST a bigger flat floor.
    timeout = _compute_record_route_timeout_s(frames=2000, fps=10.0, camera_count=6)
    # duration_s = 200s; per_tick_multiplier=24, fixed_overhead=180
    assert timeout == pytest.approx(200.0 * 24.0 + 180.0)
    assert timeout > 360.0
