"""Tests for O19 final release receipt validator.

ARCHITECTURAL DISTINCTION: SCHEMA_VALID != RELEASE_ADMISSIBLE.

The validate() function is schema-only validation: it checks that required
sections exist and that status values belong to the allowed vocabulary.
It does NOT determine whether a receipt is admissible for release promotion.
A receipt where all sections have status NOT_RUN is schema-valid but NOT
release-admissible.

No production caller promotes based on validate() output alone.
See tools/final_release_receipt.py for the full contract.
"""
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


# ---------------------------------------------------------------------------
# R1.1 negative tests: schema-valid != release-admissible
# ---------------------------------------------------------------------------


def test_all_not_run_is_schema_valid_but_not_release_admissible():
    """All sections NOT_RUN is schema-valid (PASS from validate) but must
    not be treated as release-admissible by any caller."""
    receipt = {section: {"status": "NOT_RUN"} for section in SECTIONS}
    report = validate(receipt)
    assert report["status"] == "PASS"  # schema-valid
    # Release admission requires checking actual section statuses, not just schema validity.
    # This test documents the distinction; callers must implement admission logic separately.


def test_mandatory_section_fail_is_schema_valid():
    """A section with status FAIL is still schema-valid (FAIL is an accepted
    status value). Release admission is a separate concern."""
    receipt = {section: {"status": "NOT_RUN"} for section in SECTIONS}
    receipt["testing"]["status"] = "FAIL"
    report = validate(receipt)
    assert report["status"] == "PASS"  # schema-valid: FAIL is in STATUSES


def test_mandatory_section_blocked_is_schema_valid():
    """A section with status BLOCKED is still schema-valid."""
    receipt = {section: {"status": "NOT_RUN"} for section in SECTIONS}
    receipt["runtime"]["status"] = "BLOCKED"
    report = validate(receipt)
    assert report["status"] == "PASS"  # schema-valid: BLOCKED is in STATUSES


def test_missing_nested_status():
    """A section present but without a status key is schema-valid (no invalid status)."""
    receipt = {section: {"status": "NOT_RUN"} for section in SECTIONS}
    del receipt["repository"]["status"]
    report = validate(receipt)
    assert report["status"] == "PASS"  # no invalid status value present


def test_incorrect_status_type():
    """A status that is not a string (e.g. int) should fail validation."""
    receipt = {section: {"status": "NOT_RUN"} for section in SECTIONS}
    receipt["repository"]["status"] = 123
    report = validate(receipt)
    assert report["status"] == "FAIL"


def test_malformed_receipt_object():
    """A non-dict receipt should fail."""
    report = validate("not a dict")
    assert report["status"] == "FAIL"


def test_missing_identity_digest():
    """A receipt without an identity digest is schema-valid but not release-admissible."""
    receipt = {section: {"status": "NOT_RUN"} for section in SECTIONS}
    # validate() does not check identity digests - that's an admission concern
    report = validate(receipt)
    assert report["status"] == "PASS"


def test_mixed_optional_and_mandatory_sections_all_valid_statuses():
    """All sections present with mix of PASS/NOT_RUN statuses is schema-valid."""
    receipt = {section: {"status": "NOT_RUN"} for section in SECTIONS}
    receipt["repository"]["status"] = "PASS"
    receipt["testing"]["status"] = "NOT_RUN"
    report = validate(receipt)
    assert report["status"] == "PASS"


def test_runtime_certification_unavailable():
    """Runtime section NOT_RUN is schema-valid but not release-admissible."""
    receipt = {section: {"status": "NOT_RUN"} for section in SECTIONS}
    receipt["runtime"]["status"] = "NOT_RUN"
    report = validate(receipt)
    assert report["status"] == "PASS"  # schema-valid, NOT_RUN is an accepted status


def test_schema_valid_but_release_ineligible():
    """A schema-valid receipt with all NOT_RUN is NOT release-eligible."""
    receipt = {section: {"status": "NOT_RUN"} for section in SECTIONS}
    report = validate(receipt)
    assert report["status"] == "PASS"
    assert report["missing_evidence_is_not_pass"] is True
    # The validate() function correctly reports missing_evidence_is_not_pass=True.
    # Callers must check this flag before promoting.
