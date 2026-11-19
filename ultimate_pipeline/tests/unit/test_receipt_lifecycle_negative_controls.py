# -*- coding: utf-8 -*-
"""Negative lifecycle controls for final-artifact authority receipts."""

from __future__ import annotations

import json
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
from ultimate_pipeline.quality.final_artifact_gates import RELEASE_MANDATORY_GATES


_XODR = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE><header revMajor="1" revMinor="4"/>
<road name="receipt" length="1" id="1" junction="-1">
<planView><geometry s="0" x="0" y="0" hdg="0" length="1"><line/></geometry></planView>
<lanes><laneSection s="0"><center><lane id="0" type="none" level="false"/></center></laneSection></lanes>
</road></OpenDRIVE>"""


def _release_payload(xodr_path: str, run_id: str, **overrides) -> dict:
    """A minimal acceptance payload that genuinely satisfies
    ``validate_release_acceptance_contract`` (V93 round 2, F2). Round 1's bare
    ``{"valid_for_experiments": True}`` no longer authorizes PUBLISHED --
    release purpose, the authoritative mandatory-gate set, and identity bound
    to the real final artifact + run_id are all required. ``overrides`` lets
    individual tests deliberately break exactly one field to isolate a
    specific contract failure.
    """
    sha = sha256_file(xodr_path)
    payload = {
        "valid_for_experiments": True,
        "release_eligible": True,
        "artifact_identity_verified": True,
        "acceptance_policy": {"purpose": "release"},
        "mandatory_gates": list(RELEASE_MANDATORY_GATES),
        "mandatory_gate_status": {gate: "PASS" for gate in RELEASE_MANDATORY_GATES},
        "final_xodr_sha256": sha,
        "evaluated_xodr_sha256": sha,
        "run_id": run_id,
        "hard_fail_reasons": [],
        "failed_gates": [],
    }
    payload.update(overrides)
    return payload


def _frozen_ledger(tmp_path: Path) -> tuple[ArtifactAuthorityLedger, str, dict[str, object]]:
    final = tmp_path / "final.xodr"
    final.write_text(_XODR, encoding="utf-8")
    acceptance = tmp_path / "map_acceptance.json"
    acceptance.write_text(
        json.dumps(_release_payload(str(final), tmp_path.name)), encoding="utf-8"
    )
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


def test_record_evidence_rejects_bytes_that_differ_from_evaluated_digest(tmp_path: Path):
    ledger, final, _ = _frozen_ledger(tmp_path)
    expected = sha256_file(final)
    Path(final).write_text(_XODR.replace('length="1"', 'length="2"'), encoding="utf-8")

    with pytest.raises(ArtifactAuthorityError, match="artifact identity changed"):
        ledger.record_evidence(
            "post_acceptance", final, stage="final_artifact_authority",
            expected_sha256=expected,
        )


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
        map_acceptance=_release_payload(final, tmp_path.name),
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
    """Only literal-spec PASS authorizes publication; recovery is diagnostic.

    The acceptance payload here is a genuine (full-contract-passing) release
    payload, so the ONLY reason ACCEPTANCE_FAILED can fire is the
    certification check this test is isolating.
    """
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance=_release_payload(final, tmp_path.name),
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
        map_acceptance=_release_payload(final, tmp_path.name),
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        **kwargs,
    )
    assert receipt["publication_status"] == "PUBLISHED", receipt["publication_reasons"]
    receipt["topology_certification"] = {
        "SPEC_TOPOLOGY": QualityStatus.FAIL.value,
        "RECOVERY_DIAGNOSTIC": QualityStatus.PASS.value,
    }
    write_receipt(str(tmp_path), receipt)

    with pytest.raises(FinalArtifactReceiptError, match="literal-spec"):
        resolve_final_artifact_receipt(str(tmp_path))


# ---------------------------------------------------------------------------
# V93-18 (P0) / V93 round 2 F2: build_receipt/resolve_final_artifact_receipt
# must parse and trust the ON-DISK acceptance file (and apply the FULL
# release contract to it), not just the in-memory dict a caller happens to
# pass, and not just a bare valid_for_experiments boolean. Reproduction A:
# file says valid_for_experiments=false, memory says True. Reproductions B/C
# (round 2): a bare or diagnostic-purpose acceptance with no release_eligible/
# mandatory_gates/identity must never reach PUBLISHED either.
# ---------------------------------------------------------------------------


def test_build_receipt_rejects_publication_when_disk_file_disagrees_with_memory(
    tmp_path: Path,
):
    """THE V93-18 repro: in-memory dict says True, the durable file says False."""
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    # Overwrite the durable file AFTER _frozen_ledger wrote a passing payload
    # -- this is the exact shape of the bug: whatever is on disk is the one a
    # resolver or any other process would read back later.
    Path(kwargs["acceptance_receipt_path"]).write_text(
        '{"valid_for_experiments": false, "hard_fail_reasons": ["tampered"]}',
        encoding="utf-8",
    )

    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance=_release_payload(final, tmp_path.name),
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        **kwargs,
    )

    assert receipt["publication_status"] == "ACCEPTANCE_FAILED"
    assert FINAL_ARTIFACT_PUBLISHED not in receipt["capabilities_held"]
    assert any(
        "on-disk acceptance receipt" in reason and "valid_for_experiments" in reason
        for reason in receipt["publication_reasons"]
    )


def test_build_receipt_rejects_unparsable_acceptance_file(tmp_path: Path):
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    Path(kwargs["acceptance_receipt_path"]).write_text("not json", encoding="utf-8")

    with pytest.raises(ArtifactAuthorityError, match="Cannot parse on-disk acceptance receipt"):
        ledger.build_receipt(
            final_artifact_path=final,
            map_acceptance=_release_payload(final, tmp_path.name),
            topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
            **kwargs,
        )


def test_build_receipt_rejects_acceptance_file_sha_mismatch(tmp_path: Path):
    """The on-disk acceptance's final_xodr_sha256 must match the published artifact."""
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    broken = _release_payload(final, tmp_path.name, final_xodr_sha256="0" * 64)
    Path(kwargs["acceptance_receipt_path"]).write_text(json.dumps(broken), encoding="utf-8")

    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance=_release_payload(final, tmp_path.name),
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        **kwargs,
    )
    assert receipt["publication_status"] == "ACCEPTANCE_FAILED"
    assert any(
        "on-disk acceptance receipt" in reason and "final_xodr_sha256" in reason
        for reason in receipt["publication_reasons"]
    )


def test_build_receipt_rejects_acceptance_file_run_id_mismatch(tmp_path: Path):
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    broken = _release_payload(final, "some-other-run")
    Path(kwargs["acceptance_receipt_path"]).write_text(json.dumps(broken), encoding="utf-8")

    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance=_release_payload(final, tmp_path.name),
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        **kwargs,
    )
    assert receipt["publication_status"] == "ACCEPTANCE_FAILED"
    assert any(
        "on-disk acceptance receipt" in reason and "run_id" in reason
        for reason in receipt["publication_reasons"]
    )


def test_build_receipt_accepts_matching_disk_and_memory_acceptance(tmp_path: Path):
    """Positive control: file and in-memory dict genuinely agree -> PUBLISHED."""
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance=_release_payload(final, tmp_path.name),
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        **kwargs,
    )
    assert receipt["publication_status"] == "PUBLISHED", receipt["publication_reasons"]
    assert FINAL_ARTIFACT_PUBLISHED in receipt["capabilities_held"]


# ---------------------------------------------------------------------------
# V93 round 2 (F2): a bare or diagnostic acceptance must never reach
# PUBLISHED, even when the in-memory/on-disk sides genuinely agree with each
# other -- agreement alone proved nothing about release eligibility.
# ---------------------------------------------------------------------------


def test_build_receipt_rejects_bare_diagnostic_acceptance_even_when_consistent(
    tmp_path: Path,
):
    """Repro case B: a bare {"valid_for_experiments": true} (memory AND file
    agree) must not reach PUBLISHED -- it proves nothing about release
    eligibility, mandatory gates, or identity."""
    final = tmp_path / "final.xodr"
    final.write_text(_XODR, encoding="utf-8")
    acceptance = tmp_path / "map_acceptance.json"
    acceptance.write_text('{"valid_for_experiments": true}', encoding="utf-8")
    manifest = tmp_path / "inputs_manifest.json"
    manifest.write_text('{"inputs": {}}', encoding="utf-8")

    ledger = ArtifactAuthorityLedger()
    ledger.freeze_structure(str(final), stage="final_artifact_authority")
    ledger.record_evidence("map_acceptance", str(final), stage="final_artifact_authority")

    receipt = ledger.build_receipt(
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
    )
    assert receipt["publication_status"] == "ACCEPTANCE_FAILED"
    assert FINAL_ARTIFACT_PUBLISHED not in receipt["capabilities_held"]


def test_build_receipt_rejects_diagnostic_purpose_release_eligible_false(tmp_path: Path):
    """Repro case C: diagnostic purpose, release_eligible explicitly False."""
    ledger, final, kwargs = _frozen_ledger(tmp_path)
    broken = {
        "valid_for_experiments": True,
        "release_eligible": False,
        "acceptance_policy": {"purpose": "diagnostic"},
        "mandatory_gates": [],
    }
    Path(kwargs["acceptance_receipt_path"]).write_text(json.dumps(broken), encoding="utf-8")

    receipt = ledger.build_receipt(
        final_artifact_path=final,
        map_acceptance=broken,
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        **kwargs,
    )
    assert receipt["publication_status"] == "ACCEPTANCE_FAILED"
    assert FINAL_ARTIFACT_PUBLISHED not in receipt["capabilities_held"]


def test_resolver_rejects_bare_diagnostic_receipt_even_if_hash_matches(tmp_path: Path):
    """Resolver-side repro of case B: a v1 receipt whose acceptance_receipt
    hash matches disk, but whose content is a bare diagnostic acceptance,
    must be rejected."""
    final = tmp_path / "final.xodr"
    final.write_text(_XODR, encoding="utf-8")
    parent = tmp_path / "parent.xodr"
    parent.write_text(_XODR, encoding="utf-8")
    acceptance = tmp_path / "map_acceptance.json"
    acceptance.write_text('{"valid_for_experiments": true}', encoding="utf-8")
    manifest = tmp_path / "inputs_manifest.json"
    manifest.write_text('{"inputs": {}}', encoding="utf-8")

    from ultimate_pipeline.contracts.artifact_authority import (
        FINAL_ARTIFACT_RECEIPT_FILENAME,
        compute_structure_fingerprint,
    )
    from ultimate_pipeline.contracts.stage_capabilities import STRUCTURE_FROZEN

    receipt = {
        "schema_version": 1,
        "receipt_kind": "final_artifact_receipt",
        "run_id": tmp_path.name,
        "created_at_utc": "2026-09-19T00:00:00+00:00",
        "producer_stage": "final_artifact_authority",
        "final_xodr": {
            "path": final.name,
            "sha256": sha256_file(str(final)),
            "bytes": final.stat().st_size,
        },
        "immediate_parent": {"path": parent.name, "sha256": sha256_file(str(parent))},
        "source_manifest": {"path": manifest.name, "sha256": sha256_file(str(manifest))},
        "git_commit": "f" * 40,
        "acceptance_receipt": {
            "path": acceptance.name,
            "sha256": sha256_file(str(acceptance)),
        },
        "capability_state": {
            "held": [FINAL_ARTIFACT_PUBLISHED, STRUCTURE_FROZEN],
            "invalidated": {},
        },
        "structure_fingerprint": compute_structure_fingerprint(str(final)),
        "final_artifact_sha256": sha256_file(str(final)),
    }
    (tmp_path / FINAL_ARTIFACT_RECEIPT_FILENAME).write_text(
        json.dumps(receipt), encoding="utf-8"
    )

    with pytest.raises(FinalArtifactReceiptError, match="not published"):
        resolve_final_artifact_receipt(str(tmp_path))


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
    acceptance.write_text(
        json.dumps(_release_payload(str(final), tmp_path.name)), encoding="utf-8"
    )
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
            map_acceptance=_release_payload(str(final), tmp_path.name),
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
        map_acceptance=_release_payload(final, tmp_path.name),
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        expected_final_sha256=expected_sha,
        **kwargs,
    )
    assert receipt["publication_status"] == "PUBLISHED", receipt["publication_reasons"]
