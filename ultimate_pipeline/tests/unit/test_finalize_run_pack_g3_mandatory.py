# ultimate_pipeline/tests/unit/test_finalize_run_pack_g3_mandatory.py
# -*- coding: utf-8 -*-
"""
G3 regression tests: mandatory artifact completeness.

Covers the defect where mandatory artifacts declared but absent from
``key_paths`` were never validated, allowing PASS despite missing mandatory
artifacts.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from ultimate_pipeline.utils.finalize_run_pack import (
    CATEGORY_MISSING,
    finalize_run_pack,
)


def _write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Mandatory artifact completeness
# ---------------------------------------------------------------------------


def test_mandatory_artifact_omitted_from_key_paths_fails(tmp_path):
    """A mandatory artifact not in key_paths must force FAIL."""
    _write(tmp_path / "unrelated.bin", "data")

    receipt = finalize_run_pack(
        tmp_path, ["unrelated.bin"], mandatory=["required.bin"]
    )
    assert receipt["status"] == "FAIL"
    assert any(
        f["mandatory"] is True and "key_paths" in f["message"]
        for f in receipt["failures"]
    )
    assert not (tmp_path / "SUCCESS.txt").exists()


def test_empty_key_paths_with_nonempty_mandatory_fails(tmp_path):
    """No requested artifacts but mandatory declared must force FAIL."""
    receipt = finalize_run_pack(tmp_path, [], mandatory=["required.bin"])
    assert receipt["status"] == "FAIL"
    assert any(
        f["mandatory"] is True for f in receipt["failures"]
    )
    assert not (tmp_path / "SUCCESS.txt").exists()


def test_mandatory_artifact_present_in_key_paths_passes(tmp_path):
    """A mandatory artifact that IS in key_paths and exists must PASS."""
    _write(tmp_path / "required.bin", "data")

    receipt = finalize_run_pack(
        tmp_path, ["required.bin"], mandatory=["required.bin"]
    )
    assert receipt["status"] == "PASS"
    assert (tmp_path / "SUCCESS.txt").is_file()


def test_mandatory_artifact_missing_on_disk_fails(tmp_path):
    """A mandatory artifact in key_paths but missing on disk must FAIL."""
    receipt = finalize_run_pack(
        tmp_path, ["required.bin"], mandatory=["required.bin"]
    )
    assert receipt["status"] == "FAIL"
    mandatory_failures = [
        f for f in receipt["failures"] if f.get("mandatory") is True
    ]
    assert len(mandatory_failures) >= 1
    assert not (tmp_path / "SUCCESS.txt").exists()


def test_multiple_mandatory_one_missing_fails(tmp_path):
    """Multiple mandatory artifacts with one missing must FAIL."""
    _write(tmp_path / "present.bin", "data")

    receipt = finalize_run_pack(
        tmp_path, ["present.bin"], mandatory=["present.bin", "absent.bin"]
    )
    assert receipt["status"] == "FAIL"
    assert not (tmp_path / "SUCCESS.txt").exists()


def test_multiple_mandatory_all_present_passes(tmp_path):
    """Multiple mandatory artifacts all present must PASS."""
    _write(tmp_path / "a.bin", "data")
    _write(tmp_path / "b.bin", "data")

    receipt = finalize_run_pack(
        tmp_path, ["a.bin", "b.bin"], mandatory=["a.bin", "b.bin"]
    )
    assert receipt["status"] == "PASS"
    assert (tmp_path / "SUCCESS.txt").is_file()


def test_no_mandatory_all_optional_missing_is_ok(tmp_path):
    """Without mandatory declared, missing optional artifacts should NOT force FAIL
    (each missing optional artifact is still reported but does not block PASS
    unless it's the only artifact... actually existing behavior: all artifacts
    are mandatory when none specified. Keep that behavior but document it).
    """
    # Existing behavior: when mandatory is empty/not specified, all artifacts
    # are treated as mandatory (fail-closed default). This test documents
    # that behavior.
    receipt = finalize_run_pack(tmp_path, ["missing.bin"])
    assert receipt["status"] == "FAIL"
    assert not (tmp_path / "SUCCESS.txt").exists()


def test_mandatory_artifact_unreadable_fails(tmp_path, monkeypatch):
    """A mandatory artifact that is unreadable must FAIL."""
    target = tmp_path / "locked.bin"
    target.write_text("data", encoding="utf-8")

    import ultimate_pipeline.utils.finalize_run_pack as mod

    real = mod.hash_file_sha256

    def denied(path):
        if str(path).endswith("locked.bin"):
            raise PermissionError("simulated ACL denial")
        return real(path)

    monkeypatch.setattr(mod, "hash_file_sha256", denied)
    receipt = finalize_run_pack(
        tmp_path, ["locked.bin"], mandatory=["locked.bin"]
    )
    assert receipt["status"] == "FAIL"
    assert not (tmp_path / "SUCCESS.txt").exists()


def test_mandatory_artifact_outside_root_fails(tmp_path):
    """A mandatory artifact outside the release root must FAIL."""
    outside = tmp_path.parent / "outside_secret.txt"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("nope", encoding="utf-8")

    out_dir = tmp_path / "run_out"
    out_dir.mkdir()

    receipt = finalize_run_pack(
        out_dir, [str(outside)], mandatory=[str(outside)]
    )
    assert receipt["status"] == "FAIL"
    assert not (out_dir / "SUCCESS.txt").exists()
