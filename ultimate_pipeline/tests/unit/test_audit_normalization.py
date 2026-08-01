"""AUDIT-NORM-001 tests — audit normalization tooling.

Covers: missing/duplicate IDs, invalid PASS, stale identity, missing negative
controls, contradictions, wrong profile effect, premature manifest,
archive mismatch. Pipeline source untouched.
"""
import json
import os
import shutil
import tempfile
import zipfile

import pytest

from ultimate_pipeline.audit import (
    AuditNormalizationError,
    apply_status_logic,
    assert_no_invalid_pass,
    build_registry,
    recalculate_release_effects,
    sha256,
    verify_archive_round_trip,
    verify_manifest,
)


def _rec(rid, status="PASS", ev=True, nc_required=True, nc_exec=True,
         contradictions=None, effect="NON_BLOCKING", stale=False):
    return {
        "requirement_id": rid,
        "verification_state": status,
        "evidence_met": ev,
        "negative_control": {"required": nc_required, "executed": nc_exec},
        "contradictions": contradictions or [],
        "release_effect": effect,
        "identity_stale": stale,
    }


# ---------------------------------------------------------------- A1 registry
def test_registry_232_total():
    reg = build_registry([f"REQ-{i:03d}" for i in range(1, 219)])
    assert reg["coverage"]["total_tracked"] == 232
    assert reg["coverage"]["formal_ids"] == 218
    assert reg["coverage"]["issue_ids"] == 14


def test_registry_duplicate_ids_fail_closed():
    with pytest.raises(AuditNormalizationError):
        build_registry([f"REQ-{i:03d}" for i in range(1, 219)] + ["REQ-001"])


def test_registry_missing_ids_fail_closed():
    with pytest.raises(AuditNormalizationError):
        build_registry([f"REQ-{i:03d}" for i in range(1, 200)],
                       expected_total=232)


# ---------------------------------------------------------------- A2 status
def test_pass_with_evidence_false_is_downgraded():
    c = apply_status_logic([_rec("REQ-001", ev=False)])[0]
    assert c["corrected_status"] == "INSUFFICIENT_EVIDENCE"


def test_pass_with_missing_negative_control_downgraded():
    c = apply_status_logic([_rec("REQ-001", nc_required=True, nc_exec=False)])[0]
    assert c["corrected_status"] == "INSUFFICIENT_EVIDENCE"


def test_pass_with_contradiction_downgraded_to_conflicting():
    c = apply_status_logic([_rec("REQ-001", contradictions=["stale log"])])[0]
    assert c["corrected_status"] == "CONFLICTING_EVIDENCE"


def test_pass_with_stale_identity_downgraded():
    c = apply_status_logic([_rec("REQ-001", stale=True)])[0]
    assert c["corrected_status"] == "INSUFFICIENT_EVIDENCE"
    assert "stale" in c["correction"]


def test_valid_pass_sustained():
    c = apply_status_logic([_rec("REQ-001")])[0]
    assert c["corrected_status"] == "PASS"


def test_zero_invalid_pass_across_batch():
    recs = [_rec(f"REQ-{i:03d}") for i in range(1, 219)]
    corr = apply_status_logic(recs)
    assert_no_invalid_pass(corr)
    # tamper a PASS record with a disqualifier -> fail-closed guard must raise
    tampered = [dict(corr[0], corrected_status="PASS", evidence_met=False)]
    with pytest.raises(AuditNormalizationError):
        assert_no_invalid_pass(tampered)
    # restored clean batch must pass again
    assert_no_invalid_pass(corr)


# ---------------------------------------------------------------- A3 effects
def test_wrong_profile_effect_recalculated():
    # audit said NON_BLOCKING but status is FAIL -> must block profile
    recs = [_rec("REQ-001", status="FAIL", effect="NON_BLOCKING")]
    by_id = {r["requirement_id"]: r for r in recs}
    corr = apply_status_logic(recs)
    eff = recalculate_release_effects(corr, by_id)
    p = eff["profiles"]["STANDALONE_XODR"]
    assert p["verdict"] == "BLOCKED"
    assert p["blockers"] == ["REQ-001"]


def test_blocks_all_releases_propagates():
    recs = [_rec("REQ-001", status="FAIL", effect="BLOCKS_ALL_RELEASES")]
    by_id = {r["requirement_id"]: r for r in recs}
    corr = apply_status_logic(recs)
    eff = recalculate_release_effects(corr, by_id)
    for prof in eff["profiles"]:
        assert eff["profiles"][prof]["verdict"] == "BLOCKED"
        assert (eff["profiles"][prof]["counts"].get("BLOCKS_ALL_RELEASES", 0) == 1)


def test_all_pass_profile_verdict():
    recs = [_rec(f"REQ-{i:03d}") for i in range(1, 219)]
    by_id = {r["requirement_id"]: r for r in recs}
    corr = apply_status_logic(recs)
    eff = recalculate_release_effects(corr, by_id)
    for prof in eff["profiles"]:
        assert eff["profiles"][prof]["verdict"] == "PASS"


# ---------------------------------------------------------------- A4 manifest
def test_manifest_premature_claim_detected(tmp_path):
    f = tmp_path / "result.txt"
    f.write_text("v1")
    manifest = {"artifacts": {}, "outputs": {
        "result.txt": {"sha256": sha256(str(f)) + "0", "bytes": 2}}}
    ver = verify_manifest(manifest, str(tmp_path))
    assert ver["mismatches"] == ["output:result.txt"]


def test_manifest_all_match(tmp_path):
    f = tmp_path / "result.txt"
    f.write_text("v1")
    manifest = {"artifacts": {}, "outputs": {
        "result.txt": {"sha256": sha256(str(f)), "bytes": 2}}}
    ver = verify_manifest(manifest, str(tmp_path))
    assert ver["mismatches"] == []


def test_archive_mismatch_detected(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("content-a")
    (src / "b.txt").write_text("content-b")
    zip_path = tmp_path / "evidence.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        for p in sorted(src.iterdir()):
            z.write(p, arcname=p.name)
    expected = {p.name: sha256(str(p)) for p in src.iterdir()}
    expected["a.txt"] += "ff"  # tamper expectation -> mismatch must surface
    out = verify_archive_round_trip(str(zip_path), str(tmp_path / "out"), expected)
    assert out["round_trip"] == "FAIL"
    assert any("a.txt" in m["entry"] for m in out["mismatches"])


def test_archive_round_trip_pass(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("content-a")
    (src / "b.txt").write_text("content-b")
    zip_path = tmp_path / "evidence.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        for p in sorted(src.iterdir()):
            z.write(p, arcname=p.name)
    expected = {p.name: sha256(str(p)) for p in src.iterdir()}
    out = verify_archive_round_trip(str(zip_path), str(tmp_path / "out"), expected)
    assert out["round_trip"] == "PASS"


def test_archive_corrupt_member_fails(tmp_path):
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("x.txt", "payload")
    data = bytearray(zip_path.read_bytes())
    data[-6] ^= 0xFF  # corrupt central directory byte
    zip_path.write_bytes(bytes(data))
    with pytest.raises(AuditNormalizationError):
        verify_archive_round_trip(str(zip_path), str(tmp_path / "out"), {})
