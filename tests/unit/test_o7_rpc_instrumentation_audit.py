"""Tests for O7 RPC source-availability audit."""
from __future__ import annotations

import json
from pathlib import Path


def test_rpc_audit_is_incomplete_without_carla_source():
    path = Path("RPC_STARTUP_INSTRUMENTATION_AUDIT.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "INCOMPLETE"
    assert data["source_present"] is False
    assert data["instrumentation_applied"] is False


def test_rpc_audit_does_not_claim_build():
    data = json.loads(Path("RPC_STARTUP_INSTRUMENTATION_AUDIT.json").read_text(encoding="utf-8"))
    assert data["build_attempted"] is False
    assert data["no_invented_fix"] is True
