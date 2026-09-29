"""Tests for O17 RQ3 dataset manifest verifier."""
from tools.rq3_dataset_manifest_verifier import REQUIRED, verify


def _manifest():
    return {field: "value" for field in REQUIRED} | {"frame_ids": ["f1", "f2"]}


def test_valid_manifest_passes():
    report = verify(_manifest())
    assert report["status"] == "PASS"
    assert report["quality_comparison"] == "NOT_RUN"


def test_duplicate_frames_fail():
    manifest = _manifest()
    manifest["frame_ids"] = ["f1", "f1"]
    assert verify(manifest)["status"] == "FAIL"


def test_missing_frames_fail():
    manifest = _manifest()
    manifest["missing_frames"] = ["f2"]
    assert verify(manifest)["status"] == "FAIL"


def test_paired_contract_mismatch_fails():
    report = verify(_manifest(), {**_manifest(), "route_id": "other"})
    assert report["status"] == "FAIL"
    assert "route_id" in report["paired_contract_mismatches"]
