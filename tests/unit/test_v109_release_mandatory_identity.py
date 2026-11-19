"""V109: release acceptance cannot shrink mandatory gates or omit artifact identity."""
from __future__ import annotations

import hashlib

import pytest

from ultimate_pipeline.quality.final_artifact_gates import RELEASE_MANDATORY_GATES
from ultimate_pipeline.quality.map_acceptance import build_map_acceptance


@pytest.mark.parametrize(
    "gates",
    [
        ("artifact_structure",),
        ("artifact_structure", "artifact_structure"),
        ("made_up_gate",),
        tuple(RELEASE_MANDATORY_GATES[:-1]),
        tuple(RELEASE_MANDATORY_GATES) + ("unrelated",),
        tuple(RELEASE_MANDATORY_GATES[:-1]) + ("artifact_structure",),
    ],
)
def test_release_mandatory_set_cannot_be_redefined(gates):
    reports = {g: {"ok": True} for g in gates}
    with pytest.raises(ValueError, match="RELEASE_MANDATORY_GATES"):
        build_map_acceptance(reports, purpose="release", mandatory_gates=gates)


def test_release_cannot_be_certified_without_artifact_identity(tmp_path):
    reports = {gate: {"ok": True} for gate in RELEASE_MANDATORY_GATES}
    candidate = tmp_path / "candidate.xodr"
    candidate.write_bytes(b"map bytes bound to the acceptance receipt")
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()

    missing = build_map_acceptance(
        reports, purpose="release", mandatory_gates=RELEASE_MANDATORY_GATES,
    )
    assert missing["release_eligible"] is False
    assert "artifact_identity" in missing["failed_gates"]

    no_evaluation = build_map_acceptance(
        reports, purpose="release", mandatory_gates=RELEASE_MANDATORY_GATES,
        final_xodr_path=str(candidate),
    )
    assert no_evaluation["release_eligible"] is False
    assert "artifact_identity" in no_evaluation["failed_gates"]

    missing_artifact = build_map_acceptance(
        reports, purpose="release", mandatory_gates=RELEASE_MANDATORY_GATES,
        evaluated_xodr_sha256=digest,
    )
    assert missing_artifact["release_eligible"] is False
    assert "artifact_identity" in missing_artifact["failed_gates"]

    mismatch = build_map_acceptance(
        reports, purpose="release", mandatory_gates=RELEASE_MANDATORY_GATES,
        final_xodr_path=str(candidate), evaluated_xodr_sha256="0" * 64,
    )
    assert mismatch["release_eligible"] is False
    assert "artifact_identity" in mismatch["failed_gates"]

    verified = build_map_acceptance(
        reports, purpose="release", mandatory_gates=RELEASE_MANDATORY_GATES,
        final_xodr_path=str(candidate), evaluated_xodr_sha256=digest,
    )
    assert verified["release_eligible"] is True
    assert verified["final_xodr_sha256"] == verified["evaluated_xodr_sha256"]


def test_diagnostic_does_not_claim_release_even_with_all_reports():
    reports = {gate: {"ok": True} for gate in RELEASE_MANDATORY_GATES}
    verdict = build_map_acceptance(
        reports, purpose="diagnostic", mandatory_gates=RELEASE_MANDATORY_GATES,
    )
    assert verdict["valid_for_experiments"] is True
    assert verdict["release_eligible"] is False
