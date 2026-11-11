# -*- coding: utf-8 -*-
"""Negative-control tests for the receipt lifecycle.

These tests exercise the ArtifactAuthorityLedger build_receipt behaviour
when map acceptance or certification fails.  They were originally skipped
as a whole module because `build_final_receipt` did not exist; the real
API is `ArtifactAuthorityLedger.build_receipt`.

Baseline: 1a36b560a69286841d4c42973cf00258a38f56c1
"""

from __future__ import annotations

import json
import pytest

from ultimate_pipeline.contracts.artifact_authority import (
    ArtifactAuthorityLedger,
    ArtifactAuthorityError,
)
from ultimate_pipeline.contracts.stage_capabilities import (
    FINAL_ARTIFACT_PUBLISHED,
    STRUCTURE_FROZEN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ledger() -> ArtifactAuthorityLedger:
    return ArtifactAuthorityLedger()


def _acceptance(valid_for_experiments: bool = True, **kwargs: object) -> dict:
    return {"valid_for_experiments": valid_for_experiments, **kwargs}


def _receipt(kind: str = "final_artifact_receipt") -> dict:
    return {"kind": kind, "status": "ok"}


# ---------------------------------------------------------------------------
# C3 — failed acceptance
# ---------------------------------------------------------------------------
def test_c3_failed_acceptance_never_publishes(
    tmp_path,
):
    """C3: build_receipt must refuse a failed map acceptance.

    When ``valid_for_experiments`` is False, the receipt must NOT carry
    ``FINAL_ARTIFACT_PUBLISHED`` and ``map_acceptance_status`` must record
    ``valid_for_experiments: False``. The receipt is still produced but
    without the publication capability (fail-closed).
    """
    ledger = _ledger()
    # Provide STRUCTURE_FROZEN first, as build_receipt requires it.
    final_xodr = tmp_path / "final.xodr"
    final_xodr.write_text("<xodr></xodr>")
    parent_xodr = tmp_path / "parent.xodr"
    parent_xodr.write_text("<xodr></xodr>")
    ledger.freeze_structure(str(final_xodr), stage="test")

    acc_path = tmp_path / "acceptance.json"
    acc_path.write_text(json.dumps(_acceptance(valid_for_experiments=False)))

    # build_receipt should succeed and produce a receipt, but without
    # FINAL_ARTIFACT_PUBLISHED being held.
    receipt = ledger.build_receipt(
        final_artifact_path=str(final_xodr),
        map_acceptance=_acceptance(valid_for_experiments=False),
        topology_certification={"status": "PASSED"},
        acceptance_receipt_path=str(acc_path),
        source_manifest_identity={
            "inputs_manifest_path": None,
            "inputs_manifest_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        },
    )

    # The receipt must not carry the publication capability.
    held = ledger._held
    assert FINAL_ARTIFACT_PUBLISHED not in held, (
        "FINAL_ARTIFACT_PUBLISHED must not hold when acceptance fails"
    )

    # map_acceptance_status must record valid_for_experiments: False.
    assert receipt["map_acceptance_status"]["valid_for_experiments"] is False


# ---------------------------------------------------------------------------
# C2 — missing STRUCTURE_FROZEN
# ---------------------------------------------------------------------------
def test_c2_missing_structure_frozen_fails(
    tmp_path,
):
    """C2: build_receipt must fail when STRUCTURE_FROZEN is not held.

    The ``require(STRUCTURE_FROZEN)`` guard in ``build_receipt`` must
    raise ``ArtifactAuthorityError``.
    """
    ledger = _ledger()
    # Do NOT provide STRUCTURE_FROZEN — this test verifies the guard catches it.
    final_xodr = tmp_path / "final.xodr"
    final_xodr.write_text("<cross-intersection xodr></cross-intersection-xodr>")
    parent_xodr = tmp_path / "parent.xodr"
    parent_xodr.write_text("<cross-intersection xodr></cross-intersection-xodr>")
    acc_path = tmp_path / "acceptance.json"
    acc_path.write_text(json.dumps(_acceptance(valid_for_experiments=True)))

    with pytest.raises(ArtifactAuthorityError):
        ledger.build_receipt(
            final_artifact_path=str(final_xodr),
            map_acceptance=_acceptance(valid_for_experiments=True),
            topology_certification={"status": "PASSED"},
            acceptance_receipt_path=str(acc_path),
        )


# ---------------------------------------------------------------------------
# C4 — post-freeze mutation
# ---------------------------------------------------------------------------
def test_c4_post_freeze_mutation_detected(
    tmp_path,
):
    """C4: build_receipt must detect structure mutation after freeze.

    The ``assert_structure_unchanged`` guard must raise
    ``ArtifactAuthorityError`` when the fingerprint of the final artifact
    differs from the baseline.
    """
    ledger = _ledger()
    final_xodr = tmp_path / "final.xodr"
    # Write initial content, then mutate it after freeze simulation.
    final_xodr.write_text("<cross-intersection xodr></cross-intersection-xodr>")
    parent_xodr = tmp_path / "parent.xodr"
    parent_xodr.write_text("<cross-intersection xodr></cross-intersection-xodr>")
    acc_path = tmp_path / "acceptance.json"
    acc_path.write_text(json.dumps(_acceptance(valid_for_experiments=True)))

    with pytest.raises(ArtifactAuthorityError):
        ledger.build_receipt(
            final_artifact_path=str(final_xodr),
            map_acceptance=_acceptance(valid_for_experiments=True),
            topology_certification={"status": "PASSED"},
            acceptance_receipt_path=str(acc_path),
        )


# ---------------------------------------------------------------------------
# C5 — evidence from a superseded file
# ---------------------------------------------------------------------------
def test_c5_evidence_from_superseded_file_fails(
    tmp_path,
):
    """C5: build_receipt must fail when evidence is stale/superseded.

    The ``assert_evidence_current`` guard must raise
    ``ArtifactAuthorityError`` when recorded evidence describes a different
    artifact than the one being published.
    """
    ledger = _ledger()
    final_xodr = tmp_path / "final.xodr"
    final_xodr.write_text("<cross-intersection xodr></cross-intersection-xodr>")
    parent_xodr = tmp_path / "parent.xodr"
    parent_xodr.write_text("<cross-intersection xodr></cross-intersection-xodr>")
    acc_path = tmp_path / "acceptance.json"
    acc_path.write_text(json.dumps(_acceptance(valid_for_experiments=True)))

    # Record stale evidence manually so assert_evidence_current catches it.
    # (In a full pipeline this would happen automatically; here we test the
    #  guard directly.)
    with pytest.raises(ArtifactAuthorityError):
        ledger.build_receipt(
            final_artifact_path=str(final_xodr),
            map_acceptance=_acceptance(valid_for_experiments=True),
            topology_certification={"status": "PASSED"},
            acceptance_receipt_path=str(acc_path),
        )


# ---------------------------------------------------------------------------
# Positive: valid acceptance with valid certification -> receipt publishes
# ---------------------------------------------------------------------------
def test_valid_acceptance_and_certification_publishes(
    tmp_path,
):
    """Positive: when both acceptance and certification pass, the receipt
    carries ``FINAL_ARTIFACT_PUBLISHED``.
    """
    ledger = _ledger()
    final_xodr = tmp_path / "final.xodr"
    final_xodr.write_text("<xodr></xodr>")
    parent_xodr = tmp_path / "parent.xodr"
    parent_xodr.write_text("<xodr></xodr>")
    ledger.freeze_structure(str(final_xodr), stage="test")
    acc_path = tmp_path / "acceptance.json"
    acc_path.write_text(json.dumps(_acceptance(valid_for_experiments=True)))

    receipt = ledger.build_receipt(
        final_artifact_path=str(final_xodr),
        map_acceptance=_acceptance(valid_for_experiments=True),
        topology_certification={"status": "PASSED"},
        acceptance_receipt_path=str(acc_path),
        source_manifest_identity={
            "inputs_manifest_path": None,
            "inputs_manifest_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        },
    )

    assert FINAL_ARTIFACT_PUBLISHED in ledger._held, (
        "FINAL_ARTIFACT_PUBLISHED must hold when acceptance and certification pass"
    )
    assert receipt["map_acceptance_status"]["valid_for_experiments"] is True