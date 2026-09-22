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
# REWRITTEN 2026-09-22 (GAP-016): the mtime/glob heuristic documented above
# was deliberately replaced by commit ca3729c0 with a receipt-authoritative
# resolver -- scripts/regen_map_of_record.py::_find_final_xodr() now
# delegates to ultimate_pipeline/contracts/artifact_authority.py::
# resolve_final_artifact_receipt(), whose docstring states it deliberately
# does NOT inspect mtimes, glob candidate XODRs, or use a filename
# tiebreaker (eliminating an mtime-authority anti-pattern, see GAP-012).
# The 4 tests below were rewritten against that receipt-based contract; the
# historical comment block above documents real production history and is
# kept for context, but is no longer a description of current behavior.
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.regen_map_of_record as regen
from ultimate_pipeline.contracts.artifact_authority import (
    FINAL_ARTIFACT_RECEIPT_FILENAME,
    FinalArtifactReceiptError,
    compute_structure_fingerprint,
    sha256_file,
)
from ultimate_pipeline.contracts.stage_capabilities import (
    FINAL_ARTIFACT_PUBLISHED,
    STRUCTURE_FROZEN,
)


_XODR = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE><header revMajor="1" revMinor="4"/>
<road name="final" length="1" id="1" junction="-1">
<planView><geometry s="0" x="0" y="0" hdg="0" length="1"><line/></geometry></planView>
<lanes><laneSection s="0"><center><lane id="0" type="none" level="false"/></center></laneSection></lanes>
</road></OpenDRIVE>"""


def _write_valid_receipt(run_dir: Path, final_name: str = "08h3_zseams_repaired.xodr") -> Path:
    """Write a well-formed final_artifact_receipt.json plus everything it binds to."""
    run_dir.mkdir(parents=True, exist_ok=True)
    final = run_dir / final_name
    final.write_text(_XODR, encoding="utf-8")

    parent = run_dir / "08h2_degenerate_lanes_repaired.xodr"
    parent.write_text(_XODR, encoding="utf-8")

    acceptance = run_dir / "map_acceptance.json"
    acceptance.write_text('{"valid_for_experiments": true}', encoding="utf-8")

    source_manifest = run_dir / "inputs_manifest.json"
    source_manifest.write_text('{"inputs": {}}', encoding="utf-8")

    receipt = {
        "schema_version": 1,
        "receipt_kind": "final_artifact_receipt",
        "run_id": run_dir.name,
        "created_at_utc": "2026-09-22T00:00:00+00:00",
        "producer_stage": "final_artifact_authority",
        "final_xodr": {
            "path": final.name,
            "sha256": sha256_file(str(final)),
            "bytes": final.stat().st_size,
        },
        "immediate_parent": {"path": parent.name, "sha256": sha256_file(str(parent))},
        "source_manifest": {
            "path": source_manifest.name,
            "sha256": sha256_file(str(source_manifest)),
        },
        "git_commit": "ca3729c0",
        "acceptance_receipt": {
            "path": acceptance.name,
            "sha256": sha256_file(str(acceptance)),
        },
        "capability_state": {
            "held": [FINAL_ARTIFACT_PUBLISHED, STRUCTURE_FROZEN],
            "invalidated": {},
        },
        "structure_fingerprint": compute_structure_fingerprint(str(final)),
    }
    (run_dir / FINAL_ARTIFACT_RECEIPT_FILENAME).write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    return final


def test_no_receipt_raises_final_artifact_receipt_error(tmp_path: Path):
    # A run directory with plausible-looking XODR candidates but no
    # final_artifact_receipt.json must fail closed -- the resolver never
    # falls back to filename/mtime heuristics.
    run_dir = tmp_path / "pipeline_out"
    run_dir.mkdir()
    (run_dir / "08_final_X.xodr").write_text(_XODR, encoding="utf-8")
    (run_dir / "08h3_zseams_repaired.xodr").write_text(_XODR, encoding="utf-8")

    with pytest.raises(FinalArtifactReceiptError, match="receipt is required"):
        regen._find_final_xodr(run_dir)


def test_valid_receipt_resolves_to_declared_file(tmp_path: Path):
    run_dir = tmp_path / "pipeline_out"
    final = _write_valid_receipt(run_dir)

    # An unrelated, lexically-later, newer-mtime XODR must not affect
    # selection at all -- there is no mtime/glob tiebreaker anymore.
    decoy = run_dir / "zzzz_lexically_later_and_newer.xodr"
    decoy.write_text(_XODR.replace('name="final"', 'name="decoy"'), encoding="utf-8")

    result = regen._find_final_xodr(run_dir)

    assert result == final
    assert result.read_text(encoding="utf-8") == _XODR


def test_tampered_final_xodr_is_rejected(tmp_path: Path):
    # The receipt exists and is well-formed, but the bytes on disk no
    # longer match what it declares (e.g. the file was touched/regenerated
    # after the receipt was written). Must be rejected, not silently
    # accepted.
    run_dir = tmp_path / "pipeline_out"
    final = _write_valid_receipt(run_dir)
    final.write_text(_XODR.replace('length="1"', 'length="2"'), encoding="utf-8")

    with pytest.raises(FinalArtifactReceiptError, match="SHA-256"):
        regen._find_final_xodr(run_dir)


def test_malformed_receipt_json_is_rejected(tmp_path: Path):
    run_dir = tmp_path / "pipeline_out"
    run_dir.mkdir()
    (run_dir / "08h3_zseams_repaired.xodr").write_text(_XODR, encoding="utf-8")
    (run_dir / FINAL_ARTIFACT_RECEIPT_FILENAME).write_text(
        "{not valid json", encoding="utf-8"
    )

    with pytest.raises(FinalArtifactReceiptError, match="Cannot parse"):
        regen._find_final_xodr(run_dir)
