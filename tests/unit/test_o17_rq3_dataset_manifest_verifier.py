"""Tests for O17 RQ3 dataset manifest verifier."""
from tools.rq3_dataset_manifest_verifier import REQUIRED, verify


def _manifest():
    return {field: "value" for field in REQUIRED} | {"frame_ids": ["f1", "f2"]}


def test_valid_manifest_without_paired_is_incomplete():
    """GAP-033: verify() without paired manifest should not return PASS.
    
    Current bug: when paired=None (or --paired flag omitted), the cross-manifest
    pairing check is skipped entirely but the function still returns PASS for a
    self-consistent single manifest. This is indistinguishable from a real,
    checked pairing pass. The status should be INCOMPLETE or SKIPPED_NO_PAIR.
    """
    report = verify(_manifest())
    # After fix: should be INCOMPLETE or SKIPPED_NO_PAIR, not PASS
    assert report["status"] in ("INCOMPLETE", "SKIPPED_NO_PAIR")
    assert report["paired_contract_mismatches"] == []
    # The pairing check was not performed
    assert report.get("pairing_performed") is False


def test_valid_manifest_with_paired_passes():
    """When paired manifest is provided and matches, status should be PASS."""
    report = verify(_manifest(), _manifest())
    assert report["status"] == "PASS"
    assert report["quality_comparison"] == "NOT_RUN"
    assert report.get("pairing_performed") is True


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
    assert report.get("pairing_performed") is True
