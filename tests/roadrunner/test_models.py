from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from ultimate_pipeline.roadrunner import (
    ArtifactRecord,
    ArtifactRole,
    AuthorityClass,
    CapabilityResult,
    ExportOptions,
    ExportProfile,
    GateStatus,
    ImportOptions,
    ImportProfile,
    InstallationCapability,
    PathKind,
    PathRef,
    RoadRunnerJobRequest,
    RoadRunnerMode,
    RunManifest,
    SerializableContract,
    SourceDataContract,
    StageGate,
    deterministic_json,
    ensure_artifact_parents,
    validate_sha256,
)
from ultimate_pipeline.roadrunner.exceptions import RoadRunnerContractError


def _sha(suffix: str = "a") -> str:
    return hashlib.sha256(suffix.encode()).hexdigest()


class TestEnumContract:
    def test_gate_status_values(self) -> None:
        assert GateStatus.PASS.value == "PASS"
        assert GateStatus.FAIL.value == "FAIL"
        assert GateStatus.BLOCKED.value == "BLOCKED"
        assert GateStatus.NOT_APPLICABLE.value == "NOT_APPLICABLE"

    def test_road_runner_mode_values(self) -> None:
        assert RoadRunnerMode.REFERENCE_ONLY.value == "REFERENCE_ONLY"
        assert RoadRunnerMode.AUTHORITATIVE_SCENE.value == "AUTHORITATIVE_SCENE"

    def test_authority_class_values(self) -> None:
        assert AuthorityClass.GOVERNED_INPUT.value == "GOVERNED_INPUT"
        assert AuthorityClass.DERIVED_CANDIDATE.value == "DERIVED_CANDIDATE"
        assert AuthorityClass.DEBUG_ONLY.value == "DEBUG_ONLY"


class TestPathRef:
    def test_valid_path(self) -> None:
        p = PathRef(path="/tmp/test.xodr", kind=PathKind.FILE)
        assert p.path == "/tmp/test.xodr"
        assert p.kind == PathKind.FILE
        assert p.must_exist is False

    def test_rejects_placeholder(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="placeholder"):
            PathRef(path="todo", kind=PathKind.FILE)

    def test_rejects_parent_traversal(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="parent traversal"):
            PathRef(path="/tmp/../etc/passwd", kind=PathKind.FILE)

    def test_rejects_nul_bytes(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="NUL"):
            PathRef(path="/tmp/\x00file", kind=PathKind.FILE)

    def test_normalizes_backslashes(self) -> None:
        p = PathRef(path="C:\\Users\\test.xodr", kind=PathKind.FILE)
        assert "/" in p.path
        assert "\\" not in p.path

    def test_coerces_enum_from_string(self) -> None:
        p = PathRef(path="/tmp/f.xodr", kind="FILE")
        assert p.kind == PathKind.FILE

    def test_rejects_must_exist_missing(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="does not exist"):
            PathRef(path="/_nonexistent_path_xxyyzz", kind=PathKind.FILE, must_exist=True)


class TestSerializableContract:
    def test_deterministic_json(self) -> None:
        data = {"b": 2, "a": 1}
        result = deterministic_json(data)
        assert result == '{"a":1,"b":2}'

    def test_to_json_sorts_keys(self) -> None:
        @dataclass(frozen=True)
        class TestContract(SerializableContract):
            z_field: str = "last"
            a_field: str = "first"

        tc = TestContract()
        expected = '{"a_field":"first","z_field":"last"}'
        assert tc.to_json(include_timestamps=True) == expected

    def test_semantic_fingerprint_excludes_timestamps(self) -> None:
        parent = _sha("fp-parent")
        job = RoadRunnerJobRequest(
            job_id="fp-job",
            mode=RoadRunnerMode.ROUNDTRIP_CANDIDATE,
            source=SourceDataContract(
                source_id="fp-src",
                path=PathRef(path="/src.xodr", kind=PathKind.FILE),
                sha256=parent,
            ),
            output_directory=PathRef(path="/out", kind=PathKind.DIRECTORY),
        )
        m_a = RunManifest(
            run_id="fp-run",
            job=job,
            artifacts=(
                ArtifactRecord(
                    artifact_id="fp-art",
                    role=ArtifactRole.STRUCTURAL_XODR,
                    path=PathRef(path="/out/r.xodr", kind=PathKind.FILE),
                    sha256=_sha("fp-art"),
                    parent_sha256=parent,
                ),
            ),
            gates=(),
            generated_at="2026-01-01T00:00:00Z",
        )
        m_b = RunManifest(
            run_id="fp-run",
            job=job,
            artifacts=(
                ArtifactRecord(
                    artifact_id="fp-art",
                    role=ArtifactRole.STRUCTURAL_XODR,
                    path=PathRef(path="/out/r.xodr", kind=PathKind.FILE),
                    sha256=_sha("fp-art"),
                    parent_sha256=parent,
                ),
            ),
            gates=(),
            generated_at="2026-07-28T23:59:59Z",
        )
        fp_a = m_a.semantic_fingerprint()
        fp_b = m_b.semantic_fingerprint()
        assert fp_a == fp_b


class TestValidateSha256:
    def test_valid_sha256(self) -> None:
        sha = _sha("valid")
        result = validate_sha256(sha)
        assert result == sha

    def test_rejects_placeholder(self) -> None:
        with pytest.raises(RoadRunnerContractError):
            validate_sha256("")

    def test_rejects_short_hash(self) -> None:
        with pytest.raises(RoadRunnerContractError):
            validate_sha256("abc123")

    def test_rejects_non_hex(self) -> None:
        with pytest.raises(RoadRunnerContractError):
            validate_sha256("g" + "0" * 63)

    def test_lowercases(self) -> None:
        sha = _sha("UPPER")
        result = validate_sha256(sha.upper())
        assert result == sha.lower()


class TestSourceDataContract:
    def test_valid_source(self) -> None:
        sha = _sha("source")
        contract = SourceDataContract(
            source_id="src-main",
            path=PathRef(path="/data/main.xodr", kind=PathKind.FILE),
            sha256=sha,
        )
        assert contract.source_id == "src-main"
        assert contract.authority_class == AuthorityClass.GOVERNED_INPUT
        assert contract.artifact_role == ArtifactRole.STRUCTURAL_XODR

    def test_rejects_non_governed_authority(self) -> None:
        sha = _sha("non-gov")
        with pytest.raises(RoadRunnerContractError, match="GOVERNED_INPUT"):
            SourceDataContract(
                source_id="src-bad",
                path=PathRef(path="/data/bad.xodr", kind=PathKind.FILE),
                sha256=sha,
                authority_class=AuthorityClass.DERIVED_CANDIDATE,
            )


class TestRoadRunnerJobRequest:
    def test_valid_job(self) -> None:
        sha = _sha("job-source")
        job = RoadRunnerJobRequest(
            job_id="job-001",
            mode=RoadRunnerMode.ROUNDTRIP_CANDIDATE,
            source=SourceDataContract(
                source_id="src-job",
                path=PathRef(path="/src.xodr", kind=PathKind.FILE),
                sha256=sha,
            ),
            output_directory=PathRef(path="/out", kind=PathKind.DIRECTORY),
        )
        assert job.job_id == "job-001"
        assert job.requested_authority == AuthorityClass.DERIVED_CANDIDATE

    def test_rejects_governed_authority(self) -> None:
        sha = _sha("gov-reject")
        with pytest.raises(RoadRunnerContractError, match="governed"):
            RoadRunnerJobRequest(
                job_id="job-gov",
                mode=RoadRunnerMode.ROUNDTRIP_CANDIDATE,
                source=SourceDataContract(
                    source_id="src-gov",
                    path=PathRef(path="/src.xodr", kind=PathKind.FILE),
                    sha256=sha,
                ),
                output_directory=PathRef(path="/out", kind=PathKind.DIRECTORY),
                requested_authority=AuthorityClass.GOVERNED_INPUT,
            )

    def test_rejects_non_directory_output(self) -> None:
        sha = _sha("output-test")
        with pytest.raises(RoadRunnerContractError, match="DIRECTORY"):
            RoadRunnerJobRequest(
                job_id="job-out",
                mode=RoadRunnerMode.ROUNDTRIP_CANDIDATE,
                source=SourceDataContract(
                    source_id="src-out",
                    path=PathRef(path="/src.xodr", kind=PathKind.FILE),
                    sha256=sha,
                ),
                output_directory=PathRef(path="/out/result.xodr", kind=PathKind.FILE),
            )


class TestArtifactRecord:
    def test_valid_artifact(self) -> None:
        parent = _sha("parent")
        art = ArtifactRecord(
            artifact_id="art-001",
            role=ArtifactRole.STRUCTURAL_XODR,
            path=PathRef(path="/out/result.xodr", kind=PathKind.FILE),
            sha256=_sha("artifact"),
            parent_sha256=parent,
        )
        assert art.artifact_id == "art-001"
        assert art.authority_class == AuthorityClass.DERIVED_CANDIDATE

    def test_rejects_governed_authority(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="governed"):
            ArtifactRecord(
                artifact_id="art-gov",
                role=ArtifactRole.STRUCTURAL_XODR,
                path=PathRef(path="/out/r.xodr", kind=PathKind.FILE),
                sha256=_sha("gov-art"),
                parent_sha256=_sha("parent"),
                authority_class=AuthorityClass.GOVERNED_INPUT,
            )

    def test_requires_parent_sha256(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="parent_sha256"):
            ArtifactRecord(
                artifact_id="art-no-parent",
                role=ArtifactRole.STRUCTURAL_XODR,
                path=PathRef(path="/out/r.xodr", kind=PathKind.FILE),
                sha256=_sha("no-parent"),
                parent_sha256=None,
            )


class TestStageGate:
    def test_valid_gate(self) -> None:
        gate = StageGate(
            gate_id="gate-001",
            status=GateStatus.PASS,
            required=True,
            message="All checks passed",
        )
        assert gate.gate_id == "gate-001"
        assert gate.status == GateStatus.PASS

    def test_rejects_placeholder_message(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="placeholder"):
            StageGate(
                gate_id="gate-bad",
                status=GateStatus.FAIL,
                required=True,
                message="todo",
            )

    def test_fail_gates_with_required(self) -> None:
        gate = StageGate(
            gate_id="gate-fail",
            status=GateStatus.FAIL,
            required=True,
            message="gate failed",
        )
        assert gate.status == GateStatus.FAIL
        assert gate.required is True


class TestRunManifest:
    def test_valid_manifest(self) -> None:
        parent = _sha("manifest-parent")
        manifest = RunManifest(
            run_id="run-001",
            job=RoadRunnerJobRequest(
                job_id="job-001",
                mode=RoadRunnerMode.ROUNDTRIP_CANDIDATE,
                source=SourceDataContract(
                    source_id="src-manifest",
                    path=PathRef(path="/src.xodr", kind=PathKind.FILE),
                    sha256=parent,
                ),
                output_directory=PathRef(path="/out", kind=PathKind.DIRECTORY),
            ),
            artifacts=(
                ArtifactRecord(
                    artifact_id="art-001",
                    role=ArtifactRole.STRUCTURAL_XODR,
                    path=PathRef(path="/out/r.xodr", kind=PathKind.FILE),
                    sha256=_sha("manifest-art"),
                    parent_sha256=parent,
                ),
            ),
            gates=(),
        )
        assert manifest.run_id == "run-001"

    def test_rejects_empty_artifacts(self) -> None:
        parent = _sha("empty-art")
        with pytest.raises(RoadRunnerContractError, match="at least one artifact"):
            RunManifest(
                run_id="run-empty",
                job=RoadRunnerJobRequest(
                    job_id="job-empty",
                    mode=RoadRunnerMode.ROUNDTRIP_CANDIDATE,
                    source=SourceDataContract(
                        source_id="src-empty",
                        path=PathRef(path="/src.xodr", kind=PathKind.FILE),
                        sha256=parent,
                    ),
                    output_directory=PathRef(path="/out", kind=PathKind.DIRECTORY),
                ),
                artifacts=(),
                gates=(),
            )

    def test_rejects_duplicate_artifact_ids(self) -> None:
        parent = _sha("dup")
        with pytest.raises(RoadRunnerContractError, match="unique"):
            RunManifest(
                run_id="run-dup",
                job=RoadRunnerJobRequest(
                    job_id="job-dup",
                    mode=RoadRunnerMode.ROUNDTRIP_CANDIDATE,
                    source=SourceDataContract(
                        source_id="src-dup",
                        path=PathRef(path="/src.xodr", kind=PathKind.FILE),
                        sha256=parent,
                    ),
                    output_directory=PathRef(path="/out", kind=PathKind.DIRECTORY),
                ),
                artifacts=(
                    ArtifactRecord(
                        artifact_id="same-id",
                        role=ArtifactRole.STRUCTURAL_XODR,
                        path=PathRef(path="/out/a.xodr", kind=PathKind.FILE),
                        sha256=_sha("a"),
                        parent_sha256=parent,
                    ),
                    ArtifactRecord(
                        artifact_id="same-id",
                        role=ArtifactRole.STRUCTURAL_XODR,
                        path=PathRef(path="/out/b.xodr", kind=PathKind.FILE),
                        sha256=_sha("b"),
                        parent_sha256=parent,
                    ),
                ),
                gates=(),
            )


class TestEnsureArtifactParents:
    def test_all_match(self) -> None:
        parent = _sha("match-parent")
        artifacts = (
            ArtifactRecord(
                artifact_id="a1",
                role=ArtifactRole.STRUCTURAL_XODR,
                path=PathRef(path="/out/a.xodr", kind=PathKind.FILE),
                sha256=_sha("a"),
                parent_sha256=parent,
            ),
        )
        ensure_artifact_parents(artifacts, parent)

    def test_mismatch_raises(self) -> None:
        parent = _sha("real-parent")
        artifacts = (
            ArtifactRecord(
                artifact_id="a1",
                role=ArtifactRole.STRUCTURAL_XODR,
                path=PathRef(path="/out/a.xodr", kind=PathKind.FILE),
                sha256=_sha("a"),
                parent_sha256=_sha("other"),
            ),
        )
        with pytest.raises(RoadRunnerContractError, match="does not match"):
            ensure_artifact_parents(artifacts, parent)


class TestImportExportOptions:
    def test_import_options_defaults(self) -> None:
        opts = ImportOptions()
        assert opts.preserve_lane_ids is True
        assert opts.strict_schema is True

    def test_export_options_defaults(self) -> None:
        opts = ExportOptions()
        assert opts.include_diagnostics is True
        assert ArtifactRole.RRSCENE in opts.export_roles

    def test_export_options_rejects_empty_roles(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="export_roles"):
            ExportOptions(export_roles=())

    def test_import_profile_inherits(self) -> None:
        profile = ImportProfile(preserve_lane_ids=False)
        assert profile.preserve_lane_ids is False

    def test_export_profile_inherits(self) -> None:
        profile = ExportProfile(include_diagnostics=False)
        assert profile.include_diagnostics is False


class TestInstallationCapability:
    def test_valid_capability(self) -> None:
        cap = InstallationCapability(
            capability_id="cap-rr-basic",
            adapter_name="rr-local",
            supported_modes=(RoadRunnerMode.REFERENCE_ONLY,),
            supported_imports=("xodr",),
            supported_exports=(ArtifactRole.RRSCENE,),
        )
        assert cap.capability_id == "cap-rr-basic"

    def test_rejects_empty_modes(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="supported_modes"):
            InstallationCapability(
                capability_id="cap-empty",
                adapter_name="rr-empty",
                supported_modes=(),
                supported_imports=("xodr",),
                supported_exports=(ArtifactRole.RRSCENE,),
            )

    def test_rejects_empty_exports(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="supported_exports"):
            InstallationCapability(
                capability_id="cap-no-exports",
                adapter_name="rr-no-export",
                supported_modes=(RoadRunnerMode.REFERENCE_ONLY,),
                supported_imports=("xodr",),
                supported_exports=(),
            )
