"""Tests for O20 recovery/resume audit."""
from pathlib import Path

from tools.recovery_resume_audit import audit


def test_all_stages_are_listed():
    report = audit(Path.cwd())
    assert {row["stage"] for row in report["stages"]} == {"tile_generation", "fbx_conversion", "import_staging", "unreal_import", "cook_package"}


def test_audit_does_not_claim_safe_interruption_without_execution():
    report = audit(Path.cwd())
    assert all(row["safe_interruption_tested"] is False for row in report["stages"])
    assert "No Unreal process interrupted" in " ".join(report["limitations"])


def test_current_audit_is_not_production_mutation():
    report = audit(Path.cwd())
    assert "No production artifact was manipulated" in " ".join(report["limitations"])


def test_audit_is_incomplete_while_no_stage_was_actually_interrupted():
    """NEW-247.

    The previous audit reported status=PASS while simultaneously reporting
    ``safe_interruption_tested: false`` for every stage, and while its own
    limitations said no Unreal process was interrupted. PASS was derived only
    from "source file exists AND the text mentions sha256", so an audit that
    never executed an interruption or a recovery could certify recovery.

    A PASS must require that recovery was actually exercised. Until interruption
    tests run, the honest status is INCOMPLETE.
    """
    report = audit(Path.cwd())
    assert not any(row["safe_interruption_tested"] for row in report["stages"])
    assert report["status"] != "PASS"
    assert report["status"] == "INCOMPLETE"
    assert set(report["safe_interruption_untested_stages"]) == {
        row["stage"] for row in report["stages"]
    }


def test_audit_pass_requires_executed_interruption_and_resume_capability():
    """The documented PASS criteria must be enforced, not just described."""
    report = audit(Path.cwd())
    criteria = report["pass_criteria"].lower()
    assert "actually interrupted" in criteria
    assert "never yield pass" in criteria or "can never yield pass" in criteria
    # A stage with no checkpoint/resume capability is recorded as such rather
    # than being silently treated as recoverable.
    assert "stages_without_resume_capability" in report
