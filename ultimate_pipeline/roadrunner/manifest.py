"""Run manifest helpers for optional RoadRunner backend contracts."""

from __future__ import annotations

from .gate_matrix import evaluate_gate_matrix
from .models import ArtifactRecord, RunManifest, ensure_artifact_parents


def build_run_manifest(manifest: RunManifest, *, gate_profile: str) -> RunManifest:
    ensure_artifact_parents(manifest.artifacts, manifest.job.source.sha256)
    decision = evaluate_gate_matrix(gate_profile, manifest.gates)
    if not decision.release_allowed:
        from .exceptions import RoadRunnerGateError

        raise RoadRunnerGateError(
            "RoadRunner manifest does not satisfy gate profile "
            f"{gate_profile!r}: {decision}"
        )
    return manifest


def artifact_fingerprints(manifest: RunManifest) -> tuple[str, ...]:
    artifacts: tuple[ArtifactRecord, ...] = tuple(sorted(manifest.artifacts, key=lambda item: item.artifact_id))
    return tuple(artifact.sha256 for artifact in artifacts)


__all__ = ["RunManifest", "build_run_manifest", "artifact_fingerprints"]
