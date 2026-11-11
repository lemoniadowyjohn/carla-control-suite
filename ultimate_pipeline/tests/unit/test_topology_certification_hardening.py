# ultimate_pipeline/tests/unit/test_topology_certification_hardening.py
# -*- coding: utf-8 -*-
"""
Regression tests for G4 topology certification hardening.

Covers non-finite and out-of-range fraction/threshold inputs that must
never authorize a PASS status (fail-closed), plus git SHA provenance
binding to the module's own repository.
"""
from __future__ import annotations

import math
import os
import subprocess

import pytest

from ultimate_pipeline.contracts.stage_contracts import QualityStatus
from ultimate_pipeline.quality.topology_certification import certify_topology


def _literal(fraction: float) -> dict:
    return {"graph_source": "LITERAL_SPEC", "largest_component_fraction": fraction}


def _recovered(fraction: float) -> dict:
    return {"graph_source": "RECOVERED_DIAGNOSTIC", "largest_component_fraction": fraction}


# ---------------------------------------------------------------------------
# Non-finite / out-of-range fraction values must never authorize PASS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "fraction",
    [
        float("inf"),
        float("-inf"),
        float("nan"),
        -0.5,
        1.5,
        2.0,
        -1.0,
    ],
)
def test_invalid_fraction_never_passes(fraction):
    result = certify_topology(
        literal_summary=_literal(fraction),
        recovered_summary=_recovered(0.99),
    )
    assert result["SPEC_TOPOLOGY"] == QualityStatus.INCOMPLETE.value, (
        f"fraction={fraction!r} must not authorize PASS, got {result['SPEC_TOPOLOGY']!r}"
    )


# ---------------------------------------------------------------------------
# Invalid thresholds must never authorize PASS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "threshold",
    [
        float("inf"),
        float("-inf"),
        float("nan"),
        -0.5,
        1.5,
        -1.0,
    ],
)
def test_invalid_threshold_never_passes(threshold):
    result = certify_topology(
        literal_summary=_literal(0.99),
        recovered_summary=_recovered(0.99),
        fraction_threshold=threshold,
    )
    assert result["SPEC_TOPOLOGY"] == QualityStatus.INCOMPLETE.value, (
        f"threshold={threshold!r} must not authorize PASS, got {result['SPEC_TOPOLOGY']!r}"
    )


# ---------------------------------------------------------------------------
# Boundary values within [0, 1] behave correctly
# ---------------------------------------------------------------------------

def test_fraction_zero_is_valid_but_fails():
    result = certify_topology(
        literal_summary=_literal(0.0),
        recovered_summary=_recovered(0.99),
        fraction_threshold=0.95,
    )
    assert result["SPEC_TOPOLOGY"] == QualityStatus.FAIL.value


def test_fraction_one_is_valid_and_passes():
    result = certify_topology(
        literal_summary=_literal(1.0),
        recovered_summary=_recovered(1.0),
        fraction_threshold=0.95,
    )
    assert result["SPEC_TOPOLOGY"] == QualityStatus.PASS.value


def test_threshold_zero_passes_any_valid_fraction():
    result = certify_topology(
        literal_summary=_literal(0.0),
        recovered_summary=_recovered(0.0),
        fraction_threshold=0.0,
    )
    assert result["SPEC_TOPOLOGY"] == QualityStatus.PASS.value


def test_threshold_one_requires_fraction_one():
    result = certify_topology(
        literal_summary=_literal(0.99),
        recovered_summary=_recovered(0.99),
        fraction_threshold=1.0,
    )
    assert result["SPEC_TOPOLOGY"] == QualityStatus.FAIL.value

    result = certify_topology(
        literal_summary=_literal(1.0),
        recovered_summary=_recovered(1.0),
        fraction_threshold=1.0,
    )
    assert result["SPEC_TOPOLOGY"] == QualityStatus.PASS.value


# ---------------------------------------------------------------------------
# Valid baseline still works
# ---------------------------------------------------------------------------

def test_valid_baseline_passes():
    result = certify_topology(
        literal_summary=_literal(0.99),
        recovered_summary=_recovered(0.99),
    )
    assert result["SPEC_TOPOLOGY"] == QualityStatus.PASS.value
    assert result["RECOVERY_DIAGNOSTIC"] == QualityStatus.PASS.value


# ---------------------------------------------------------------------------
# Git SHA provenance binds to module's repository, not cwd
# ---------------------------------------------------------------------------

def test_git_sha_matches_module_repo():
    """_get_git_sha must return the SHA of the ultimate_pipeline repo."""
    from ultimate_pipeline.quality.topology_certification import _get_git_sha

    sha = _get_git_sha()
    assert sha, "git SHA must not be empty"

    # Compute expected SHA by running git in the module's repo root
    module_dir = os.path.dirname(os.path.abspath(
        __import__("ultimate_pipeline.quality.topology_certification", fromlist=["x"]).__file__
    ))
    repo_root = os.path.abspath(os.path.join(module_dir, "..", ".."))
    expected = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stderr=subprocess.DEVNULL,
        text=True,
    ).strip()
    assert sha == expected, (
        f"git SHA {sha!r} does not match module repo {expected!r}"
    )
