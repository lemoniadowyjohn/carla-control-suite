# -*- coding: utf-8 -*-
"""
G2 regression tests: candidate manifest SHA-256 digest format validation.

Covers:
- Invalid SHA-256 hex formats are rejected (not-a-hex-string, wrong length,
  uppercase, non-hex characters).
- Invalid git SHA (repo_sha) formats are rejected.
- Well-formed digests still pass format validation.
- XODR byte verification still works for locally available artifacts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ultimate_pipeline.tools.repo_health import (
    CANDIDATE_MANIFEST_SCHEMA,
    validate_candidate_manifest,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_manifest(root: Path, **overrides) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    xodr = root / "map.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    payload = {
        "schema": CANDIDATE_MANIFEST_SCHEMA,
        "repo_sha": "a" * 40,
        "candidate_id": "cand-001",
        "xodr_path": "map.xodr",
        "xodr_sha256": _sha256(b"<OpenDRIVE/>"),
        "map_registry_id": "auto_map_of_record",
        "carla_client_version": "0.9.16",
        "carla_server_version": "0.9.16",
        "ue_build": "UE4.26-CARLA0916",
        "import_package_sha256": "b" * 64,
        "cooked_package_sha256": "c" * 64,
        "cook_manifest_sha256": "d" * 64,
        "runtime_map": "AutoMap",
    }
    payload.update(overrides)
    path = root / "candidate_manifest.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Invalid SHA-256 formats are rejected
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "field,invalid_value",
    [
        ("xodr_sha256", "not-a-hex-string"),
        ("xodr_sha256", "z" * 64),
        ("xodr_sha256", "B" * 64),  # uppercase
        ("xodr_sha256", "b" * 63),  # too short
        ("xodr_sha256", "b" * 65),  # too long
        ("xodr_sha256", ""),
        ("import_package_sha256", "not-a-hex-string"),
        ("import_package_sha256", "z" * 64),
        ("cooked_package_sha256", "not-a-hex-string"),
        ("cook_manifest_sha256", "not-a-hex-string"),
    ],
)
def test_invalid_sha256_format_rejected(tmp_path, field, invalid_value):
    path = _make_manifest(tmp_path, **{field: invalid_value})
    result = validate_candidate_manifest(path, expected_repo_sha="a" * 40)
    assert result["state"] == "IDENTITY_MISMATCH", result["problems"]
    assert any(p["field"] == field for p in result["problems"]), (
        f"{field}={invalid_value!r} must be rejected as invalid SHA-256"
    )


# ---------------------------------------------------------------------------
# Invalid git SHA (repo_sha) is rejected
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "invalid_value",
    [
        "not-a-git-sha",
        "z" * 40,
        "A" * 40,  # uppercase
        "a" * 39,  # too short
        "a" * 41,  # too long
        "",
    ],
)
def test_invalid_git_sha_rejected(tmp_path, invalid_value):
    path = _make_manifest(tmp_path, repo_sha=invalid_value)
    result = validate_candidate_manifest(path, expected_repo_sha="a" * 40)
    assert result["state"] == "IDENTITY_MISMATCH", result["problems"]
    assert any(p["field"] == "repo_sha" for p in result["problems"]), (
        f"repo_sha={invalid_value!r} must be rejected as invalid git SHA"
    )


# ---------------------------------------------------------------------------
# Well-formed digests still pass format validation
# ---------------------------------------------------------------------------

def test_well_formed_sha256_passes_format_check(tmp_path):
    """Valid-format digests pass format validation (byte verification of
    package digests happens later when artifacts are available)."""
    path = _make_manifest(tmp_path)
    result = validate_candidate_manifest(path, expected_repo_sha="a" * 40)
    assert result["state"] == "PASS", result["problems"]


# ---------------------------------------------------------------------------
# XODR byte verification still works for locally available artifacts
# ---------------------------------------------------------------------------

def test_xodr_byte_verification_catches_wrong_hash(tmp_path):
    """XODR digest is verified against actual file bytes when available."""
    xodr = tmp_path / "map.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    wrong_sha = "0" * 64
    path = _make_manifest(tmp_path, xodr_sha256=wrong_sha)
    result = validate_candidate_manifest(path, expected_repo_sha="a" * 40)
    assert result["state"] == "IDENTITY_MISMATCH"
    assert any(p["field"] == "xodr_sha256" for p in result["problems"])
