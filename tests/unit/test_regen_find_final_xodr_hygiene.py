# scripts/regen_map_of_record.py::_find_final_xodr() -- zero prior test
# coverage. WS1.4 (map-quality/RQ hardening plan, 2026-09-02): discovered
# via a real, live canonical regen (not a synthetic reproduction) that this
# function has NEVER picked up C10 map-hygiene's (stage_08_hygiene.py,
# added 2026-08-19) corrected output.
#
# stage_08_hygiene.py writes 08h1_island_quarantined.xodr ->
# 08h2_degenerate_lanes_repaired.xodr -> 08h3_zseams_repaired.xodr, none of
# which match "08_final*" (prefix "08h", not "08_final") or
# "*DROP_BAD_LINKS*". _find_final_xodr()'s glob only matched those two
# patterns, so it always silently fell back to the PRE-hygiene
# 08_final*_linkpatched.xodr -- every governed regen since hygiene was
# wired in has emitted a candidate with island quarantine, degenerate-lane
# repair, and z-seam repair silently discarded, despite the hygiene stage
# genuinely running and producing correct output.
#
# Directly reproduced against a real regen run
# (campaigns/.../regen/20260902T151513Z/): 08h1_island_quarantined.xodr had
# 30 fewer roads (32267 vs 32297) than the pre-hygiene file this function
# picked; the emitted candidate matched the pre-hygiene file's road count,
# confirming the hygiene repairs never reached the final artifact.
#
# NOTE (2026-09-22): the four tests below were rewritten for the
# receipt-based contract on 2026-09-22, referencing GAP-016
# (MASTER_GAP_REGISTER.json issues_batch_3). _find_final_xodr now delegates
# to ultimate_pipeline.contracts.artifact_authority.resolve_final_artifact_receipt
# (commit ca3729c0), which deliberately does NOT inspect mtimes, glob
# candidate XODRs, or use a filename tiebreaker anymore. The previous
# mtime/glob fixtures tested superseded behavior and have been replaced by
# equivalents against the real receipt contract.
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import scripts.regen_map_of_record as regen
from ultimate_pipeline.contracts.artifact_authority import (
    FinalArtifactReceiptError,
    compute_structure_fingerprint,
    sha256_file,
)

RECEIPT_FILENAME = "final_artifact_receipt.json"

# A minimal, well-formed OpenDRIVE document: structurally valid enough for
# compute_structure_fingerprint(), and byte-identical across fixtures apart
# from the content under test.
_MINIMAL_XODR = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><OpenDRIVE></OpenDRIVE>"


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _newer(path: Path) -> None:
    """Stretch the write-time so an mtime-ordered heuristic would prefer it."""
    time.sleep(0.02)
    _write(path, _MINIMAL_XODR)


def _build_receipt(run_dir: Path, *, declared_final: str = "08h3_zseams_repaired.xodr",
                   final_content: str = _MINIMAL_XODR,
                   final_bytes: int | None = None,
                   final_sha256: str | None = None) -> Path:
    """Write a well-formed governed receipt + its declared artifacts.

    The fixture also plants a pre-hygiene ``08_final*_linkpatched.xodr`` and,
    unless ``declared_final`` equals it, writes that distractor *after* the
    declared final so any mtime-ordered pick exposes strict receipt authority.
    """
    final_path = run_dir / declared_final
    _write(final_path, final_content)

    distractor = run_dir / "08_final_X_linkpatched.xodr"
    if distractor.name != declared_final:
        _newer(distractor)  # newest-by-mtime, must still NOT be authoritative

    acceptance_path = run_dir / "acceptance.json"
    _write(acceptance_path, "{\"status\":\"accepted\"}")

    actual_sha = final_sha256 if final_sha256 is not None else sha256_file(str(final_path))
    receipt = {
        "schema_version": 1,
        "receipt_kind": "final_artifact_receipt",
        "run_id": run_dir.name,
        "final_xodr": {
            "path": declared_final,
            "sha256": actual_sha,
            "bytes": final_bytes if final_bytes is not None else final_path.stat().st_size,
        },
        "structure_fingerprint": {
            "sha256": compute_structure_fingerprint(str(final_path))["sha256"],
        },
        "immediate_parent": {
            "path": "08h2_degenerate_lanes_repaired.xodr",
            "sha256": "0" * 64,
        },
        "source_manifest": {"sha256": "1" * 64},
        "git_commit": None,
        "created_at_utc": "2026-09-22T00:00:00Z",
        "producer_stage": "stage_08h_map_hygiene",
        "acceptance_receipt": {
            "path": "acceptance.json",
            "sha256": sha256_file(str(acceptance_path)),
        },
        "capability_state": {"held": ["structure_frozen", "final_artifact_published"]},
    }
    receipt_path = run_dir / RECEIPT_FILENAME
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt_path


def test_no_receipt_raises_and_mtime_never_authoritative(tmp_path: Path):
    # A run dir with hygiene + pre-hygiene candidates and NO receipt is not
    # resolvable; the resolver must reject it instead of silently electing
    # the newest-by-mtime candidate (exactly the old mtime-authority pattern
    # GAP-012 flags and GAP-016 confirms eliminated).
    _write(tmp_path / "08_final_X.xodr", _MINIMAL_XODR)
    _newer(tmp_path / "08_final_X_laneSectionFixed.xodr")
    _newer(tmp_path / "08h1_island_quarantined.xodr")
    _newer(tmp_path / "08h3_zseams_repaired.xodr")

    with pytest.raises(
        FinalArtifactReceiptError,
        match=RECEIPT_FILENAME,
    ):
        regen._find_final_xodr(tmp_path)


def test_valid_receipt_resolves_exactly_the_declared_hygiene_final(tmp_path: Path):
    # A well-formed receipt declaring 08h3_zseams_repaired.xodr must resolve
    # to that exact file even though the pre-hygiene 08_final*.xodr was
    # written later (mtime-blind, filename-blind authority).
    _build_receipt(tmp_path, declared_final="08h3_zseams_repaired.xodr")

    result = regen._find_final_xodr(tmp_path)

    assert result.name == "08h3_zseams_repaired.xodr"
    assert result.read_text(encoding="utf-8") == _MINIMAL_XODR


def test_receipt_declaring_missing_or_mismatched_file_is_rejected(tmp_path: Path):
    # Receipt declares a path that does not exist on disk -> rejected.
    _build_receipt(tmp_path, declared_final="08h_gone.xodr")
    _write(tmp_path / "08h_gone.xodr", _MINIMAL_XODR)  # keep xml valid for receipt build, then delete
    (tmp_path / "08h_gone.xodr").unlink()
    with pytest.raises(FinalArtifactReceiptError, match="missing"):
        regen._find_final_xodr(tmp_path)

    # Receipt SHA-256 does not match the bytes on disk -> rejected.
    _write(tmp_path / "08h1_island_quarantined.xodr", _MINIMAL_XODR)
    (tmp_path / RECEIPT_FILENAME).unlink()
    _build_receipt(tmp_path, declared_final="08h1_island_quarantined.xodr")
    _write(tmp_path / "08h1_island_quarantined.xodr", "tampered-bytes-not-in-receipt")
    with pytest.raises(FinalArtifactReceiptError, match="SHA-256"):
        regen._find_final_xodr(tmp_path)


def test_malformed_receipt_json_is_rejected(tmp_path: Path):
    # Unparseable receipt body -> clear parse error (fail-closed).
    _write(tmp_path / RECEIPT_FILENAME, "this is definitely not json {")
    _write(tmp_path / "08h3_zseams_repaired.xodr", _MINIMAL_XODR)
    with pytest.raises(
        FinalArtifactReceiptError,
        match="Cannot parse final-artifact receipt",
    ):
        regen._find_final_xodr(tmp_path)

    # Parseable but not a valid receipt (wrong schema) -> rejected too.
    (tmp_path / RECEIPT_FILENAME).unlink()
    _write(tmp_path / RECEIPT_FILENAME, json.dumps({"schema_version": 999, "receipt_kind": "final_artifact_receipt"}))
    with pytest.raises(
        FinalArtifactReceiptError,
        match="schema_version",
    ):
        regen._find_final_xodr(tmp_path)
