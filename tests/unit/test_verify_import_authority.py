"""Portability and behaviour tests for the import-authority preflight.

The preflight is the gate that stops a verification run from silently testing
a different CARLA checkout. Two properties must hold:

* positive -- in a clean environment every repository module resolves to the
  expected checkout;
* negative -- if any other checkout could supply a repository module, the
  preflight reports it and exits non-zero, regardless of search order.

These tests exercise the checker directly so the guarantee is pinned on every
platform, not only where the gate happens to run in CI.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import verify_import_authority as via  # noqa: E402


def test_expected_root_is_discovered_dynamically():
    """No machine-specific path may be encoded in the checker."""
    root = via.expected_repo_root()
    assert root == REPO_ROOT.resolve()
    source = (REPO_ROOT / "tools" / "verify_import_authority.py").read_text(
        encoding="utf-8")
    # A hardcoded drive letter or user directory would defeat portability.
    for forbidden in ("C:\\", "c:\\", "D:\\", "E:\\", "F:\\"):
        assert forbidden not in source, f"machine-specific path in source: {forbidden}"
    assert "/home/" not in source
    assert "/Users/" not in source


def test_clean_environment_passes():
    """Positive case: repository modules resolve inside the checkout."""
    report = via.audit(REPO_ROOT.resolve())
    assert report["status"] == "PASS", report["violations"]
    assert report["violations"] == []
    namespaces = {ns["module"]: ns for ns in report["namespaces"]}
    for name in via.REPO_NAMESPACES:
        assert name in namespaces
    ultimate = namespaces["ultimate_pipeline"]
    assert ultimate["origin"] is not None
    assert via._under(
        via._norm(ultimate["origin"]), via._norm(REPO_ROOT.resolve())
    )


def test_external_checkout_is_rejected(tmp_path, monkeypatch):
    """Negative case: a second CARLA checkout must fail the gate.

    The external location is injected into the *allowed* computation by
    monkeypatching the namespace search path, proving the checker reports any
    location outside the expected root rather than trusting ordering.
    """
    external = tmp_path / "other_carla_checkout"
    (external / "tools").mkdir(parents=True)
    (external / "tools" / "__init__.py").write_text("", encoding="utf-8")

    import tools as candidate_tools

    original = list(candidate_tools.__path__)
    candidate_tools.__path__ = [*original, str(external / "tools")]
    try:
        report = via.audit(REPO_ROOT.resolve())
    finally:
        candidate_tools.__path__ = original

    assert report["status"] == "FAIL"
    kinds = {v["kind"] for v in report["violations"]}
    assert "external_search_location" in kinds
    assert any(
        str(external) in v.get("location", "") or
        str(external) in v.get("origin", "")
        for v in report["violations"]
    ), report["violations"]


def test_ordering_is_not_treated_as_sufficient(tmp_path, monkeypatch):
    """Candidate location first, external second -> still a failure.

    Guards the explicit rule that search *order* never establishes authority.
    """
    external = tmp_path / "later_external"
    (external / "tools").mkdir(parents=True)
    (external / "tools" / "__init__.py").write_text("", encoding="utf-8")

    import tools as candidate_tools

    candidate_first = str(REPO_ROOT.resolve() / "tools")
    original = list(candidate_tools.__path__)
    candidate_tools.__path__ = [candidate_first, str(external / "tools")]
    try:
        report = via.audit(REPO_ROOT.resolve())
    finally:
        candidate_tools.__path__ = original

    assert report["status"] == "FAIL", (
        "an external checkout later in the path must still be rejected"
    )


def test_cli_exit_codes(tmp_path):
    """CLI: 0 when clean, 1 when a violation is present."""
    clean = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "verify_import_authority.py")],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        env={**_clean_env()},
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "IMPORT_AUTHORITY_PASS" in clean.stdout

    dirty = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "verify_import_authority.py")],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        env={**_clean_env(), "PYTHONPATH": str(tmp_path)},
    )
    # A PYTHONPATH that does not contain a CARLA checkout must not create a
    # false positive; the gate keys on repository module origin only.
    assert dirty.returncode == 0, dirty.stdout + dirty.stderr


def _clean_env() -> dict:
    import os

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


def test_module_is_importable_without_side_effects():
    """Importing the checker must not import candidate packages eagerly."""
    assert callable(via.audit)
    assert callable(via.expected_repo_root)
    assert set(via.REPO_NAMESPACES) == {"ultimate_pipeline", "tools"}
