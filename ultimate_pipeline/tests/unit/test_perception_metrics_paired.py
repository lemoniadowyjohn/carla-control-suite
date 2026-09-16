# -*- coding: utf-8 -*-
"""Tests for the paired-capture comparison guard in perception_metrics.py.

Regression coverage for submission/results/perception_rq3_bounded/
paired_metrics.json (2026-05-14): the recorded paired-capture attempt used
mismatched configs on its two sides (20 frames/1 camera generated-map vs.
8 frames/6-camera Town10HD) and every pixel-level metric
(kl_divergence, histogram_intersection, mean_brightness_difference,
per_channel_kl) came back `null` because the comparison was structurally
impossible to compute.

`assert_paired_captures_compatible` / `compute_paired_perception_metrics`
must now raise a clear error instead of silently producing those nulls.
"""
from __future__ import annotations

import pytest
from PIL import Image

from ultimate_pipeline.perception.perception_metrics import (
    PairedCaptureMismatchError,
    assert_paired_captures_compatible,
    compute_paired_perception_metrics,
    compute_perception_metrics,
)


def _write_camera_frames(root, camera, n, color):
    cam_dir = root / camera
    cam_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("RGB", (16, 12), color).save(cam_dir / f"{i:06d}.png")


# ---------------------------------------------------------------------------
# (b) the guard raises when configs are artificially mismatched
# ---------------------------------------------------------------------------


def test_guard_raises_on_frame_count_mismatch():
    metrics_a = {
        "enabled": True,
        "camera": {"counts": {"front_left_camera": 20}},
    }
    metrics_b = {
        "enabled": True,
        "camera": {"counts": {"front_left_camera": 8}},
    }
    with pytest.raises(PairedCaptureMismatchError, match="frame count mismatch"):
        assert_paired_captures_compatible(metrics_a, metrics_b, label_a="generated_map", label_b="town10hd")


def test_guard_raises_on_camera_set_mismatch():
    metrics_a = {
        "enabled": True,
        "camera": {"counts": {"front_camera": 8}},
    }
    metrics_b = {
        "enabled": True,
        "camera": {
            "counts": {
                "back_left_camera": 8,
                "back_right_camera": 8,
                "front_left_camera": 8,
                "front_right_camera": 8,
                "left_camera": 8,
                "right_camera": 8,
            }
        },
    }
    with pytest.raises(PairedCaptureMismatchError, match="camera set mismatch"):
        assert_paired_captures_compatible(metrics_a, metrics_b)


def test_guard_raises_when_either_side_has_no_data():
    metrics_a = {"enabled": False, "reason": "no_sensor_data_found"}
    metrics_b = {"enabled": True, "camera": {"counts": {"front_camera": 8}}}
    with pytest.raises(PairedCaptureMismatchError, match="no usable sensor data"):
        assert_paired_captures_compatible(metrics_a, metrics_b)


def test_compute_paired_perception_metrics_raises_on_real_mismatched_fixtures(tmp_path):
    """End-to-end reproduction of the 2026-05-14 mismatch using real captured
    directories (20 frames/1 camera vs. 8 frames/6 cameras)."""
    generated = tmp_path / "generated_map"
    town10hd = tmp_path / "town10hd"
    _write_camera_frames(generated, "front_camera", 20, (100, 100, 100))
    for cam in (
        "front_left_camera",
        "front_right_camera",
        "left_camera",
        "right_camera",
        "back_left_camera",
        "back_right_camera",
    ):
        _write_camera_frames(town10hd, cam, 8, (120, 90, 60))

    with pytest.raises(PairedCaptureMismatchError):
        compute_paired_perception_metrics(str(generated), str(town10hd))


# ---------------------------------------------------------------------------
# (c) the guard passes silently when configs match
# ---------------------------------------------------------------------------


def test_guard_passes_silently_when_camera_sets_and_frame_counts_match():
    metrics_a = {
        "enabled": True,
        "camera": {"counts": {"front_left_camera": 8, "front_right_camera": 8}},
    }
    metrics_b = {
        "enabled": True,
        "camera": {"counts": {"front_left_camera": 8, "front_right_camera": 8}},
    }
    # Must not raise.
    assert_paired_captures_compatible(metrics_a, metrics_b) is None


def test_compute_paired_perception_metrics_succeeds_on_matched_fixtures_and_is_not_null(tmp_path):
    generated = tmp_path / "generated_map"
    town10hd = tmp_path / "town10hd"
    # Same camera set, same frame count on both sides -> directly comparable.
    _write_camera_frames(generated, "front_left_camera", 5, (200, 40, 40))
    _write_camera_frames(generated, "front_right_camera", 5, (200, 40, 40))
    _write_camera_frames(town10hd, "front_left_camera", 5, (40, 40, 200))
    _write_camera_frames(town10hd, "front_right_camera", 5, (40, 40, 200))

    result = compute_paired_perception_metrics(
        str(generated), str(town10hd), label_a="generated_map", label_b="town10hd"
    )

    assert result["enabled"] is True
    assert result["frames_a"] == 10
    assert result["frames_b"] == 10
    assert sorted(result["camera_names"]) == ["front_left_camera", "front_right_camera"]

    # These must be REAL numbers now, not the `null` recorded in the
    # 2026-05-14 paired_metrics.json.
    assert result["kl_divergence"] is not None
    assert result["histogram_intersection"] is not None
    assert result["mean_brightness_difference"] is not None
    assert result["per_channel_kl"] is not None
    assert set(result["per_channel_kl"].keys()) == {"r", "g", "b"}

    # The two solid-color fixtures are maximally different in R and B
    # channels, so KL-divergence should be clearly positive (non-trivial)
    # and histogram intersection should be low (near 0), not a degenerate
    # perfect match.
    assert result["kl_divergence"] > 0.0
    assert result["histogram_intersection"] < 1.0


def test_compute_paired_perception_metrics_identical_fixtures_give_zero_divergence(tmp_path):
    generated = tmp_path / "generated_map"
    town10hd = tmp_path / "town10hd"
    _write_camera_frames(generated, "front_camera", 4, (128, 128, 128))
    _write_camera_frames(town10hd, "front_camera", 4, (128, 128, 128))

    result = compute_paired_perception_metrics(str(generated), str(town10hd))

    assert result["enabled"] is True
    assert result["kl_divergence"] == pytest.approx(0.0, abs=1e-6)
    assert result["histogram_intersection"] == pytest.approx(1.0, abs=1e-6)


def test_compute_perception_metrics_still_works_standalone(tmp_path):
    """Sanity: the new paired-comparison code must not have broken the
    existing single-run compute_perception_metrics entry point."""
    root = tmp_path / "run"
    _write_camera_frames(root, "front_camera", 3, (10, 10, 10))
    result = compute_perception_metrics(str(root))
    assert result["enabled"] is True
    assert result["camera"]["counts"] == {"front_camera": 3}
