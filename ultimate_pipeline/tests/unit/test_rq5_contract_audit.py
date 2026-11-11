#!/usr/bin/env python3
"""CHAT-09 / B3: test that --contract fallback is eliminated.

The bug: tools/rq5_contract_audit.py silently fell back to DEFAULT_CONTRACT
when the explicit --contract path didn't exist.
The fix: explicit --contract must exist, else FileNotFoundError.
"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.rq5_contract_audit import audit


def test_explicit_contract_must_exist():
    """Explicit --contract path that doesn't exist raises FileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        missing = repo / "missing_contract.json"
        try:
            audit(repo, contract=missing)
            raise AssertionError("Should have raised FileNotFoundError")
        except FileNotFoundError as e:
            assert "Explicit --contract path does not exist" in str(e)
            assert "missing_contract.json" in str(e)
    print("PASS: explicit missing contract raises FileNotFoundError")


def test_no_contract_falls_back():
    """Without explicit --contract, falls back to repo config then DEFAULT then legacy."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        # Create the repo-local contract
        (repo / "configs").mkdir(parents=True)
        (repo / "configs" / "rq5_protocol_freeze_v1.json").write_text(
            '{"protocol_version": "test", "schema": "rq5_protocol_freeze_v1"}', encoding='utf-8'
        )
        # Should use the repo-local contract
        result = audit(repo)
        assert result.get("contract_schema") == "rq5_protocol_freeze_v1"
        assert result.get("contract_path", "").endswith("rq5_protocol_freeze_v1.json")
        print("PASS: no explicit contract uses repo-local config")


def test_no_contract_no_repo_uses_legacy():
    """Without any contract file, uses legacy audit."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        # No configs/rq5_protocol_freeze_v1.json
        result = audit(repo)
        # Legacy audit returns a dict with "decisions" key
        assert "decisions" in result or "status" in result
        print("PASS: no contract falls back to legacy audit")


if __name__ == "__main__":
    test_explicit_contract_must_exist()
    test_no_contract_falls_back()
    test_no_contract_no_repo_uses_legacy()
    print("\n=== B3 contract fallback tests: ALL PASS ===")