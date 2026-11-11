# V4-A — G2 mutation-sensitivity gap fix
#
# The existing test test_invalid_sha256_format_rejected[xodr_sha256-not-a-hex-string]
# conflates SHA-256 format validation with XODR byte verification: when the
# XODR file exists with different content, BOTH the format check AND the byte
# check fail. A mutant that accepts non-hex strings still fails because byte
# verification catches it.
#
# To isolate format validation, we test import_package_sha256 and
# cooked_package_sha256 — package digests that have NO byte verification,
# only format validation. An invalid format here fails purely on format
# grounds.
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ultimate_pipeline.tools.repo_health import (
    CANDIDATE_MANIFEST_SCHEMA,
    validate_candidate_manifest,
)


def test_invalid_package_sha256_format_isolated_from_byte_verification(tmp_path):
    """import_package_sha256 with invalid format fails even when XODR is valid.

    Package digests (import_package_sha256, cooked_package_sha256,
    cook_manifest_sha256) have NO byte verification — only format validation.
    So an invalid format here fails purely on format grounds.
    """
    xodr = tmp_path / "map.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    xodr_sha = hashlib.sha256(b"<OpenDRIVE/>").hexdigest()

    payload = {
        "schema": CANDIDATE_MANIFEST_SCHEMA,
        "repo_sha": "a" * 40,
        "candidate_id": "cand-001",
        "xodr_path": "map.xodr",
        "xodr_sha256": xodr_sha,  # valid format, correct bytes
        "map_registry_id": "auto_map_of_record",
        "carla_client_version": "0.9.16",
        "carla_server_version": "0.9.16",
        "ue_build": "UE4.26-CARLA0916",
        "import_package_sha256": "not-a-hex-string",  # invalid format only
        "cooked_package_sha256": "c" * 64,
        "cook_manifest_sha256": "d" * 64,
        "runtime_map": "AutoMap",
    }
    path = tmp_path / "candidate_manifest.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = validate_candidate_manifest(path, expected_repo_sha="a" * 40)
    assert result["state"] == "IDENTITY_MISMATCH", result["problems"]
    assert any(
        p["field"] == "import_package_sha256"
        and "SHA-256" in p["reason"]
        for p in result["problems"]
    ), (
        f"import_package_sha256='not-a-hex-string' must fail format validation: "
        f"{result['problems']}"
    )


def test_invalid_cooked_package_sha256_format_isolated(tmp_path):
    """cooked_package_sha256 with invalid format fails on format alone."""
    xodr = tmp_path / "map.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    xodr_sha = hashlib.sha256(b"<OpenDRIVE/>").hexdigest()

    payload = {
        "schema": CANDIDATE_MANIFEST_SCHEMA,
        "repo_sha": "a" * 40,
        "candidate_id": "cand-001",
        "xodr_path": "map.xodr",
        "xodr_sha256": xodr_sha,
        "map_registry_id": "auto_map_of_record",
        "carla_client_version": "0.9.16",
        "carla_server_version": "0.9.16",
        "ue_build": "UE4.26-CARLA0916",
        "import_package_sha256": "b" * 64,
        "cooked_package_sha256": "not-a-hex-string",  # invalid format only
        "cook_manifest_sha256": "d" * 64,
        "runtime_map": "AutoMap",
    }
    path = tmp_path / "candidate_manifest.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = validate_candidate_manifest(path, expected_repo_sha="a" * 40)
    assert result["state"] == "IDENTITY_MISMATCH", result["problems"]
    assert any(
        p["field"] == "cooked_package_sha256"
        and "SHA-256" in p["reason"]
        for p in result["problems"]
    ), (
        f"cooked_package_sha256='not-a-hex-string' must fail format validation: "
        f"{result['problems']}"
    )
