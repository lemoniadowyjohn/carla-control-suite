"""
RQ5 dataset quality gate tests (protocol v2, batch 12).

The gate is the last thing standing between a broken capture and a training run,
so most of these tests are negative controls: a dataset with a black frame, a
truncated PNG, a missing label, a duplicated frame, an out-of-range semantic id
or an inconsistent resolution must FAIL, not warn.

All fixtures are synthetic and carry ``claim_scope = TEST_FIXTURE_ONLY``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from ultimate_pipeline.perception.dataset_quality_gate import (
    DATASET_QUALITY_FILENAME,
    DATASET_QUALITY_SCHEMA,
    QUALITY_FAIL,
    QUALITY_PASS,
    QualityGateError,
    evaluate_dataset_quality,
    load_dataset_quality,
    run_quality_gate,
    write_dataset_quality,
)

CAMERA = "front_left_camera"
NUM_CLASSES = 29


def _make_dataset(
    root: Path,
    *,
    camera: str = CAMERA,
    frames: int = 4,
    size: int = 16,
    seed: int = 0,
    any_fraction: float = 0.05,
) -> Path:
    """Write a structurally-correct synthetic segmentation dataset."""
    rgb_dir = root / "rgb" / camera
    lab_dir = root / "semseg_raw" / camera
    rgb_dir.mkdir(parents=True, exist_ok=True)
    lab_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    for i in range(frames):
        rgb = rng.integers(0, 255, size=(size, size, 3), dtype=np.uint8)
        Image.fromarray(rgb, mode="RGB").save(rgb_dir / f"{i:08d}.png")
        lab = rng.integers(0, 8, size=(size, size), dtype=np.uint8)
        lab[rng.random((size, size)) < any_fraction] = 255
        Image.fromarray(lab, mode="L").save(lab_dir / f"{i:08d}.png")
    return root


def _codes(report) -> set[str]:
    return set(report.metrics.get("quality_failures") or [])


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_structurally_correct_dataset_passes(tmp_path):
    report = evaluate_dataset_quality(_make_dataset(tmp_path / "ds"), CAMERA, num_classes=NUM_CLASSES)
    assert report.status == QUALITY_PASS, [f.to_dict() for f in report.findings]
    assert report.ok
    assert report.metrics["frames_paired"] == 4
    assert report.metrics["sensor_completeness"]["rgb"] == 4


def test_report_records_the_required_evidence(tmp_path):
    report = evaluate_dataset_quality(_make_dataset(tmp_path / "ds"), CAMERA, num_classes=NUM_CLASSES)
    payload = report.to_dict()
    for key in (
        "sensor_completeness",
        "frames_paired",
        "class_histogram",
        "class_coverage_count",
        "duplicate_rate",
        "invalid_label_frame_count",
        "quality_failures",
    ):
        assert key in payload, f"DATASET_QUALITY payload is missing {key}"
    assert payload["schema"] == DATASET_QUALITY_SCHEMA
    assert payload["claim_scope"] == "TEST_FIXTURE_ONLY"
    assert payload["report_sha256"]


def test_any_sentinel_fraction_is_measured_not_just_tolerated(tmp_path):
    report = evaluate_dataset_quality(
        _make_dataset(tmp_path / "ds", any_fraction=0.25), CAMERA, num_classes=NUM_CLASSES
    )
    assert report.metrics["any_sentinel_fraction"] is not None
    assert 0.15 < report.metrics["any_sentinel_fraction"] < 0.40
    sentinel = [f for f in report.findings if f.code == "any_sentinel_fraction"]
    assert sentinel and sentinel[0].severity == "warning"


def test_absurd_any_sentinel_fraction_is_escalated_to_fatal(tmp_path):
    report = evaluate_dataset_quality(
        _make_dataset(tmp_path / "ds", any_fraction=1.0), CAMERA, num_classes=NUM_CLASSES
    )
    assert report.status == QUALITY_FAIL
    assert "any_sentinel_fraction" in _codes(report)


def test_dataset_quality_json_round_trips(tmp_path):
    report = evaluate_dataset_quality(_make_dataset(tmp_path / "ds"), CAMERA, num_classes=NUM_CLASSES)
    path = write_dataset_quality(tmp_path / "out", report)
    assert path.name == DATASET_QUALITY_FILENAME
    loaded = load_dataset_quality(path)
    assert loaded["status"] == report.status
    assert loaded["report_sha256"] == report.to_dict()["report_sha256"]


def test_run_quality_gate_writes_evidence(tmp_path):
    report, path = run_quality_gate(
        _make_dataset(tmp_path / "ds"), CAMERA, out_dir=tmp_path / "out", num_classes=NUM_CLASSES
    )
    assert report.ok
    assert path is not None and path.is_file()


# ---------------------------------------------------------------------------
# structural negative controls
# ---------------------------------------------------------------------------


def test_missing_root_is_an_error_not_a_pass(tmp_path):
    with pytest.raises(QualityGateError, match="does not exist"):
        evaluate_dataset_quality(tmp_path / "absent", CAMERA)


def test_missing_camera_directory_is_an_error(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    with pytest.raises(QualityGateError, match="no rgb/"):
        evaluate_dataset_quality(root, "no_such_camera")


def test_missing_semantic_labels_fail(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    (root / "semseg_raw" / CAMERA / "00000000.png").unlink()
    report = evaluate_dataset_quality(root, CAMERA, num_classes=NUM_CLASSES)
    assert report.status == QUALITY_FAIL
    assert "semantic_label_missing" in _codes(report)
    assert report.metrics["sensor_completeness"]["semseg_raw"] == 3


def test_rgb_frame_without_label_is_a_sensor_correspondence_failure(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    Image.fromarray(
        np.zeros((16, 16, 3), dtype=np.uint8), mode="RGB"
    ).save(root / "rgb" / CAMERA / "00009999.png")
    report = evaluate_dataset_quality(root, CAMERA, num_classes=NUM_CLASSES)
    assert report.status == QUALITY_FAIL
    assert "semantic_label_missing" in _codes(report)


def test_dataset_with_no_paired_frames_fails_with_explicit_reason(tmp_path):
    root = tmp_path / "ds"
    (root / "rgb" / CAMERA).mkdir(parents=True)
    (root / "semseg_raw" / CAMERA).mkdir(parents=True)
    report = evaluate_dataset_quality(root, CAMERA, num_classes=NUM_CLASSES)
    assert report.status == QUALITY_FAIL
    assert "no_paired_frames" in _codes(report)


def test_required_lidar_must_be_present(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    report = evaluate_dataset_quality(root, CAMERA, require_lidar=True, num_classes=NUM_CLASSES)
    assert report.status == QUALITY_FAIL
    assert "lidar_missing" in _codes(report)

    lidar = root / "lidar" / CAMERA
    lidar.mkdir(parents=True)
    for i in range(4):
        (lidar / f"{i:08d}.bin").write_bytes(b"\x00" * 8)
    ok = evaluate_dataset_quality(root, CAMERA, require_lidar=True, num_classes=NUM_CLASSES)
    assert ok.status == QUALITY_PASS, [f.to_dict() for f in ok.findings]
    assert ok.metrics["sensor_completeness"]["lidar"] == 4


# ---------------------------------------------------------------------------
# decodability / corruption negative controls
# ---------------------------------------------------------------------------


def test_truncated_png_is_detected_as_undecodable(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    (root / "rgb" / CAMERA / "00000002.png").write_bytes(b"\x89PNG\r\n\x1a\n truncated")
    report = evaluate_dataset_quality(root, CAMERA, num_classes=NUM_CLASSES)
    assert report.status == QUALITY_FAIL
    assert "file_undecodable" in _codes(report)


def test_all_black_rgb_frame_is_detected(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    Image.fromarray(np.zeros((16, 16, 3), dtype=np.uint8), mode="RGB").save(
        root / "rgb" / CAMERA / "00000001.png"
    )
    report = evaluate_dataset_quality(root, CAMERA, num_classes=NUM_CLASSES)
    assert report.status == QUALITY_FAIL
    assert "rgb_all_black" in _codes(report)


def test_duplicate_rgb_content_under_two_frame_ids_is_detected(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    source = (root / "rgb" / CAMERA / "00000000.png").read_bytes()
    (root / "rgb" / CAMERA / "00000003.png").write_bytes(source)
    report = evaluate_dataset_quality(root, CAMERA, num_classes=NUM_CLASSES)
    assert report.status == QUALITY_FAIL
    assert "duplicate_content" in _codes(report)
    assert report.metrics["duplicate_content_count"] >= 1
    assert report.metrics["duplicate_rate"] > 0.0


def test_out_of_range_semantic_id_is_detected(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    lab = np.zeros((16, 16), dtype=np.uint8)
    lab[0, 0] = 200  # >= num_classes(29) and != Any(255)
    Image.fromarray(lab, mode="L").save(root / "semseg_raw" / CAMERA / "00000000.png")
    report = evaluate_dataset_quality(root, CAMERA, num_classes=NUM_CLASSES)
    assert report.status == QUALITY_FAIL
    assert "semantic_id_invalid" in _codes(report)
    assert report.metrics["invalid_label_frame_count"] >= 1


def test_label_geometry_mismatch_is_detected(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    Image.fromarray(np.zeros((8, 8), dtype=np.uint8), mode="L").save(
        root / "semseg_raw" / CAMERA / "00000000.png"
    )
    report = evaluate_dataset_quality(root, CAMERA, num_classes=NUM_CLASSES)
    assert report.status == QUALITY_FAIL
    assert "semantic_id_invalid" in _codes(report)


def test_inconsistent_resolution_is_detected(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    Image.fromarray(
        np.zeros((32, 32, 3), dtype=np.uint8), mode="RGB"
    ).save(root / "rgb" / CAMERA / "00000001.png")
    Image.fromarray(
        np.zeros((32, 32), dtype=np.uint8), mode="L"
    ).save(root / "semseg_raw" / CAMERA / "00000001.png")
    report = evaluate_dataset_quality(root, CAMERA, num_classes=NUM_CLASSES)
    assert report.status == QUALITY_FAIL
    assert "resolution_inconsistent" in _codes(report)
    assert len(report.metrics["resolutions"]) == 2


def test_expected_resolution_is_enforced_when_requested(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    report = evaluate_dataset_quality(
        root, CAMERA, expected_resolution=(64, 64), num_classes=NUM_CLASSES
    )
    assert report.status == QUALITY_FAIL
    assert "resolution_mismatch" in _codes(report)


def test_frame_id_without_digits_is_invalid(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    (root / "rgb" / CAMERA / "00000001.png").rename(root / "rgb" / CAMERA / "frame_a.png")
    (root / "semseg_raw" / CAMERA / "00000001.png").rename(
        root / "semseg_raw" / CAMERA / "frame_a.png"
    )
    report = evaluate_dataset_quality(root, CAMERA, num_classes=NUM_CLASSES)
    assert report.status == QUALITY_FAIL
    assert "frame_id_invalid" in _codes(report)


def test_constant_semantic_frame_is_reported_as_a_warning_not_silently_ignored(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    Image.fromarray(
        np.full((16, 16), 3, dtype=np.uint8), mode="L"
    ).save(root / "semseg_raw" / CAMERA / "00000000.png")
    report = evaluate_dataset_quality(root, CAMERA, num_classes=NUM_CLASSES)
    assert report.metrics["constant_semantic_frame_count"] == 1
    finding = [f for f in report.findings if f.code == "semantic_constant_frame"][0]
    assert finding.severity == "warning"
    assert report.status == QUALITY_PASS


def test_class_coverage_is_reported(tmp_path):
    root = _make_dataset(tmp_path / "ds")
    report = evaluate_dataset_quality(root, CAMERA, num_classes=NUM_CLASSES)
    coverage = report.metrics["class_coverage_count"]
    assert 0 < coverage <= NUM_CLASSES
    assert len(report.metrics["class_histogram"]) == NUM_CLASSES
    assert len(report.metrics["classes_never_present"]) == NUM_CLASSES - coverage


def test_diagnostic_decode_cap_is_recorded_and_never_reported_as_authoritative(tmp_path):
    root = _make_dataset(tmp_path / "ds", frames=6)
    report = evaluate_dataset_quality(
        root, CAMERA, max_decode_frames=2, num_classes=NUM_CLASSES
    )
    assert report.metrics["diagnostic"] is True
    assert report.metrics["frames_scanned"] == 2
    assert report.metrics["frames_paired"] == 6


def test_quality_report_json_is_schema_checked(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema": "something_else"}), encoding="utf-8")
    with pytest.raises(QualityGateError, match="unsupported dataset quality schema"):
        load_dataset_quality(path)
    with pytest.raises(QualityGateError, match="not found"):
        load_dataset_quality(tmp_path / "absent.json")