# -*- coding: utf-8 -*-
"""V5 / NEW-207 (E24): exact-artifact CARLA runtime identity contract.

These tests exercise the PRE-RUNTIME identity gate only. They deliberately do
not require a CARLA server: the point of E24 is that an unbound or mismatched
candidate is rejected *before* any live certification is attempted.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ultimate_pipeline.tools.repo_health import (
    CANDIDATE_MANIFEST_SCHEMA,
    CANDIDATE_REQUIRED_FIELDS,
    RUNTIME_CERT_STATES,
    STATUS_PASS,
    main,
    validate_candidate_manifest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_manifest(root: Path, *, repo_sha: str = "a" * 40) -> tuple[Path, dict]:
    root.mkdir(parents=True, exist_ok=True)
    xodr = root / "map.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    payload = {
        "schema": CANDIDATE_MANIFEST_SCHEMA,
        "repo_sha": repo_sha,
        "candidate_id": "cand-001",
        "xodr_path": "map.xodr",
        "xodr_sha256": _sha256(xodr),
        "map_registry_id": "auto_map_of_record",
        "carla_client_version": "0.9.16",
        "carla_server_version": "0.9.16",
        "ue_build": "UE4.26-CARLA0916",
        "import_package_sha256": "b" * 64,
        "cooked_package_sha256": "c" * 64,
        "cook_manifest_sha256": "d" * 64,
        "runtime_map": "AutoMap",
    }
    path = root / "candidate_manifest.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path, payload


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_valid_candidate_passes(tmp_path):
    path, _ = _valid_manifest(tmp_path)
    result = validate_candidate_manifest(path, expected_repo_sha="a" * 40)
    assert result["state"] == STATUS_PASS, result["problems"]
    assert result["problems"] == []
    # the manifest digest is recorded so the receipt can bind to it
    assert len(result["manifest_sha256"]) == 64
    assert result["xodr_sha256_recomputed"] == _sha256(tmp_path / "map.xodr")


def test_relative_xodr_path_resolves_against_manifest_dir(tmp_path):
    path, _ = _valid_manifest(tmp_path)
    assert validate_candidate_manifest(path)["state"] == STATUS_PASS


def test_absolute_xodr_path_is_accepted(tmp_path):
    xodr = tmp_path / "map.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    payload = {**_valid_manifest(tmp_path)[1], "xodr_path": str(xodr)}
    (tmp_path / "candidate_manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    assert validate_candidate_manifest(tmp_path / "candidate_manifest.json")["state"] == STATUS_PASS


# ---------------------------------------------------------------------------
# identity mismatch attacks
# ---------------------------------------------------------------------------


def test_missing_manifest_is_identity_mismatch(tmp_path):
    result = validate_candidate_manifest(tmp_path / "nope.json")
    assert result["state"] == "IDENTITY_MISMATCH"
    assert any("not found" in p["reason"] for p in result["problems"])


def test_corrupt_manifest_is_identity_mismatch(tmp_path):
    path = tmp_path / "candidate_manifest.json"
    path.write_text("{not json", encoding="utf-8")
    result = validate_candidate_manifest(path)
    assert result["state"] == "IDENTITY_MISMATCH"


def test_wrong_schema_rejected(tmp_path):
    path, payload = _valid_manifest(tmp_path)
    payload["schema"] = "SOMETHING_ELSE/v9"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_candidate_manifest(path)
    assert result["state"] == "IDENTITY_MISMATCH"
    assert any(p["field"] == "schema" for p in result["problems"])


def test_wrong_repo_sha_rejected(tmp_path):
    path, _ = _valid_manifest(tmp_path, repo_sha="a" * 40)
    result = validate_candidate_manifest(path, expected_repo_sha="f" * 40)
    assert result["state"] == "IDENTITY_MISMATCH"
    assert any(p["field"] == "repo_sha" for p in result["problems"])


def test_wrong_xodr_content_rejected(tmp_path):
    """Correct workflow, wrong XODR: the hash binding must catch it."""
    path, _ = _valid_manifest(tmp_path)
    (tmp_path / "map.xodr").write_text("<OpenDRIVE><!--different-->", encoding="utf-8")
    result = validate_candidate_manifest(path)
    assert result["state"] == "IDENTITY_MISMATCH"
    assert any(p["field"] == "xodr_sha256" for p in result["problems"])


def test_missing_xodr_file_rejected(tmp_path):
    path, _ = _valid_manifest(tmp_path)
    (tmp_path / "map.xodr").unlink()
    result = validate_candidate_manifest(path)
    assert result["state"] == "IDENTITY_MISMATCH"
    assert any(p["field"] == "xodr_path" for p in result["problems"])


def test_stale_manifest_after_map_change_rejected(tmp_path):
    """A manifest that predates an artifact change must not certify it."""
    path, _ = _valid_manifest(tmp_path)
    (tmp_path / "map.xodr").write_text("<OpenDRIVE/><mutated/>", encoding="utf-8")
    assert validate_candidate_manifest(path)["state"] == "IDENTITY_MISMATCH"


@pytest.mark.parametrize("field", ["carla_client_version", "carla_server_version"])
def test_wrong_carla_version_rejected(tmp_path, field):
    path, payload = _valid_manifest(tmp_path)
    payload[field] = "0.9.10"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_candidate_manifest(path, expected_carla_version="0.9.16")
    assert result["state"] == "IDENTITY_MISMATCH"
    assert any(p["field"] == field for p in result["problems"])


@pytest.mark.parametrize("field", CANDIDATE_REQUIRED_FIELDS)
def test_every_required_field_is_enforced(tmp_path, field):
    path, payload = _valid_manifest(tmp_path)
    del payload[field]
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_candidate_manifest(path)
    assert result["state"] == "IDENTITY_MISMATCH"
    assert any(p["field"] == field for p in result["problems"]), (
        f"omitting {field} must be a hard failure, not a warning"
    )


@pytest.mark.parametrize("field", CANDIDATE_REQUIRED_FIELDS)
def test_empty_required_field_is_enforced(tmp_path, field):
    path, payload = _valid_manifest(tmp_path)
    payload[field] = "   "
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_candidate_manifest(path)
    assert result["state"] == "IDENTITY_MISMATCH"


def test_tampered_manifest_changes_its_digest(tmp_path):
    path, payload = _valid_manifest(tmp_path)
    before = validate_candidate_manifest(path)["manifest_sha256"]
    payload["candidate_id"] = "cand-002"
    path.write_text(json.dumps(payload), encoding="utf-8")
    after = validate_candidate_manifest(path)["manifest_sha256"]
    assert before != after


# ---------------------------------------------------------------------------
# state vocabulary
# ---------------------------------------------------------------------------


def test_blocked_external_is_not_a_pass_state():
    assert "BLOCKED_EXTERNAL" in RUNTIME_CERT_STATES
    assert "BLOCKED_EXTERNAL" != STATUS_PASS


def test_identity_mismatch_is_a_distinct_state():
    assert "IDENTITY_MISMATCH" in RUNTIME_CERT_STATES
    assert "IDENTITY_MISMATCH" not in (STATUS_PASS,)


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_cli_validate_candidate_exit_codes(tmp_path):
    path, _ = _valid_manifest(tmp_path)
    assert main(["--validate-candidate", str(path), "--expected-repo-sha", "a" * 40]) == 0

    bad, _ = _valid_manifest(tmp_path / "b", repo_sha="a" * 40)
    assert main(["--validate-candidate", str(bad), "--expected-repo-sha", "f" * 40]) == 1

    assert main(["--validate-candidate", str(tmp_path / "missing.json")]) == 1


def test_cli_validate_candidate_emits_json(tmp_path, capsys):
    path, _ = _valid_manifest(tmp_path)
    main(["--validate-candidate", str(path), "--expected-repo-sha", "a" * 40, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == STATUS_PASS
    assert payload["schema"] == "CANDIDATE_IDENTITY_GATE/v1"


def test_cli_against_real_checked_out_sha(tmp_path):
    """The gate must accept a manifest bound to THIS repository's real SHA."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(_repo_root()),
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    xodr = tmp_path / "map.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    payload = {
        "schema": CANDIDATE_MANIFEST_SCHEMA,
        "repo_sha": head,
        "candidate_id": "cand-real",
        "xodr_path": str(xodr),
        "xodr_sha256": _sha256(xodr),
        "map_registry_id": "auto_map_of_record",
        "carla_client_version": "0.9.16",
        "carla_server_version": "0.9.16",
        "ue_build": "UE4.26-CARLA0916",
        "import_package_sha256": "b" * 64,
        "cooked_package_sha256": "c" * 64,
        "cook_manifest_sha256": "d" * 64,
        "runtime_map": "AutoMap",
    }
    path = tmp_path / "candidate_manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_candidate_manifest(path, expected_repo_sha=head)
    assert result["state"] == STATUS_PASS, result["problems"]
