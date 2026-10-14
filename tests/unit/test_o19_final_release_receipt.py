"""Tests for O19 final release receipt validator."""
from tools.final_release_receipt import SECTIONS, STATUSES, validate


def test_valid_receipt_passes():
    receipt = {section: {"status": "NOT_RUN"} for section in SECTIONS}
    report = validate(receipt)
    assert report["status"] == "PASS"
    assert report["missing_evidence_is_not_pass"] is True


def test_missing_section_fails():
    report = validate({"repository": {}})
    assert report["status"] == "FAIL"
    assert any("missing section" in failure for failure in report["failures"])


def test_invalid_status_fails():
    receipt = {section: {"status": "NOT_RUN"} for section in SECTIONS}
    receipt["runtime"]["status"] = "SUCCESS"
    report = validate(receipt)
    assert report["status"] == "FAIL"
    assert "SUCCESS" in " ".join(report["failures"])


def test_absent_evidence_cannot_serialize_as_pass():
    receipt = {section: {} for section in SECTIONS}
    assert validate(receipt)["status"] == "PASS"
    assert "PASS" not in receipt["runtime"]
    assert STATUSES >= {"PASS", "FAIL", "NOT_RUN", "BLOCKED", "NOT_APPLICABLE"}
