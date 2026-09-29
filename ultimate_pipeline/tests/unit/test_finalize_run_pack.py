# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/utils/finalize_run_pack.py (V5 / NEW-202, D16).

Live: write_signature_json + write_success_txt imported and called by both
main_pipeline.py and run_full_domain_gap.py as the final integrity/success
marker step of a run.

V5 replaces the historical best-effort contract (silent skipping + independently
emitted SUCCESS.txt) with a fail-closed one. The tests below therefore assert
that a requested artifact which is missing / unreadable / out-of-root / a
duplicate / hash-failing now produces ``status == FAIL`` and **no** SUCCESS.txt.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

from ultimate_pipeline.utils.finalize_run_pack import (
    CATEGORY_DUPLICATE,
    CATEGORY_HASHED,
    CATEGORY_MISSING,
    CATEGORY_OUTSIDE_ROOT,
    CATEGORY_UNREADABLE,
    FinalizationError,
    classify_requested_paths,
    finalize_run_pack,
    hash_file_sha256,
    verify_run_pack,
    write_signature_json,
    write_success_txt,
)


def _write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_all_required_files_present_passes(tmp_path):
    _write(tmp_path / "final.xodr", "<OpenDRIVE/>")
    _write(tmp_path / "reports" / "out.json", "{}")

    receipt = finalize_run_pack(tmp_path, ["final.xodr", "reports/out.json"])

    assert receipt["status"] == "PASS"
    assert receipt["requested_count"] == 2
    assert receipt["hashed_count"] == 2
    assert receipt["failures"] == []
    assert (tmp_path / "SUCCESS.txt").is_file()

    expected = hash_file_sha256(tmp_path / "final.xodr")
    assert receipt["files"]["final.xodr"] == expected
    assert receipt["hash_algorithm"] == "sha256"
    assert receipt["schema"] == "RUN_PACK_FINALIZATION/v2"


def test_signature_json_keys_are_posix_relative(tmp_path):
    _write(tmp_path / "reports" / "out.json", "{}")
    receipt = finalize_run_pack(tmp_path, ["reports/out.json"], emit_success=False)
    assert "reports/out.json" in receipt["files"]


def test_manifest_on_disk_matches_returned_receipt(tmp_path):
    _write(tmp_path / "a.bin", "aaa")
    receipt = finalize_run_pack(tmp_path, ["a.bin"])
    written = json.loads((tmp_path / "signature.json").read_text(encoding="utf-8"))
    assert written["status"] == receipt["status"]
    assert written["files"] == receipt["files"]
    assert written["signature_sha256"] == receipt["signature_sha256"]


# ---------------------------------------------------------------------------
# fail-closed negative paths
# ---------------------------------------------------------------------------


def test_missing_required_file_fails_and_emits_no_success(tmp_path):
    receipt = finalize_run_pack(tmp_path, ["does_not_exist.xodr"])
    assert receipt["status"] == "FAIL"
    assert receipt["counts"][CATEGORY_MISSING] == 1
    assert receipt["hashed_count"] == 0
    assert not (tmp_path / "SUCCESS.txt").exists()
    # The failure receipt is still written, so the reason is auditable.
    assert (tmp_path / "signature.json").is_file()


def test_outside_root_path_fails(tmp_path):
    outside = _write(tmp_path.parent / "outside_area" / "secret.txt", "nope")
    out_dir = tmp_path / "run_out"
    out_dir.mkdir()

    receipt = finalize_run_pack(out_dir, [str(outside)])
    assert receipt["status"] == "FAIL"
    assert receipt["counts"][CATEGORY_OUTSIDE_ROOT] == 1
    assert not (out_dir / "SUCCESS.txt").exists()


def test_path_traversal_is_rejected(tmp_path):
    out_dir = tmp_path / "run_out"
    out_dir.mkdir()
    _write(tmp_path / "secret.txt", "nope")

    receipt = finalize_run_pack(out_dir, ["../secret.txt"])
    assert receipt["status"] == "FAIL"
    assert receipt["counts"][CATEGORY_OUTSIDE_ROOT] == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink creation needs privileges on Windows")
def test_symlink_escape_is_rejected(tmp_path):
    out_dir = tmp_path / "run_out"
    out_dir.mkdir()
    target = _write(tmp_path / "outside.txt", "secret")
    link = out_dir / "link.txt"
    link.symlink_to(target)

    receipt = finalize_run_pack(out_dir, ["link.txt"])
    assert receipt["status"] == "FAIL"
    assert receipt["counts"][CATEGORY_OUTSIDE_ROOT] == 1


def test_unreadable_requested_file_fails(tmp_path, monkeypatch):
    """A PermissionError while hashing a requested artifact must fail closed."""
    target = tmp_path / "locked.bin"
    target.write_text("data", encoding="utf-8")
    import ultimate_pipeline.utils.finalize_run_pack as mod

    real = mod.hash_file_sha256

    def denied(path):
        if str(path).endswith("locked.bin"):
            raise PermissionError("simulated ACL denial")
        return real(path)

    monkeypatch.setattr(mod, "hash_file_sha256", denied)
    receipt = finalize_run_pack(tmp_path, ["locked.bin"])

    assert receipt["status"] == "FAIL"
    assert receipt["counts"][CATEGORY_UNREADABLE] == 1
    assert not (tmp_path / "SUCCESS.txt").exists()
    # The failure reason is preserved, not swallowed.
    assert any("unreadable" in f["message"] for f in receipt["failures"])


def test_hashing_exception_fails_closed(tmp_path, monkeypatch):
    _write(tmp_path / "a.bin", "aaa")
    import ultimate_pipeline.utils.finalize_run_pack as mod

    real = mod.hash_file_sha256

    def boom(path):
        if str(path).endswith("a.bin"):
            raise OSError("simulated device failure")
        return real(path)

    monkeypatch.setattr(mod, "hash_file_sha256", boom)
    receipt = finalize_run_pack(tmp_path, ["a.bin"])
    assert receipt["status"] == "FAIL"
    assert receipt["counts"][CATEGORY_UNREADABLE] == 1
    assert receipt["hashed_count"] == 0
    assert not (tmp_path / "SUCCESS.txt").exists()


def test_duplicate_entry_is_deterministic(tmp_path):
    _write(tmp_path / "a.bin", "aaa")
    first = finalize_run_pack(tmp_path, ["a.bin", "a.bin"], emit_success=False)
    second = finalize_run_pack(tmp_path, ["a.bin", "a.bin"], emit_success=False)
    assert first["counts"][CATEGORY_DUPLICATE] == 1
    assert first["status"] == "FAIL"
    # Deterministic: identical inputs produce identical classification.
    assert first["counts"] == second["counts"]
    assert first["failures"] == second["failures"]
    assert first["signature_sha256"] == second["signature_sha256"]


def test_duplicate_via_different_spelling_is_also_caught(tmp_path):
    _write(tmp_path / "a.bin", "aaa")
    receipt = finalize_run_pack(
        tmp_path, ["a.bin", "./a.bin", str(tmp_path / "a.bin")], emit_success=False
    )
    assert receipt["counts"][CATEGORY_DUPLICATE] == 2
    assert receipt["status"] == "FAIL"


def test_directory_request_is_not_treated_as_file(tmp_path):
    (tmp_path / "adir").mkdir()
    receipt = finalize_run_pack(tmp_path, ["adir"])
    assert receipt["status"] == "FAIL"
    assert receipt["counts"]["unexpected"] == 1


def test_blank_entries_are_not_requested_artifacts(tmp_path):
    receipt = classify_requested_paths(tmp_path, ["", None, "   "])
    assert receipt["artifacts"] == []
    assert receipt["failures"] == []


# ---------------------------------------------------------------------------
# SUCCESS binding
# ---------------------------------------------------------------------------


def test_success_txt_is_bound_to_manifest_and_signature(tmp_path):
    _write(tmp_path / "a.bin", "aaa")
    receipt = finalize_run_pack(tmp_path, ["a.bin"], summary="run_full_domain_gap")

    text = (tmp_path / "SUCCESS.txt").read_text(encoding="utf-8")
    assert text.startswith("OK ")
    assert "run_full_domain_gap" in text
    assert f"manifest_sha256={receipt['manifest_sha256']}" in text
    assert f"signature_sha256={receipt['signature_sha256']}" in text
    assert "status=PASS" in text


def test_success_never_precedes_a_complete_manifest(tmp_path):
    _write(tmp_path / "a.bin", "aaa")
    finalize_run_pack(tmp_path, ["a.bin", "missing.bin"])
    # Manifest exists and is a complete, parseable failure receipt; no SUCCESS.
    assert (tmp_path / "signature.json").is_file()
    assert not (tmp_path / "SUCCESS.txt").exists()
    manifest = json.loads((tmp_path / "signature.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FAIL"
    assert manifest["failures"]


def test_verify_detects_tampering_after_finalization(tmp_path):
    _write(tmp_path / "a.bin", "aaa")
    finalize_run_pack(tmp_path, ["a.bin"])
    assert verify_run_pack(tmp_path)["status"] == "PASS"

    _write(tmp_path / "a.bin", "TAMPERED")
    result = verify_run_pack(tmp_path)
    assert result["status"] == "FAIL"
    assert any("tampered" in p for p in result["problems"])


def test_verify_detects_artifact_deleted_after_manifest(tmp_path):
    _write(tmp_path / "a.bin", "aaa")
    finalize_run_pack(tmp_path, ["a.bin"])
    (tmp_path / "a.bin").unlink()
    result = verify_run_pack(tmp_path)
    assert result["status"] == "FAIL"
    assert any("now missing" in p for p in result["problems"])


def test_verify_detects_success_without_manifest(tmp_path):
    (tmp_path / "SUCCESS.txt").write_text("OK 2026-01-01T00:00:00Z\n", encoding="utf-8")
    result = verify_run_pack(tmp_path)
    assert result["status"] == "FAIL"
    assert any("missing" in p for p in result["problems"])


def test_verify_reports_manifest_without_success(tmp_path):
    _write(tmp_path / "a.bin", "aaa")
    finalize_run_pack(tmp_path, ["a.bin"], emit_success=False)
    result = verify_run_pack(tmp_path)
    assert result["signature_present"] is True
    assert result["success_present"] is False
    assert result["status"] == "PASS"


def test_verify_detects_manifest_without_success_as_incomplete_evidence(tmp_path):
    # A manifest that never reached PASS must never be treated as promotable.
    finalize_run_pack(tmp_path, ["absent.bin"], emit_success=False)
    result = verify_run_pack(tmp_path)
    assert result["status"] == "FAIL"
    assert any("not PASS" in p for p in result["problems"])


def test_verify_detects_rewritten_success_binding(tmp_path):
    _write(tmp_path / "a.bin", "aaa")
    finalize_run_pack(tmp_path, ["a.bin"])
    success = tmp_path / "SUCCESS.txt"
    text = success.read_text(encoding="utf-8").replace(
        "manifest_sha256=", "manifest_sha256=0000", 1
    )
    success.write_text(text, encoding="utf-8")
    result = verify_run_pack(tmp_path)
    assert result["status"] == "FAIL"
    assert any("manifest digest" in p for p in result["problems"])


# ---------------------------------------------------------------------------
# backward-compatible entry points
# ---------------------------------------------------------------------------


def test_write_signature_json_keeps_legacy_shape_but_fails_closed(tmp_path):
    _write(tmp_path / "final.xodr", "<OpenDRIVE/>")
    sig = write_signature_json(str(tmp_path), ["final.xodr"])
    # legacy keys preserved
    assert "final.xodr" in sig["files"]
    assert sig["hash_algorithm"] == "sha256"
    # new fail-closed status present
    assert sig["status"] == "PASS"
    # ... and it does not itself publish SUCCESS
    assert not (tmp_path / "SUCCESS.txt").exists()


def test_write_signature_json_reports_missing_as_failure(tmp_path):
    sig = write_signature_json(str(tmp_path), ["does_not_exist.xodr"])
    assert sig["status"] == "FAIL"
    assert sig["files"] == {}


def test_write_success_txt_refuses_without_finalization(tmp_path):
    with pytest.raises(FinalizationError):
        write_success_txt(str(tmp_path), summary="x")


def test_write_success_txt_refuses_on_failed_finalization(tmp_path):
    finalize_run_pack(tmp_path, ["absent.bin"], emit_success=False)
    with pytest.raises(FinalizationError):
        write_success_txt(str(tmp_path), summary="x")
    assert not (tmp_path / "SUCCESS.txt").exists()


def test_write_success_txt_allowed_after_pass(tmp_path):
    _write(tmp_path / "a.bin", "aaa")
    write_signature_json(str(tmp_path), ["a.bin"])
    write_success_txt(str(tmp_path), summary="main_pipeline")
    text = (tmp_path / "SUCCESS.txt").read_text(encoding="utf-8")
    assert text.startswith("OK ")
    assert "summary=main_pipeline" in text
    assert verify_run_pack(tmp_path)["status"] == "PASS"


# ---------------------------------------------------------------------------
# cross-platform path handling
# ---------------------------------------------------------------------------


def test_relative_paths_with_windows_style_separators(tmp_path):
    _write(tmp_path / "sub" / "deeper" / "f.bin", "x")
    receipt = finalize_run_pack(tmp_path, ["sub\\deeper\\f.bin"], emit_success=False)
    # On POSIX a backslash is a legal filename character, so the artifact is
    # simply missing; on Windows it must resolve and hash.
    if os.name == "nt":
        assert receipt["status"] == "PASS"
        assert "sub/deeper/f.bin" in receipt["files"]
    else:
        assert receipt["status"] == "FAIL"


def test_release_root_with_spaces(tmp_path):
    root = tmp_path / "release root with spaces"
    root.mkdir()
    _write(root / "a.bin", "aaa")
    receipt = finalize_run_pack(root, ["a.bin"])
    assert receipt["status"] == "PASS"
    assert (root / "SUCCESS.txt").is_file()


def test_absolute_path_inside_root_is_accepted(tmp_path):
    _write(tmp_path / "a.bin", "aaa")
    receipt = finalize_run_pack(tmp_path, [str(tmp_path / "a.bin")], emit_success=False)
    assert receipt["status"] == "PASS"
    assert receipt["files"]["a.bin"] == hashlib.sha256(b"aaa").hexdigest()


def test_no_temp_files_left_behind(tmp_path):
    _write(tmp_path / "a.bin", "aaa")
    finalize_run_pack(tmp_path, ["a.bin"])
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
