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
