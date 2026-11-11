# -*- coding: utf-8 -*-
"""
Tests for tools/verify_import_authority.py (G1 import-authority fix).

Covers:
- Correct source checkout: PASS
- Wrong-origin detection: FAIL
- Missing namespace: FAIL
- No-origin (namespace package): FAIL
- _is_within path containment (positive and negative)
- Third-party dependencies are not checked (out of scope)
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

from tools.verify_import_authority import (
    REPO_OWNED_NAMESPACES,
    _expected_source_root,
    _is_within,
    verify_import_authority,
)


# ---------------------------------------------------------------------------
# _is_within path containment
# ---------------------------------------------------------------------------

def test_is_within_positive(tmp_path):
    child = tmp_path / "sub" / "file.py"
    child.parent.mkdir(parents=True)
    child.write_text("x")
    assert _is_within(child, tmp_path) is True


def test_is_within_negative_outside(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x")
    assert _is_within(outside, tmp_path) is False


def test_is_within_negative_sibling(tmp_path):
    sibling = tmp_path.parent / "sibling" / "file.py"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("x")
    assert _is_within(sibling, tmp_path) is False


def test_is_within_negative_outside_parent(tmp_path):
    # A file in the parent directory is outside tmp_path
    outside = tmp_path.parent / "escape.txt"
    outside.write_text("x")
    assert _is_within(outside, tmp_path) is False


# ---------------------------------------------------------------------------
# verify_import_authority on the real checkout
# ---------------------------------------------------------------------------

def test_verify_correct_checkout_passes():
    """The real checkout must pass: ultimate_pipeline resolves from here."""
    result = verify_import_authority(expected_root=_expected_source_root())
    assert result["passed"] is True
    assert result["failures"] == []
    # expected_root should be the repository root (parent of tools/)
    assert Path(result["expected_root"]).name == "carla_-main"


def test_verify_wrong_root_fails():
    """A wrong expected root must fail because ultimate_pipeline is elsewhere."""
    wrong_root = Path("/nonexistent/wrong/root")
    result = verify_import_authority(expected_root=wrong_root)
    assert result["passed"] is False
    assert len(result["failures"]) == 1
    f = result["failures"][0]
    assert f["namespace"] == "ultimate_pipeline"
    assert f["status"] == "WRONG_ORIGIN"


# ---------------------------------------------------------------------------
# Namespace resolution edge cases
# ---------------------------------------------------------------------------

def test_missing_namespace_reported(monkeypatch):
    """A repository-owned namespace that resolves outside the root is a failure."""
    # Simulate a wrong origin by monkeypatching importlib.import_module
    import tools.verify_import_authority as mod

    real_import = mod.importlib.import_module

    def fake_import(name, *args, **kwargs):
        module = real_import(name, *args, **kwargs)
        if name == "ultimate_pipeline":
            # Pretend it resolves outside the expected root
            module.__file__ = "/outside/root/ultimate_pipeline/__init__.py"
        return module

    monkeypatch.setattr(mod.importlib, "import_module", fake_import)
    try:
        result = verify_import_authority(expected_root=_expected_source_root())
        assert result["passed"] is False
        assert any(
            f["namespace"] == "ultimate_pipeline" and f["status"] == "WRONG_ORIGIN"
            for f in result["failures"]
        )
    finally:
        monkeypatch.undo()


def test_no_origin_namespace_reported(monkeypatch):
    """A namespace with no __file__ is reported as NO_ORIGIN."""
    # Create a fake module with no __file__
    fake = types.ModuleType("ultimate_pipeline")
    # No __file__ attribute
    sys.modules["ultimate_pipeline"] = fake
    try:
        # importlib.import_module will return the cached module
        result = verify_import_authority(expected_root=_expected_source_root())
        assert result["passed"] is False
        assert any(f["namespace"] == "ultimate_pipeline" and f["status"] == "NO_ORIGIN" for f in result["failures"])
    finally:
        del sys.modules["ultimate_pipeline"]
        # Restore the real module
        importlib.import_module("ultimate_pipeline")


# ---------------------------------------------------------------------------
# Third-party dependencies are out of scope
# ---------------------------------------------------------------------------

def test_third_party_not_checked():
    """Third-party packages are not in REPO_OWNED_NAMESPACES and not checked."""
    assert "ultimate_pipeline" in REPO_OWNED_NAMESPACES
    # Common third-party deps are deliberately absent
    for ns in ("numpy", "pytest", "yaml", "requests"):
        assert ns not in REPO_OWNED_NAMESPACES


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_passes(capsys, monkeypatch):
    """CLI exits 0 and prints PASS for the correct checkout."""
    from tools.verify_import_authority import main
    rc = main(["--json"])
    assert rc == 0
    captured = capsys.readouterr()
    import json
    result = json.loads(captured.out)
    assert result["passed"] is True


def test_cli_fails_wrong_root(capsys, monkeypatch):
    """CLI exits non-zero for a wrong root."""
    from tools.verify_import_authority import main
    rc = main(["--expected-root", "/nonexistent", "--json"])
    assert rc != 0
    captured = capsys.readouterr()
    import json
    result = json.loads(captured.out)
    assert result["passed"] is False
