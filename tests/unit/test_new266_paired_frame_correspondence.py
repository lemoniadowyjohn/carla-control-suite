# -*- coding: utf-8 -*-
"""NEW-266: exact paired-frame correspondence.

The 2026-05-14 paired-comparison work established that mismatched camera
SETS / frame COUNTS must raise. This file pins the stronger claim: equal
counts are NOT evidence of correspondence, and the histogram metrics
produced by `compute_paired_perception_metrics` are distributional domain
gap, not paired frame metrics.
"""
from __future__ import annotations

import pytest
from PIL import Image

from ultimate_pipeline.perception.perception_metrics import (
    PairedCaptureMismatchError,
    assert_paired_captures_compatible,
    compute_paired_perception_metrics,
    paired_frame_correspondence_report,
)


def _metrics(counts, frame_ids=None, enabled=True, reason=""):
    payload = {"enabled": enabled, "reason": reason, "camera": {"counts": dict(counts)}}
    if frame_ids is not None:
        payload["camera"]["frame_ids"] = {
            k: list(v) for k, v in frame_ids.items()
        }
    return payload


def _write_camera_frames(root, camera, n, color):
    cam_dir = root / camera
    cam_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("RGB", (16, 12), color).save(cam_dir / f"{i:06d}.png")


# ---------------------------------------------------------------------------
# equal counts, unequal frame ids -> must not be treated as a match
# ---------------------------------------------------------------------------


def test_equal_counts_but_different_frame_ids_raise():
    metrics_a = _metrics(
        {"front_left_camera": 4},
        {"front_left_camera": [101, 102, 103, 104]},
    )
    metrics_b = _metrics(
        {"front_left_camera": 4},
        {"front_left_camera": [201, 202, 203, 204]},
    )
    with pytest.raises(PairedCaptureMismatchError) as exc:
        assert_paired_captures_compatible(metrics_a, metrics_b)
    assert "frame id set mismatch" in str(exc.value)


def test_identical_frame_ids_pass():
    metrics_a = _metrics(
        {"front_left_camera": 3},
        {"front_left_camera": [7, 8, 9]},
    )
    metrics_b = _metrics(
        {"front_left_camera": 3},
        {"front_left_camera": [9, 8, 7]},
    )
    assert_paired_captures_compatible(metrics_a, metrics_b) is None
    assert metrics_a["_pairing_evidence"]["frame_id_correspondence"] == "MATCH"


def test_frame_correspondence_required_but_unrecorded_raises():
    metrics_a = _metrics({"front_left_camera": 3})
    metrics_b = _metrics({"front_left_camera": 3})
    with pytest.raises(PairedCaptureMismatchError, match="correspondence required"):
        assert_paired_captures_compatible(
            metrics_a, metrics_b, require_frame_correspondence=True
        )


def test_unrecorded_frame_ids_are_reported_not_invented():
    metrics_a = _metrics({"front_left_camera": 3})
    metrics_b = _metrics({"front_left_camera": 3})
    assert_paired_captures_compatible(metrics_a, metrics_b) is None
    assert metrics_a["_pairing_evidence"]["frame_id_correspondence"] == "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# governed pair_sequence_index
# ---------------------------------------------------------------------------


def test_pair_sequence_index_mismatch_raises():
    metrics_a = _metrics({"front_left_camera": 3})
    metrics_b = _metrics({"front_left_camera": 3})
    with pytest.raises(PairedCaptureMismatchError, match="pair_sequence_index mismatch"):
        assert_paired_captures_compatible(
            metrics_a,
            metrics_b,
            pair_sequence_index_a=[0, 1, 2],
            pair_sequence_index_b=[0, 1, 5],
        )


def test_pair_sequence_index_match_passes():
    metrics_a = _metrics({"front_left_camera": 3})
    metrics_b = _metrics({"front_left_camera": 3})
    assert_paired_captures_compatible(
        metrics_a,
        metrics_b,
        pair_sequence_index_a=[0, 1, 2],
        pair_sequence_index_b=[0, 1, 2],
    ) is None
    assert metrics_a["_pairing_evidence"]["pair_sequence_index"] == "MATCH"


def test_pair_sequence_index_supplied_for_one_arm_only_raises():
    metrics_a = _metrics({"front_left_camera": 3})
    metrics_b = _metrics({"front_left_camera": 3})
    with pytest.raises(PairedCaptureMismatchError, match="pair_sequence_index"):
        assert_paired_captures_compatible(
            metrics_a, metrics_b, pair_sequence_index_a=[0, 1, 2]
        )


# ---------------------------------------------------------------------------
# correspondence report
# ---------------------------------------------------------------------------


def test_correspondence_report_detects_partial_overlap():
    metrics_a = _metrics(
        {"front_left_camera": 4},
        {"front_left_camera": [1, 2, 3, 4]},
    )
    metrics_b = _metrics(
        {"front_left_camera": 4},
        {"front_left_camera": [1, 2, 9, 10]},
    )
    report = paired_frame_correspondence_report(metrics_a, metrics_b)
    assert report["exact_correspondence"] is False
    assert report["metric_family"] == "paired_frame_metric"
    row = report["rows"][0]
    assert row["frames_a"] == row["frames_b"] == 4  # equal counts
    assert row["common_frame_ids"] == 2  # but only 2 correspond
    assert report["common_frame_ids_across_cameras"] == [1, 2]


def test_correspondence_report_requires_governed_pair_sequence():
    metrics_a = _metrics({"front_left_camera": 2}, {"front_left_camera": [1, 2]})
    metrics_b = _metrics({"front_left_camera": 2}, {"front_left_camera": [1, 2]})
    report = paired_frame_correspondence_report(
        metrics_a, metrics_b, pair_sequence_index_a=[0, 1], pair_sequence_index_b=[0, 9]
    )
    assert report["pair_sequence_index_match"] is False
    assert report["exact_correspondence"] is True
    assert "same governed route pose index" in report["policy"]


# ---------------------------------------------------------------------------
# the histogram metrics are distributional domain gap, not paired frames
# ---------------------------------------------------------------------------


def test_histogram_metrics_are_labelled_distributional_domain_gap(tmp_path):
    generated = tmp_path / "generated_map"
    town10hd = tmp_path / "town10hd"
    _write_camera_frames(generated, "front_camera", 4, (200, 40, 40))
    _write_camera_frames(town10hd, "front_camera", 4, (40, 40, 200))

    result = compute_paired_perception_metrics(str(generated), str(town10hd))

    assert result["metric_family"] == "distributional_domain_gap"
    assert result["paired_frame_metric"] is False
    assert result["comparison_basis"] == "pooled_histograms_over_matched_cameras_not_pose_correspondence"
    assert "pair_sequence_index" in result["paired_frame_metrics_note"]
