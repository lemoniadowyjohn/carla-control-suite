"""Gate matrix policy for RoadRunner releases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .exceptions import RoadRunnerGateError
from .models import GateStatus, SerializableContract, StageGate, validate_identifier


@dataclass(frozen=True)
class GateMatrixProfile:
    profile: str
    required_gates: frozenset[str]
    optional_gates: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", validate_identifier(self.profile, "profile"))
        object.__setattr__(self, "required_gates", frozenset(self.required_gates))
        object.__setattr__(self, "optional_gates", frozenset(self.optional_gates))
        overlap = self.required_gates & self.optional_gates
        if overlap:
            raise RoadRunnerGateError(f"gate(s) cannot be both required and optional: {sorted(overlap)}")


@dataclass(frozen=True)
class GateMatrixDecision:
    profile: str
    release_allowed: bool
    rejected_gates: tuple[str, ...]
    illegal_not_applicable_gates: tuple[str, ...]
    missing_required_gates: tuple[str, ...]


@dataclass(frozen=True)
class GateMatrix(SerializableContract):
    profiles: Mapping[str, GateMatrixProfile]

    def __post_init__(self) -> None:
        if not self.profiles:
            raise RoadRunnerGateError("gate matrix must include at least one profile")
        object.__setattr__(self, "profiles", dict(self.profiles))

    def evaluate(self, profile: str, gates: Sequence[StageGate]) -> GateMatrixDecision:
        return evaluate_gate_matrix(profile, gates, profiles=self.profiles)


DEFAULT_GATE_MATRIX: Mapping[str, GateMatrixProfile] = {
    "structural_release": GateMatrixProfile(
        profile="structural_release",
        required_gates=frozenset(
            {
                "source_integrity",
                "semantic_diff",
                "mesh_xodr_alignment",
                "artifact_hashes",
            }
        ),
        optional_gates=frozenset({"visual_mesh_quality"}),
    ),
    "visual_build": GateMatrixProfile(
        profile="visual_build",
        required_gates=frozenset({"source_integrity", "artifact_hashes", "visual_mesh_quality"}),
        optional_gates=frozenset({"semantic_diff", "mesh_xodr_alignment"}),
    ),
    "scenario_augmentation": GateMatrixProfile(
        profile="scenario_augmentation",
        required_gates=frozenset({"source_integrity", "artifact_hashes"}),
        optional_gates=frozenset({"semantic_diff", "mesh_xodr_alignment", "visual_mesh_quality"}),
    ),
    "debug": GateMatrixProfile(
        profile="debug",
        required_gates=frozenset({"artifact_hashes"}),
        optional_gates=frozenset({"source_integrity", "semantic_diff", "mesh_xodr_alignment", "visual_mesh_quality"}),
    ),
}

DEFAULT_GATE_MATRIX_MODEL = GateMatrix(DEFAULT_GATE_MATRIX)


def evaluate_gate_matrix(
    profile: str,
    gates: Sequence[StageGate],
    *,
    profiles: Mapping[str, GateMatrixProfile] = DEFAULT_GATE_MATRIX,
) -> GateMatrixDecision:
    if profile not in profiles:
        raise RoadRunnerGateError(f"unknown gate matrix profile: {profile!r}")
    matrix = profiles[profile]
    by_id = {gate.gate_id: gate for gate in gates}
    missing_required = tuple(sorted(matrix.required_gates - set(by_id)))
    rejected = tuple(
        sorted(
            gate.gate_id
            for gate in gates
            if gate.gate_id in matrix.required_gates and gate.status in {GateStatus.FAIL, GateStatus.BLOCKED}
        )
    )
    illegal_na = tuple(
        sorted(
            gate.gate_id
            for gate in gates
            if gate.status is GateStatus.NOT_APPLICABLE and gate.gate_id not in matrix.optional_gates
        )
    )
    return GateMatrixDecision(
        profile=profile,
        release_allowed=not (missing_required or rejected or illegal_na),
        rejected_gates=rejected,
        illegal_not_applicable_gates=illegal_na,
        missing_required_gates=missing_required,
    )


def assert_release_allowed(profile: str, gates: Sequence[StageGate]) -> None:
    decision = evaluate_gate_matrix(profile, gates)
    if decision.release_allowed:
        return
    raise RoadRunnerGateError(
        "RoadRunner release rejected: "
        f"failed_or_blocked={decision.rejected_gates}, "
        f"illegal_not_applicable={decision.illegal_not_applicable_gates}, "
        f"missing_required={decision.missing_required_gates}"
    )
