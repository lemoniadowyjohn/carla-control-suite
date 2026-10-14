"""Tests for O14 clean-clone offline audit."""
from __future__ import annotations

from tools.clean_clone_offline_audit import audit_checkout


def test_current_checkout_is_explicitly_audited():
    report = audit_checkout(__import__("pathlib").Path.cwd())
    assert report["schema"] == "clean_clone_offline_audit/v1"
    assert report["root"]
    assert any(c["check"] == "map_registry" for c in report["checks"])


def test_report_does_not_claim_runtime_or_download():
    report = audit_checkout(__import__("pathlib").Path.cwd())
    assert "No CARLA/UE4 download or build attempted" in " ".join(report["limitations"])
