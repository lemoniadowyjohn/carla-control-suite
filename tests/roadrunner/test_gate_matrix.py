from __future__ import annotations

import hashlib

import pytest

from ultimate_pipeline.roadrunner import GateStatus, StageGate
from ultimate_pipeline.roadrunner.exceptions import RoadRunnerGateError
from ultimate_pipeline.roadrunner.gate_matrix import (
    DEFAULT_GATE_MATRIX,
    GateMatrix,
    GateMatrixProfile,
    assert_release_allowed,
    evaluate_gate_matrix,
)


def _sha(suffix: str = "a") -> str:
    return hashlib.sha256(suffix.encode()).hexdigest()


def _gate(gate_id: str, status: GateStatus, required: bool = True) -> StageGate:
    return StageGate(gate_id=gate_id, status=status, required=required, message=f"gate {gate_id}")


class TestGateMatrixProfile:
    def test_valid_profile(self) -> None:
        p = GateMatrixProfile(
            profile="test-profile",
            required_gates=frozenset({"gate-a", "gate-b"}),
            optional_gates=frozenset({"gate-c"}),
        )
        assert p.profile == "test-profile"
        assert "gate-a" in p.required_gates

    def test_rejects_overlap(self) -> None:
        with pytest.raises(RoadRunnerGateError, match="both required and optional"):
            GateMatrixProfile(
                profile="bad-profile",
                required_gates=frozenset({"shared-gate"}),
                optional_gates=frozenset({"shared-gate"}),
            )


class TestGateMatrix:
    def test_valid_matrix(self) -> None:
        matrix = GateMatrix(profiles={
            "p1": GateMatrixProfile(
                profile="p1",
                required_gates=frozenset({"g1"}),
            ),
        })
        assert "p1" in matrix.profiles

    def test_rejects_empty_profiles(self) -> None:
        with pytest.raises(RoadRunnerGateError, match="at least one profile"):
            GateMatrix(profiles={})


class TestEvaluateGateMatrix:
    def test_all_pass_releases(self) -> None:
        gates = [_gate("artifact_hashes", GateStatus.PASS)]
        decision = evaluate_gate_matrix("debug", gates, profiles=DEFAULT_GATE_MATRIX)
        assert decision.release_allowed is True

    def test_required_fail_blocks_release(self) -> None:
        gates = [_gate("artifact_hashes", GateStatus.FAIL)]
        decision = evaluate_gate_matrix("debug", gates, profiles=DEFAULT_GATE_MATRIX)
        assert decision.release_allowed is False
        assert "artifact_hashes" in decision.rejected_gates

    def test_required_blocked_blocks_release(self) -> None:
        gates = [_gate("artifact_hashes", GateStatus.BLOCKED)]
        decision = evaluate_gate_matrix("debug", gates, profiles=DEFAULT_GATE_MATRIX)
        assert decision.release_allowed is False

    def test_missing_required_blocks_release(self) -> None:
        decision = evaluate_gate_matrix("debug", [], profiles=DEFAULT_GATE_MATRIX)
        assert decision.release_allowed is False
        assert "artifact_hashes" in decision.missing_required_gates

    def test_optional_not_applicable_accepted(self) -> None:
        gates = [
            _gate("source_integrity", GateStatus.PASS),
            _gate("artifact_hashes", GateStatus.PASS),
            _gate("visual_mesh_quality", GateStatus.PASS),
            _gate("semantic_diff", GateStatus.NOT_APPLICABLE),
        ]
        decision = evaluate_gate_matrix("visual_build", gates, profiles=DEFAULT_GATE_MATRIX)
        assert decision.release_allowed is True

    def test_required_not_applicable_rejected(self) -> None:
        gates = [_gate("artifact_hashes", GateStatus.NOT_APPLICABLE)]
        decision = evaluate_gate_matrix("debug", gates, profiles=DEFAULT_GATE_MATRIX)
        assert decision.release_allowed is False
        assert "artifact_hashes" in decision.illegal_not_applicable_gates

    def test_unknown_profile_raises(self) -> None:
        with pytest.raises(RoadRunnerGateError, match="unknown"):
            evaluate_gate_matrix("nonexistent", [], profiles=DEFAULT_GATE_MATRIX)

    def test_structural_release_full_pass(self) -> None:
        gates = [
            _gate("source_integrity", GateStatus.PASS),
            _gate("semantic_diff", GateStatus.PASS),
            _gate("mesh_xodr_alignment", GateStatus.PASS),
            _gate("artifact_hashes", GateStatus.PASS),
        ]
        decision = evaluate_gate_matrix("structural_release", gates, profiles=DEFAULT_GATE_MATRIX)
        assert decision.release_allowed is True

    def test_structural_release_with_optional_na(self) -> None:
        gates = [
            _gate("source_integrity", GateStatus.PASS),
            _gate("semantic_diff", GateStatus.PASS),
            _gate("mesh_xodr_alignment", GateStatus.PASS),
            _gate("artifact_hashes", GateStatus.PASS),
            _gate("visual_mesh_quality", GateStatus.NOT_APPLICABLE),
        ]
        decision = evaluate_gate_matrix("structural_release", gates, profiles=DEFAULT_GATE_MATRIX)
        assert decision.release_allowed is True

    def test_scenario_augmentation_minimal(self) -> None:
        gates = [
            _gate("source_integrity", GateStatus.PASS),
            _gate("artifact_hashes", GateStatus.PASS),
        ]
        decision = evaluate_gate_matrix("scenario_augmentation", gates, profiles=DEFAULT_GATE_MATRIX)
        assert decision.release_allowed is True


class TestAssertReleaseAllowed:
    def test_passes_when_allowed(self) -> None:
        gates = [_gate("artifact_hashes", GateStatus.PASS)]
        assert_release_allowed("debug", gates)

    def test_raises_when_blocked(self) -> None:
        gates = [_gate("artifact_hashes", GateStatus.FAIL)]
        with pytest.raises(RoadRunnerGateError, match="release rejected"):
            assert_release_allowed("debug", gates)
