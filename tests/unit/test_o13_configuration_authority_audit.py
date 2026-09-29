"""Tests for O13 configuration authority audit."""
from __future__ import annotations

from tools.configuration_authority_audit import build_audit


def test_audit_binds_current_registry():
    audit = build_audit()
    assert audit["map_sha256"]
    assert audit["map_registry_sha256"]


def test_required_settings_are_classified():
    names = {row["setting"] for row in build_audit()["rows"]}
    assert {"authoritative automatic map", "CRS/header offset", "tile size", "UE4 root", "lane width fallback", "position tolerance"} <= names
    assert all(row["category"] in {"A", "B", "C", "D", "E"} for row in build_audit()["rows"])


def test_no_global_framework_was_introduced():
    assert "No global config framework" in build_audit()["policy"]
