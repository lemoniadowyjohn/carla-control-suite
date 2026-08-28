"""ultimate_pipeline/roadrunner/manifest.py -- build_run_manifest (gate-profile enforcement
before accepting a RoadRunner run manifest) and artifact_fingerprints (deterministic sha256
ordering). Found untested while auditing tests/roadrunner/ coverage against
ultimate_pipeline/roadrunner/'s actual module list.
"""
from __future__ import annotations

import pytest

from ultimate_pipeline.roadrunner.exceptions import RoadRunnerGateError
from ultimate_pipeline.roadrunner.manifest import artifact_fingerprints, build_run_manifest
from ultimate_pipeline.roadrunner.models import (
    ArtifactRecord,
    ArtifactRole,
    GateStatus,
    PathKind,
    PathRef,
    RoadRunnerJobRequest,
    RoadRunnerMode,
    RunManifest,
    SourceDataContract,
    StageGate,
)

SOURCE_SHA = "a" * 64
PARENT_SHA = SOURCE_SHA  # artifacts must reference the source's sha256 as their parent


def _source():
    return SourceDataContract(
        source_id="ingolstadt_auto",
        path=PathRef(path="candidate/map.xodr", kind=PathKind.FILE),
        sha256=SOURCE_SHA,
    )


def _job():
    return RoadRunnerJobRequest(
        job_id="job1",
        mode=RoadRunnerMode.REFERENCE_ONLY,
        source=_source(),
        output_directory=PathRef(path="out/", kind=PathKind.DIRECTORY),
    )


def _artifact(artifact_id="artifact1", sha256="b" * 64):
    return ArtifactRecord(
        artifact_id=artifact_id,
        role=ArtifactRole.RRSCENE,
        path=PathRef(path=f"out/{artifact_id}.rrscene", kind=PathKind.FILE),
        sha256=sha256,
        parent_sha256=PARENT_SHA,
    )


def _passing_gate(gate_id="artifact_hashes"):
    return StageGate(gate_id=gate_id, status=GateStatus.PASS, required=True, message="verified")


def _failing_gate(gate_id="artifact_hashes"):
    return StageGate(gate_id=gate_id, status=GateStatus.FAIL, required=True, message="hash mismatch")


def _manifest(gates):
    return RunManifest(
        run_id="run1",
        job=_job(),
        artifacts=(_artifact(),),
        gates=gates,
    )


# ---------------------------------------------------------------------------
# build_run_manifest
# ---------------------------------------------------------------------------

def test_build_run_manifest_accepts_when_gate_profile_satisfied():
    manifest = _manifest((_passing_gate(),))
    result = build_run_manifest(manifest, gate_profile="debug")
    assert result is manifest


def test_build_run_manifest_rejects_when_required_gate_fails():
    manifest = _manifest((_failing_gate(),))
    with pytest.raises(RoadRunnerGateError, match="does not satisfy gate profile"):
        build_run_manifest(manifest, gate_profile="debug")


def test_build_run_manifest_rejects_when_artifact_parent_mismatches_source():
    bad_artifact = ArtifactRecord(
        artifact_id="artifact1",
        role=ArtifactRole.RRSCENE,
        path=PathRef(path="out/a.rrscene", kind=PathKind.FILE),
        sha256="b" * 64,
        parent_sha256="c" * 64,  # does NOT match the source's sha256
    )
    manifest = RunManifest(
        run_id="run1",
        job=_job(),
        artifacts=(bad_artifact,),
        gates=(_passing_gate(),),
    )
    with pytest.raises(Exception):  # RoadRunnerContractError, from ensure_artifact_parents
        build_run_manifest(manifest, gate_profile="debug")


def test_build_run_manifest_unknown_profile_raises():
    manifest = _manifest((_passing_gate(),))
    with pytest.raises(RoadRunnerGateError, match="unknown gate matrix profile"):
        build_run_manifest(manifest, gate_profile="not_a_real_profile")


# ---------------------------------------------------------------------------
# artifact_fingerprints
# ---------------------------------------------------------------------------

def test_artifact_fingerprints_returns_sha256_tuple():
    manifest = _manifest((_passing_gate(),))
    fingerprints = artifact_fingerprints(manifest)
    assert fingerprints == ("b" * 64,)


def test_artifact_fingerprints_sorted_by_artifact_id_deterministically():
    a1 = _artifact(artifact_id="zzz", sha256="1" * 64)
    a2 = _artifact(artifact_id="aaa", sha256="2" * 64)
    manifest = RunManifest(
        run_id="run1",
        job=_job(),
        artifacts=(a1, a2),
        gates=(_passing_gate(),),
    )
    # sorted by artifact_id ("aaa" before "zzz") -> "2"*64 comes first regardless of input order
    assert artifact_fingerprints(manifest) == ("2" * 64, "1" * 64)
