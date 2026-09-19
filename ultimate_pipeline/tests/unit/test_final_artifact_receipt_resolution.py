"""Production final-XODR resolution must be receipt-authoritative, not mtime-authoritative."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from scripts.regen_map_of_record import (
    _find_final_xodr,
    _find_final_xodr_historical_recovery,
)
from ultimate_pipeline.contracts.artifact_authority import (
    FINAL_ARTIFACT_RECEIPT_FILENAME,
    FinalArtifactReceiptError,
    compute_structure_fingerprint,
    resolve_final_artifact_receipt,
    sha256_file,
)
from ultimate_pipeline.contracts.stage_capabilities import (
    FINAL_ARTIFACT_PUBLISHED,
    STRUCTURE_FROZEN,
)


XODR = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<OpenDRIVE><header revMajor=\"1\" revMinor=\"4\"/>
<road name=\"receipt\" length=\"1\" id=\"1\" junction=\"-1\">
<planView><geometry s=\"0\" x=\"0\" y=\"0\" hdg=\"0\" length=\"1\"><line/></geometry></planView>
<lanes><laneSection s=\"0\"><center><lane id=\"0\" type=\"none\" level=\"false\"/></center></laneSection></lanes>
</road></OpenDRIVE>"""


def _write_receipt(run_dir: Path, final_name: str = "published.xodr") -> Path:
    final = run_dir / final_name
    final.write_text(XODR, encoding="utf-8")
    parent = run_dir / "08h3_parent.xodr"
    parent.write_text(XODR, encoding="utf-8")
    acceptance = run_dir / "map_acceptance.json"
    acceptance.write_text('{"valid_for_experiments": true}', encoding="utf-8")
    source_manifest = run_dir / "inputs_manifest.json"
    source_manifest.write_text('{"inputs": {}}', encoding="utf-8")
    receipt = {
        "schema_version": 1,
        "receipt_kind": "final_artifact_receipt",
        "run_id": run_dir.name,
        "created_at_utc": "2026-09-19T00:00:00+00:00",
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
        "git_commit": "f5333f3ae623194809350afa3bc212f53c3577d6",
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


@pytest.mark.parametrize(
    "stale_name",
    ["08_final_touched_old.xodr", "newer_unrelated.xodr", "zzzz_lexically_later_stale.xodr"],
)
def test_production_receipt_ignores_touched_newer_and_lexically_later_xodrs(
    tmp_path, stale_name
):
    """These were all able to win the prior glob+mtime ordering."""
    run_dir = tmp_path / "pipeline_out"
    run_dir.mkdir()
    published = _write_receipt(run_dir)
    stale = run_dir / stale_name
    stale.write_text(XODR.replace('name="receipt"', 'name="stale"'), encoding="utf-8")

    # Make the receipt-selected artifact oldest and the unrelated one newest.
    now = time.time()
    os.utime(published, (now - 10_000, now - 10_000))
    os.utime(stale, (now + 10_000, now + 10_000))

    assert _find_final_xodr(run_dir) == published
    assert resolve_final_artifact_receipt(str(run_dir)) == published


def test_production_resolution_fails_closed_without_a_receipt(tmp_path):
    run_dir = tmp_path / "pipeline_out"
    run_dir.mkdir()
    (run_dir / "08_final.xodr").write_text(XODR, encoding="utf-8")

    with pytest.raises(FinalArtifactReceiptError, match="receipt is required"):
        _find_final_xodr(run_dir)


def test_tampered_final_xodr_does_not_resolve_even_when_receipt_exists(tmp_path):
    run_dir = tmp_path / "pipeline_out"
    run_dir.mkdir()
    published = _write_receipt(run_dir)
    published.write_text(XODR.replace('length="1"', 'length="2"'), encoding="utf-8")

    with pytest.raises(FinalArtifactReceiptError, match="SHA-256"):
        resolve_final_artifact_receipt(str(run_dir))


def test_mtime_selection_is_available_only_through_explicit_historical_recovery(tmp_path):
    run_dir = tmp_path / "historical_run"
    run_dir.mkdir()
    old = run_dir / "08_final_old.xodr"
    newest = run_dir / "08h3_newest.xodr"
    old.write_text(XODR, encoding="utf-8")
    newest.write_text(XODR, encoding="utf-8")
    now = time.time()
    os.utime(old, (now - 10_000, now - 10_000))
    os.utime(newest, (now + 10_000, now + 10_000))

    assert _find_final_xodr_historical_recovery(run_dir) == newest
