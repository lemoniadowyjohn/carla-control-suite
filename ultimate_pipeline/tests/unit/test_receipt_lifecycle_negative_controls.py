# -*- coding: utf-8 -*-
"""Negative lifecycle controls for final-artifact authority receipts."""

from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.contracts.artifact_authority import (
    ArtifactAuthorityError,
    ArtifactAuthorityLedger,
    FinalArtifactReceiptError,
    resolve_final_artifact_receipt,
    sha256_file,
    write_receipt,
)
from ultimate_pipeline.contracts.stage_capabilities import FINAL_ARTIFACT_PUBLISHED


_XODR = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE><header revMajor="1" revMinor="4"/>
<road name="receipt" length="1" id="1" junction="-1">
<planView><geometry s="0" x="0" y="0" hdg="0" length="1"><line/></geometry></planView>
<lanes><laneSection s="0"><center><lane id="0" type="none" level="false"/></center></laneSection></lanes>
</road></OpenDRIVE>"""


def _frozen_ledger(tmp_path: Path) -> tuple[ArtifactAuthorityLedger, str, dict[str, object]]:
    final = tmp_path / "final.xodr"
    final.write_text(_XODR, encoding="utf-8")
    acceptance = tmp_path / "map_acceptance.json"
    acceptance.write_text('{"valid_for_experiments": true}', encoding="utf-8")
    manifest = tmp_path / "inputs_manifest.json"
    manifest.write_text('{"inputs": {}}', encoding="utf-8")

    ledger = ArtifactAuthorityLedger()
    ledger.freeze_structure(str(final), stage="final_artifact_authority")
    ledger.record_evidence("map_acceptance", str(final), stage="final_artifact_authority")
    return ledger, str(final), {
        "receipt_root": str(tmp_path),
        "run_id": tmp_path.name,
        "acceptance_receipt_path": str(acceptance),
        "source_manifest_identity": {
            "inputs_manifest_path": str(manifest),
            "inputs_manifest_sha256": sha256_file(str(manifest)),
        },
    }


def test_receipt_rejects_failed_map_acceptance(tmp_path: Path):
    """C3: a failed acceptance is documented but never published."""
    ledger, final, kwargs = _frozen_ledger(tmp_path)

    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance={"valid_for_experiments": False, "hard_fail_reasons": ["P0-C"]},
        topology_certification={"SPEC_TOPOLOGY": "COMPLETE"},
        **kwargs,
    )

    assert receipt["publication_status"] == "ACCEPTANCE_FAILED"
    assert FINAL_ARTIFACT_PUBLISHED not in receipt["capabilities_held"]


def test_receipt_rejects_missing_stage(tmp_path: Path):
    """C2: a receipt cannot be built before STRUCTURE_FROZEN."""
    final = tmp_path / "final.xodr"
    final.write_text(_XODR, encoding="utf-8")

    with pytest.raises(ArtifactAuthorityError, match="structure_frozen"):
        ArtifactAuthorityLedger().build_receipt(final_artifact_path=str(final))


def test_receipt_detects_post_freeze_mutation(tmp_path: Path):
    """C4: a structural mutation after freeze prevents receipt construction."""
    ledger, final, _ = _frozen_ledger(tmp_path)
    Path(final).write_text(_XODR.replace('length="1"', 'length="2"'), encoding="utf-8")

    with pytest.raises(ArtifactAuthorityError, match="STRUCTURE_FROZEN violated"):
        ledger.assert_structure_unchanged(final, where="receipt")


def test_receipt_rejects_tiling_from_different_sha(tmp_path: Path):
    """C5: evidence from a superseded artifact cannot describe the final map."""
    ledger, _, _ = _frozen_ledger(tmp_path)
    superseding = tmp_path / "superseding.xodr"
    superseding.write_text(_XODR.replace('name="receipt"', 'name="new"'), encoding="utf-8")

    with pytest.raises(ArtifactAuthorityError, match="does not describe"):
        ledger.assert_evidence_current(str(superseding))


def test_resolver_refuses_acceptance_failed_receipt(tmp_path: Path):
    """A receipt that records failure is never a resolver-published artifact."""
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance={"valid_for_experiments": False},
        topology_certification={"SPEC_TOPOLOGY": "COMPLETE"},
        **kwargs,
    )
    write_receipt(str(tmp_path), receipt)

    with pytest.raises(FinalArtifactReceiptError, match="not published"):
        resolve_final_artifact_receipt(str(tmp_path))


def test_certification_failure_is_recorded_but_not_published(tmp_path: Path):
    """Certification errors are durable failure evidence, never publication."""
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance={"valid_for_experiments": True},
        topology_certification={
            "status": "CERTIFICATION_FAILED",
            "error_type": "ValueError",
            "error": "malformed topology",
        },
        **kwargs,
    )

    assert receipt["publication_status"] == "ACCEPTANCE_FAILED"
    assert receipt["topology_certification"]["status"] == "CERTIFICATION_FAILED"
    assert FINAL_ARTIFACT_PUBLISHED not in receipt["capabilities_held"]
