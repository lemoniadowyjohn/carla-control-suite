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
from ultimate_pipeline.contracts.stage_contracts import QualityStatus


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
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
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
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
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


@pytest.mark.parametrize(
    "certification,reason",
    [
        (None, "missing"),
        ({}, "missing"),
        ({"SPEC_TOPOLOGY": QualityStatus.FAIL.value}, "fail"),
        ({"SPEC_TOPOLOGY": QualityStatus.INCOMPLETE.value}, "incomplete"),
        ({"RECOVERY_DIAGNOSTIC": QualityStatus.PASS.value}, "missing"),
        (
            {
                "SPEC_TOPOLOGY": QualityStatus.FAIL.value,
                "RECOVERY_DIAGNOSTIC": QualityStatus.PASS.value,
            },
            "fail",
        ),
    ],
)
def test_receipt_requires_literal_spec_topology_pass(
    tmp_path: Path, certification: object, reason: str
):
    """Only literal-spec PASS authorizes publication; recovery is diagnostic."""
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance={"valid_for_experiments": True},
        topology_certification=certification,
        **kwargs,
    )

    assert receipt["publication_status"] == "ACCEPTANCE_FAILED"
    assert FINAL_ARTIFACT_PUBLISHED not in receipt["capabilities_held"]
    assert any(reason in item.lower() for item in receipt["publication_reasons"])


def test_resolver_rechecks_literal_spec_topology_for_v2_receipts(tmp_path: Path):
    """A tampered v2 receipt cannot claim publication after a spec failure."""
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance={"valid_for_experiments": True},
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        **kwargs,
    )
    receipt["topology_certification"] = {
        "SPEC_TOPOLOGY": QualityStatus.FAIL.value,
        "RECOVERY_DIAGNOSTIC": QualityStatus.PASS.value,
    }
    write_receipt(str(tmp_path), receipt)

    with pytest.raises(FinalArtifactReceiptError, match="literal-spec"):
        resolve_final_artifact_receipt(str(tmp_path))


# ---------------------------------------------------------------------------
# V93-18 (P0): build_receipt/resolve_final_artifact_receipt must parse and
# trust the ON-DISK acceptance file, not just the in-memory dict a caller
# happens to pass. Reproduction: the file says valid_for_experiments=false,
# the in-memory dict says True.
# ---------------------------------------------------------------------------


def test_build_receipt_rejects_publication_when_disk_file_disagrees_with_memory(
    tmp_path: Path,
):
    """THE V93-18 repro: in-memory dict says True, the durable file says False."""
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    # Overwrite the durable file AFTER _frozen_ledger wrote "true" -- this is
    # the exact shape of the bug: whatever is on disk is the one a resolver
    # or any other process would read back later.
    Path(kwargs["acceptance_receipt_path"]).write_text(
        '{"valid_for_experiments": false, "hard_fail_reasons": ["tampered"]}',
        encoding="utf-8",
    )

    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance={"valid_for_experiments": True, "failed_gates": []},
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        **kwargs,
    )

    assert receipt["publication_status"] == "ACCEPTANCE_FAILED"
    assert FINAL_ARTIFACT_PUBLISHED not in receipt["capabilities_held"]
    assert any(
        "on-disk acceptance receipt does not record valid_for_experiments"
        in reason
        for reason in receipt["publication_reasons"]
    )


def test_build_receipt_rejects_unparsable_acceptance_file(tmp_path: Path):
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    Path(kwargs["acceptance_receipt_path"]).write_text("not json", encoding="utf-8")

    with pytest.raises(ArtifactAuthorityError, match="Cannot parse on-disk acceptance receipt"):
        ledger.build_receipt(
            final_artifact_path=final,
            map_acceptance={"valid_for_experiments": True},
            topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
            **kwargs,
        )


def test_build_receipt_rejects_acceptance_file_sha_mismatch(tmp_path: Path):
    """The on-disk acceptance's final_xodr_sha256 must match the published artifact."""
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    Path(kwargs["acceptance_receipt_path"]).write_text(
        '{"valid_for_experiments": true, "final_xodr_sha256": "' + "0" * 64 + '"}',
        encoding="utf-8",
    )

    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance={"valid_for_experiments": True},
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        **kwargs,
    )
    assert receipt["publication_status"] == "ACCEPTANCE_FAILED"
    assert any(
        "final_xodr_sha256 does not match" in reason
        for reason in receipt["publication_reasons"]
    )


def test_build_receipt_rejects_acceptance_file_run_id_mismatch(tmp_path: Path):
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    Path(kwargs["acceptance_receipt_path"]).write_text(
        '{"valid_for_experiments": true, "run_id": "some-other-run"}',
        encoding="utf-8",
    )

    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance={"valid_for_experiments": True},
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        **kwargs,
    )
    assert receipt["publication_status"] == "ACCEPTANCE_FAILED"
    assert any(
        "run_id" in reason and "does not match" in reason
        for reason in receipt["publication_reasons"]
    )


def test_build_receipt_accepts_matching_disk_and_memory_acceptance(tmp_path: Path):
    """Positive control: file and in-memory dict genuinely agree -> PUBLISHED."""
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance={"valid_for_experiments": True},
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        **kwargs,
    )
    assert receipt["publication_status"] == "PUBLISHED"
    assert FINAL_ARTIFACT_PUBLISHED in receipt["capabilities_held"]


# ---------------------------------------------------------------------------
# PR #30 "Later mutation earns release receipt": final_out can change between
# the caller's earlier verification and build_receipt. expected_final_sha256
# is the last re-check.
# ---------------------------------------------------------------------------


def test_build_receipt_rejects_final_artifact_mutated_after_expected_sha_was_captured(
    tmp_path: Path,
):
    """Isolates the ``expected_final_sha256`` re-check from
    ``assert_evidence_current`` (a stricter, independent check that would
    also catch a byte-level mutation if evidence had been recorded against
    the pre-mutation bytes -- see
    ``test_byte_level_mutation_without_structural_change_is_still_caught`` in
    test_final_artifact_authority.py). This ledger deliberately records NO
    evidence, so only ``expected_final_sha256`` can be responsible for the
    rejection below.
    """
    final = tmp_path / "final.xodr"
    final.write_text(_XODR, encoding="utf-8")
    acceptance = tmp_path / "map_acceptance.json"
    acceptance.write_text('{"valid_for_experiments": true}', encoding="utf-8")
    manifest = tmp_path / "inputs_manifest.json"
    manifest.write_text('{"inputs": {}}', encoding="utf-8")

    ledger = ArtifactAuthorityLedger()
    ledger.freeze_structure(str(final), stage="final_artifact_authority")
    expected_sha = sha256_file(str(final))

    # A byte-only edit (header attribute, not a tracked structural aspect)
    # after the caller captured expected_sha.
    final.write_text(
        _XODR.replace('revMinor="4"', 'revMinor="4" extra="x"'), encoding="utf-8"
    )

    with pytest.raises(ArtifactAuthorityError, match="Final artifact changed after acceptance"):
        ledger.build_receipt(
            final_artifact_path=str(final),
            map_acceptance={"valid_for_experiments": True},
            topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
            receipt_root=str(tmp_path),
            run_id=tmp_path.name,
            acceptance_receipt_path=str(acceptance),
            source_manifest_identity={
                "inputs_manifest_path": str(manifest),
                "inputs_manifest_sha256": sha256_file(str(manifest)),
            },
            expected_final_sha256=expected_sha,
        )


def test_build_receipt_accepts_unchanged_final_artifact_against_expected_sha(
    tmp_path: Path,
):
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    expected_sha = sha256_file(final)
    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance={"valid_for_experiments": True},
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        expected_final_sha256=expected_sha,
        **kwargs,
    )
    assert receipt["publication_status"] == "PUBLISHED"
