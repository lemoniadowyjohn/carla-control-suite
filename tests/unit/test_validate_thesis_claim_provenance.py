"""C19 step 3 — validate_thesis_claim_provenance.py: independent re-verification
of every RQ claim's cited artifact, not just re-reading the same claim.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.validate_thesis_claim_provenance import _hash_file, _verify_rq_table_claims, validate


def test_hash_file_detects_algorithm_by_length(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello world")
    sha = hashlib.sha256(b"hello world").hexdigest()
    md5 = hashlib.md5(b"hello world").hexdigest()
    assert _hash_file(p, sha) == sha
    assert _hash_file(p, md5) == md5


def test_deferred_and_missing_rows_need_no_provenance(tmp_path: Path) -> None:
    rq_path = tmp_path / "rq_tables.json"
    rq_path.write_text(json.dumps({"rows": [
        {"rq": "RQ2", "metric": "x", "status": "DEFERRED", "sha256": ""},
        {"rq": "RQ1", "metric": "y", "status": "MISSING", "sha256": ""},
    ]}), encoding="utf-8")
    result = _verify_rq_table_claims(rq_path)
    assert result["ok"] is True
    assert all(c["provenance"] == "n/a (deferred/missing)" for c in result["claims_checked"])


def test_negative_control_hash_mismatch_fails(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "reports" / "post_audit_hardening" / "FAKE"
    evidence_dir.mkdir(parents=True)
    artifact = evidence_dir / "checkpoint.pt"
    artifact.write_bytes(b"real content")
    real_sha = hashlib.sha256(b"real content").hexdigest()
    wrong_sha = hashlib.sha256(b"different content").hexdigest()

    rq_path = tmp_path / "rq_tables.json"
    rq_path.write_text(json.dumps({"rows": [
        {"rq": "RQ3/RQ5", "metric": "gnn", "status": "PROTOTYPE",
         "artifact": "checkpoint.pt", "sha256": wrong_sha},
    ]}), encoding="utf-8")

    import tools.validate_thesis_claim_provenance as mod
    old_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        result = _verify_rq_table_claims(rq_path)
    finally:
        mod.REPO_ROOT = old_root

    assert result["ok"] is False
    assert result["claims_checked"][0]["provenance"] == "FAIL"
    assert "mismatch" in result["claims_checked"][0]["error"]
    assert real_sha  # sanity: fixture actually differs from wrong_sha


def test_negative_control_missing_artifact_fails(tmp_path: Path) -> None:
    rq_path = tmp_path / "rq_tables.json"
    rq_path.write_text(json.dumps({"rows": [
        {"rq": "RQ1", "metric": "x", "status": "BOUNDED",
         "artifact": "does_not_exist.xodr", "sha256": "a" * 64},
    ]}), encoding="utf-8")

    import tools.validate_thesis_claim_provenance as mod
    old_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        result = _verify_rq_table_claims(rq_path)
    finally:
        mod.REPO_ROOT = old_root

    assert result["ok"] is False
    assert "not found" in result["claims_checked"][0]["error"]


def test_negative_control_claim_with_no_hash_flagged_unpinned(tmp_path: Path) -> None:
    rq_path = tmp_path / "rq_tables.json"
    rq_path.write_text(json.dumps({"rows": [
        {"rq": "RQ4", "metric": "explicit_dr_wired", "status": "AUTHORITATIVE", "sha256": ""},
    ]}), encoding="utf-8")
    result = _verify_rq_table_claims(rq_path)
    # ok can still be True (UNPINNED is a documented gap, not a hard failure --
    # not every AUTHORITATIVE claim is about a hashable artifact), but it must
    # be visible in the report, never silently treated as PASS.
    assert result["claims_checked"][0]["provenance"] == "UNPINNED"


def test_claim_citing_a_superseded_pin_sha_still_passes(tmp_path: Path) -> None:
    """A registry promotion (e.g. C29) moves the LIVE pin to a new sha, but historical
    claims computed against the previous pin remain true as long as that file is still on
    disk with the same content -- they must not start failing just because the registry's
    live pointer moved on. Resolved via the registry entry's supersedes_sha256/
    supersedes_path, not by rewriting the historical claim."""
    old_file = tmp_path / "old_pin.xodr"
    old_file.write_bytes(b"old pinned content")
    old_sha = hashlib.sha256(b"old pinned content").hexdigest()

    new_file = tmp_path / "new_pin.xodr"
    new_file.write_bytes(b"new pinned content")
    new_sha = hashlib.sha256(b"new pinned content").hexdigest()

    rq_path = tmp_path / "rq_tables.json"
    rq_path.write_text(json.dumps({"rows": [
        {"rq": "RQ1", "metric": "local_curvature_gap", "status": "BOUNDED",
         "artifact": "old_pin.xodr vs manual.xodr", "sha256": old_sha},
    ]}), encoding="utf-8")

    fake_registry = {
        "auto_map_of_record": {
            "path": "new_pin.xodr", "sha256": new_sha, "bytes": len(b"new pinned content"),
            "role": "auto", "aliases": ["auto_map_of_record"],
            "supersedes_sha256": old_sha, "supersedes_path": "old_pin.xodr",
        },
    }

    import tools.validate_thesis_claim_provenance as mod
    old_root = mod.REPO_ROOT
    old_registry = mod.PINNED_MAP_REGISTRY
    mod.REPO_ROOT = tmp_path
    mod.PINNED_MAP_REGISTRY = fake_registry
    try:
        result = _verify_rq_table_claims(rq_path)
    finally:
        mod.REPO_ROOT = old_root
        mod.PINNED_MAP_REGISTRY = old_registry

    assert result["ok"] is True, result
    assert result["claims_checked"][0]["provenance"] == "PASS"
    assert "superseded" in result["claims_checked"][0]["via"]


def test_claim_citing_a_superseded_sha_fails_if_the_old_file_itself_has_drifted(tmp_path: Path) -> None:
    """The supersession path must still hash-verify the old file -- it's a documented
    escape hatch for legitimate historical claims, not a way to silently skip verification
    of anything whose sha happens to match a supersedes_sha256 value."""
    old_file = tmp_path / "old_pin.xodr"
    old_file.write_bytes(b"DRIFTED content, not what was actually measured")

    rq_path = tmp_path / "rq_tables.json"
    original_old_sha = hashlib.sha256(b"old pinned content").hexdigest()
    rq_path.write_text(json.dumps({"rows": [
        {"rq": "RQ1", "metric": "local_curvature_gap", "status": "BOUNDED",
         "artifact": "old_pin.xodr vs manual.xodr", "sha256": original_old_sha},
    ]}), encoding="utf-8")

    fake_registry = {
        "auto_map_of_record": {
            "path": "new_pin.xodr", "sha256": "b" * 64, "bytes": 0,
            "role": "auto", "aliases": ["auto_map_of_record"],
            "supersedes_sha256": original_old_sha, "supersedes_path": "old_pin.xodr",
        },
    }

    import tools.validate_thesis_claim_provenance as mod
    old_root = mod.REPO_ROOT
    old_registry = mod.PINNED_MAP_REGISTRY
    mod.REPO_ROOT = tmp_path
    mod.PINNED_MAP_REGISTRY = fake_registry
    try:
        result = _verify_rq_table_claims(rq_path)
    finally:
        mod.REPO_ROOT = old_root
        mod.PINNED_MAP_REGISTRY = old_registry

    assert result["ok"] is False
    assert result["claims_checked"][0]["provenance"] == "FAIL"


def test_against_real_repo_pinned_maps_and_inputs_verify() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = validate(repo_root)
    assert all(r["ok"] for r in result["pinned_maps"]), result["pinned_maps"]
    assert result["inputs_manifest"]["ok"] is True, result["inputs_manifest"]
    # This is the check that was missing when the C29 pin promotion silently broke every
    # RQ1 claim's provenance verification (they cited the pre-promotion sha, which stopped
    # matching PINNED_MAP_REGISTRY the moment the live pointer moved) -- nothing exercised
    # _verify_rq_table_claims against the real rq_tables.json, so 648+/648+ "full suite
    # green" runs never caught it. Assert it here so it can't regress silently again.
    assert result["rq_table_claims"]["ok"] is True, result["rq_table_claims"]
