"""Typed dependency-free RoadRunner backend contracts.

The classes in this module describe data exchanged with an optional
RoadRunner backend. They intentionally do not import or execute RoadRunner.
All JSON serialization is deterministic: object keys are sorted and compact
separators are used so equivalent contracts produce identical bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .exceptions import RoadRunnerContractError


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDERS = {
    "",
    "placeholder",
    "todo",
    "tbd",
    "unknown",
    "none",
    "null",
    "changeme",
    "replace_me",
    "replace-me",
    "0000000000000000000000000000000000000000000000000000000000000000",
}
_TIMESTAMP_FIELD_NAMES = frozenset(
    {
        "created_at",
        "updated_at",
        "completed_at",
        "started_at",
        "generated_at",
        "timestamp",
    }
)


class GateStatus(Enum):
    """Status reported by a RoadRunner stage gate."""

    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RoadRunnerMode(Enum):
    """Supported optional RoadRunner integration modes."""

    REFERENCE_ONLY = "REFERENCE_ONLY"
    ROUNDTRIP_CANDIDATE = "ROUNDTRIP_CANDIDATE"
    AUTHORITATIVE_SCENE = "AUTHORITATIVE_SCENE"
    VISUAL_BUILD_ONLY = "VISUAL_BUILD_ONLY"
    PLUGIN_EXPERIMENT = "PLUGIN_EXPERIMENT"


class ArtifactRole(Enum):
    """Role of a RoadRunner-related artifact."""

    STRUCTURAL_XODR = "STRUCTURAL_XODR"
    RRSCENE = "RRSCENE"
    VISUAL_MESH = "VISUAL_MESH"
    TILED_VISUAL_MESH = "TILED_VISUAL_MESH"
    CARLA_PACKAGE = "CARLA_PACKAGE"
    DIAGNOSTIC = "DIAGNOSTIC"


class AuthorityClass(Enum):
    """Authority class assigned to source and derived artifacts."""

    GOVERNED_INPUT = "GOVERNED_INPUT"
    DERIVED_CANDIDATE = "DERIVED_CANDIDATE"
    VISUAL_ONLY = "VISUAL_ONLY"
    SYNTHETIC_SCENARIO = "SYNTHETIC_SCENARIO"
    DEBUG_ONLY = "DEBUG_ONLY"


class PathKind(Enum):
    """Explicit classification for contract paths."""

    FILE = "FILE"
    DIRECTORY = "DIRECTORY"
    ARTIFACT = "ARTIFACT"


def _coerce_enum(enum_type: type[Enum], value: Enum | str, field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as exc:
            raise RoadRunnerContractError(
                f"{field_name} must be one of {[item.value for item in enum_type]}, got {value!r}"
            ) from exc
    raise RoadRunnerContractError(f"{field_name} must be {enum_type.__name__} or str")


def _reject_placeholder(value: str, field_name: str) -> None:
    normalized = value.strip().lower()
    if normalized in _PLACEHOLDERS or normalized.startswith(("todo:", "placeholder:")):
        raise RoadRunnerContractError(f"{field_name} cannot be a placeholder value")


def validate_identifier(value: str, field_name: str) -> str:
    """Validate a stable non-placeholder identifier."""

    if not isinstance(value, str):
        raise RoadRunnerContractError(f"{field_name} must be a string")
    stripped = value.strip()
    _reject_placeholder(stripped, field_name)
    if any(ch.isspace() for ch in stripped):
        raise RoadRunnerContractError(f"{field_name} must not contain whitespace")
    return stripped


def validate_sha256(value: str, field_name: str = "sha256") -> str:
    """Validate a non-placeholder lowercase SHA-256 digest."""

    if not isinstance(value, str):
        raise RoadRunnerContractError(f"{field_name} must be a string")
    lowered = value.strip().lower()
    _reject_placeholder(lowered, field_name)
    if SHA256_RE.fullmatch(lowered) is None:
        raise RoadRunnerContractError(f"{field_name} must be a 64-character lowercase SHA-256 hex digest")
    return lowered


def _validate_mapping(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RoadRunnerContractError(f"{field_name} must be a mapping")
    return dict(value)


def utc_now_iso() -> str:
    """Return a UTC ISO-8601 timestamp for non-fingerprint metadata."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SerializableContract:
    """Mixin for deterministic JSON serialization and semantic fingerprints."""

    def to_dict(self, *, include_timestamps: bool = True) -> dict[str, Any]:
        """Convert the contract to JSON-compatible primitives."""

        return _to_primitive(self, include_timestamps=include_timestamps)

    def to_json(self, *, include_timestamps: bool = True) -> str:
        """Serialize the contract deterministically to JSON."""

        return deterministic_json(self.to_dict(include_timestamps=include_timestamps))

    def semantic_fingerprint(self) -> str:
        """Hash semantic content while excluding timestamp fields."""

        payload = self.to_json(include_timestamps=False).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def _to_primitive(value: Any, *, include_timestamps: bool) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value):
        result: dict[str, Any] = {}
        for item in fields(value):
            if not include_timestamps and (
                item.name in _TIMESTAMP_FIELD_NAMES or item.name.endswith("_timestamp")
            ):
                continue
            result[item.name] = _to_primitive(getattr(value, item.name), include_timestamps=include_timestamps)
        return result
    if isinstance(value, Mapping):
        return {
            str(key): _to_primitive(inner, include_timestamps=include_timestamps)
            for key, inner in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_to_primitive(inner, include_timestamps=include_timestamps) for inner in value]
    return value


def deterministic_json(value: Any) -> str:
    """Serialize JSON-compatible values with deterministic key order."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class PathRef(SerializableContract):
    """Explicit path representation used by all RoadRunner contracts."""

    path: str
    kind: PathKind
    must_exist: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_enum(PathKind, self.kind, "kind"))
        if not isinstance(self.path, str):
            raise RoadRunnerContractError("path must be a string")
        normalized = self.path.strip().replace("\\", "/")
        _reject_placeholder(normalized, "path")
        if "\x00" in normalized:
            raise RoadRunnerContractError("path must not contain NUL bytes")
        if normalized in {".", ".."} or "/../" in f"/{normalized}/":
            raise RoadRunnerContractError("path must not contain parent traversal")
        if self.must_exist and not Path(normalized).exists():
            raise RoadRunnerContractError(f"path does not exist: {normalized}")
        object.__setattr__(self, "path", normalized)


@dataclass(frozen=True)
class InstallationCapability(SerializableContract):
    """Declared capability of a RoadRunner installation or adapter."""

    capability_id: str
    adapter_name: str
    supported_modes: tuple[RoadRunnerMode, ...]
    supported_imports: tuple[str, ...]
    supported_exports: tuple[ArtifactRole, ...]
    version: str | None = None
    executable_path: PathRef | None = None
    plugin_paths: tuple[PathRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability_id", validate_identifier(self.capability_id, "capability_id"))
        object.__setattr__(self, "adapter_name", validate_identifier(self.adapter_name, "adapter_name"))
        object.__setattr__(
            self,
            "supported_modes",
            tuple(_coerce_enum(RoadRunnerMode, mode, "supported_modes") for mode in self.supported_modes),
        )
        object.__setattr__(
            self,
            "supported_exports",
            tuple(_coerce_enum(ArtifactRole, role, "supported_exports") for role in self.supported_exports),
        )
        object.__setattr__(
            self,
            "supported_imports",
            tuple(validate_identifier(item, "supported_imports") for item in self.supported_imports),
        )
        if not self.supported_modes:
            raise RoadRunnerContractError("supported_modes must not be empty")
        if not self.supported_exports:
            raise RoadRunnerContractError("supported_exports must not be empty")
        if self.version is not None:
            _reject_placeholder(self.version.strip(), "version")
        object.__setattr__(self, "plugin_paths", tuple(self.plugin_paths))


@dataclass(frozen=True)
class CapabilityResult(SerializableContract):
    """Capability check result for a RoadRunner adapter or installation."""

    result_id: str
    capability: InstallationCapability
    available: bool
    diagnostics: tuple[str, ...] = ()
    checked_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_id", validate_identifier(self.result_id, "result_id"))
        object.__setattr__(self, "diagnostics", tuple(str(item) for item in self.diagnostics))


@dataclass(frozen=True)
class SourceDataContract(SerializableContract):
    """Contract for governed source data entering a RoadRunner workflow."""

    source_id: str
    path: PathRef
    sha256: str
    artifact_role: ArtifactRole = ArtifactRole.STRUCTURAL_XODR
    authority_class: AuthorityClass = AuthorityClass.GOVERNED_INPUT
    coordinate_reference: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", validate_identifier(self.source_id, "source_id"))
        object.__setattr__(self, "sha256", validate_sha256(self.sha256))
        object.__setattr__(self, "artifact_role", _coerce_enum(ArtifactRole, self.artifact_role, "artifact_role"))
        object.__setattr__(
            self,
            "authority_class",
            _coerce_enum(AuthorityClass, self.authority_class, "authority_class"),
        )
        if self.authority_class is not AuthorityClass.GOVERNED_INPUT:
            raise RoadRunnerContractError("source data must use GOVERNED_INPUT authority")
        if self.coordinate_reference is not None:
            _reject_placeholder(self.coordinate_reference.strip(), "coordinate_reference")
        object.__setattr__(self, "metadata", _validate_mapping(self.metadata, "metadata"))


@dataclass(frozen=True)
class ImportOptions(SerializableContract):
    """Options controlling import into RoadRunner without executing it."""

    preserve_lane_ids: bool = True
    preserve_signal_ids: bool = True
    import_elevation: bool = True
    import_lane_markings: bool = True
    strict_schema: bool = True
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", _validate_mapping(self.extra, "extra"))


@dataclass(frozen=True)
class ExportOptions(SerializableContract):
    """Options describing expected RoadRunner export artifacts."""

    export_roles: tuple[ArtifactRole, ...] = (ArtifactRole.RRSCENE,)
    include_diagnostics: bool = True
    deterministic_export: bool = True
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        roles = tuple(_coerce_enum(ArtifactRole, role, "export_roles") for role in self.export_roles)
        if not roles:
            raise RoadRunnerContractError("export_roles must not be empty")
        object.__setattr__(self, "export_roles", roles)
        object.__setattr__(self, "extra", _validate_mapping(self.extra, "extra"))


@dataclass(frozen=True)
class ImportProfile(ImportOptions):
    """Named import profile model; equivalent to RoadRunner import options."""


@dataclass(frozen=True)
class ExportProfile(ExportOptions):
    """Named export profile model; equivalent to RoadRunner export options."""


@dataclass(frozen=True)
class RoadRunnerJobRequest(SerializableContract):
    """Request contract for an optional RoadRunner backend job."""

    job_id: str
    mode: RoadRunnerMode
    source: SourceDataContract
    output_directory: PathRef
    import_options: ImportOptions = field(default_factory=ImportOptions)
    export_options: ExportOptions = field(default_factory=ExportOptions)
    requested_authority: AuthorityClass = AuthorityClass.DERIVED_CANDIDATE
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", validate_identifier(self.job_id, "job_id"))
        object.__setattr__(self, "mode", _coerce_enum(RoadRunnerMode, self.mode, "mode"))
        object.__setattr__(
            self,
            "requested_authority",
            _coerce_enum(AuthorityClass, self.requested_authority, "requested_authority"),
        )
        if self.requested_authority is AuthorityClass.GOVERNED_INPUT:
            raise RoadRunnerContractError("RoadRunner candidates cannot request governed authority")
        if self.output_directory.kind is not PathKind.DIRECTORY:
            raise RoadRunnerContractError("output_directory must use DIRECTORY path kind")


@dataclass(frozen=True)
class ArtifactRecord(SerializableContract):
    """Record for a produced or referenced RoadRunner artifact."""

    artifact_id: str
    role: ArtifactRole
    path: PathRef
    sha256: str
    authority_class: AuthorityClass = AuthorityClass.DERIVED_CANDIDATE
    parent_sha256: str | None = None
    media_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", validate_identifier(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "role", _coerce_enum(ArtifactRole, self.role, "role"))
        object.__setattr__(self, "sha256", validate_sha256(self.sha256))
        object.__setattr__(
            self,
            "authority_class",
            _coerce_enum(AuthorityClass, self.authority_class, "authority_class"),
        )
        if self.authority_class is AuthorityClass.GOVERNED_INPUT:
            raise RoadRunnerContractError("RoadRunner artifact candidates cannot use governed authority")
        if self.parent_sha256 is None:
            raise RoadRunnerContractError("candidate artifacts must reference parent_sha256")
        object.__setattr__(self, "parent_sha256", validate_sha256(self.parent_sha256, "parent_sha256"))
        if self.media_type is not None:
            _reject_placeholder(self.media_type.strip(), "media_type")
        object.__setattr__(self, "metadata", _validate_mapping(self.metadata, "metadata"))


@dataclass(frozen=True)
class StageGate(SerializableContract):
    """A RoadRunner release or diagnostic gate result."""

    gate_id: str
    status: GateStatus
    required: bool
    message: str
    evidence_paths: tuple[PathRef, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_id", validate_identifier(self.gate_id, "gate_id"))
        object.__setattr__(self, "status", _coerce_enum(GateStatus, self.status, "status"))
        if not isinstance(self.message, str):
            raise RoadRunnerContractError("message must be a string")
        _reject_placeholder(self.message.strip(), "message")
        object.__setattr__(self, "evidence_paths", tuple(self.evidence_paths))
        object.__setattr__(self, "metrics", _validate_mapping(self.metrics, "metrics"))


@dataclass(frozen=True)
class SemanticDiffSummary(SerializableContract):
    """Summary of semantic differences between parent and candidate data."""

    parent_sha256: str
    candidate_sha256: str
    changed_elements: int
    added_elements: int = 0
    removed_elements: int = 0
    critical_changes: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "parent_sha256", validate_sha256(self.parent_sha256, "parent_sha256"))
        object.__setattr__(self, "candidate_sha256", validate_sha256(self.candidate_sha256, "candidate_sha256"))
        for name in ("changed_elements", "added_elements", "removed_elements"):
            if getattr(self, name) < 0:
                raise RoadRunnerContractError(f"{name} must be non-negative")
        object.__setattr__(
            self,
            "critical_changes",
            tuple(validate_identifier(item, "critical_changes") for item in self.critical_changes),
        )
        object.__setattr__(self, "metrics", _validate_mapping(self.metrics, "metrics"))


@dataclass(frozen=True)
class MeshXodrAlignmentSummary(SerializableContract):
    """Summary of alignment between visual mesh output and source XODR."""

    mesh_sha256: str
    xodr_sha256: str
    max_horizontal_error_m: float
    max_vertical_error_m: float
    aligned: bool
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mesh_sha256", validate_sha256(self.mesh_sha256, "mesh_sha256"))
        object.__setattr__(self, "xodr_sha256", validate_sha256(self.xodr_sha256, "xodr_sha256"))
        if self.max_horizontal_error_m < 0 or self.max_vertical_error_m < 0:
            raise RoadRunnerContractError("alignment errors must be non-negative")
        object.__setattr__(self, "notes", tuple(str(note) for note in self.notes))


@dataclass(frozen=True)
class RunManifest(SerializableContract):
    """Manifest for a RoadRunner contract-only run record."""

    run_id: str
    job: RoadRunnerJobRequest
    artifacts: tuple[ArtifactRecord, ...]
    gates: tuple[StageGate, ...]
    semantic_diff: SemanticDiffSummary | None = None
    alignment_summary: MeshXodrAlignmentSummary | None = None
    generated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", validate_identifier(self.run_id, "run_id"))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "gates", tuple(self.gates))
        if not self.artifacts:
            raise RoadRunnerContractError("run manifest must include at least one artifact")
        artifact_ids = {artifact.artifact_id for artifact in self.artifacts}
        if len(artifact_ids) != len(self.artifacts):
            raise RoadRunnerContractError("artifact_id values must be unique")
        gate_ids = {gate.gate_id for gate in self.gates}
        if len(gate_ids) != len(self.gates):
            raise RoadRunnerContractError("gate_id values must be unique")


def ensure_artifact_parents(artifacts: Sequence[ArtifactRecord], parent_sha256: str) -> None:
    """Validate that every candidate artifact references the expected parent SHA."""

    expected = validate_sha256(parent_sha256, "parent_sha256")
    for artifact in artifacts:
        if artifact.parent_sha256 != expected:
            raise RoadRunnerContractError(
                f"artifact {artifact.artifact_id!r} parent_sha256 does not match source sha256"
            )
