"""Read-only, fail-closed GUI projection of an authenticated backend run snapshot.

NOT a release verifier, terminal writer, CARLA controller or authentication system.
The backend must establish provenance and authenticate the transport. This
consumer refuses to promote incomplete, replayed or contradictory snapshots.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "carla.gui.run-snapshot/v1"
RUN_STATES = frozenset({
    "QUEUED", "RUNNING", "BLOCKED_EXTERNAL", "FAILED", "CANCEL_REQUESTED",
    "CANCELLED", "SUCCEEDED_SOURCE_ONLY", "PUBLISHED_RUNTIME_CERTIFIED",
})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class UnverifiedSnapshot(ValueError):
    """Malformed, unbound or contradictory status. Keep previous UI state."""


class StaleSnapshot(UnverifiedSnapshot):
    """Out-of-order update or backend restart needs a verified resync."""


def _nonempty(raw: Any, field: str, *, max_length: int = 256) -> str:
    if not isinstance(raw, str) or not raw or len(raw) > max_length:
        raise UnverifiedSnapshot(f"{field} missing or invalid")
    if any(ord(ch) < 32 for ch in raw):
        raise UnverifiedSnapshot(f"{field} contains control characters")
    return raw


def _sha(raw: Any, field: str, *, git: bool = False) -> str:
    value = _nonempty(raw, field)
    if not (_GIT_SHA if git else _SHA256).fullmatch(value):
        raise UnverifiedSnapshot(f"{field} must be a complete lowercase digest")
    return value


@dataclass(frozen=True)
class RunIdentity:
    run_id: str
    source_sha: str
    config_sha256: str
    xodr_sha256: str
    purpose: str
    lease_generation: int

    @classmethod
    def from_mapping(cls, source: Mapping[str, Any]) -> "RunIdentity":
        if not isinstance(source, Mapping):
            raise UnverifiedSnapshot("run identity must be an object")
        run_id = _nonempty(source.get("run_id"), "run_id")
        if "/" in run_id or "\\" in run_id or run_id in (".", ".."):
            raise UnverifiedSnapshot("run_id must be an opaque identifier, not a path")
        purpose = _nonempty(source.get("purpose"), "purpose")
        if purpose not in {"release", "diagnostic"}:
            raise UnverifiedSnapshot("unknown run purpose")
        generation = source.get("lease_generation")
        if type(generation) is not int or generation < 1:
            raise UnverifiedSnapshot("lease_generation must be positive integer")
        return cls(run_id, _sha(source.get("source_sha"), "source_sha", git=True),
                   _sha(source.get("config_sha256"), "config_sha256"),
                   _sha(source.get("xodr_sha256"), "xodr_sha256"),
                   purpose, generation)


@dataclass(frozen=True)
class GateEvidence:
    gate_id: str
    required: bool
    status: str
    artifact_sha256: str | None
    verified_at: str


def _timestamp(raw: Any, name: str, *, required: bool = False) -> str:
    if raw in ("", None) and not required:
        return ""
    value = _nonempty(raw, name, max_length=64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UnverifiedSnapshot(f"{name} is not ISO 8601") from exc
    if parsed.tzinfo is None:
        raise UnverifiedSnapshot(f"{name} must carry UTC offset")
    return value


def _gates(raw: Any) -> tuple[GateEvidence, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > 128:
        raise UnverifiedSnapshot("gate list invalid or unbounded")
    gates = []
    ids = set()
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise UnverifiedSnapshot("gate evidence must be an object")
        gid = _nonempty(entry.get("gate_id"), "gate_id")
        if gid in ids:
            raise UnverifiedSnapshot("duplicate gate_id")
        ids.add(gid)
        required = entry.get("required")
        if type(required) is not bool:
            raise UnverifiedSnapshot("gate required must be an exact boolean")
        status = _nonempty(entry.get("status"), "gate status")
        if status not in {"PASS", "FAIL", "BLOCKED_EXTERNAL", "NOT_EVALUATED"}:
            raise UnverifiedSnapshot("unrecognized gate status")
        artifact = entry.get("artifact_sha256")
        sha = _sha(artifact, "gate artifact_sha256") if artifact else None
        when = _timestamp(entry.get("verified_at", ""), "gate verified_at")
        if status == "PASS" and (sha is None or not when):
            raise UnverifiedSnapshot("PASS gate is not bound to hash/timestamp")
        gates.append(GateEvidence(gid, required, status, sha, when))
    return tuple(gates)


@dataclass(frozen=True)
class BackendRunSnapshot:
    identity: RunIdentity
    backend_epoch: str
    sequence: int
    state: str
    stage: str
    terminal_verdict: str
    last_verified_at: str
    artifact_sha256: str | None
    report_count: int
    provenance_verified: bool
    runtime_verified: bool
    source_verified: bool
    ci_source_sha: str | None
    ci_state: str
    carla_runtime_state: str
    gnn_feature_state: str
    gates: tuple[GateEvidence, ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], *,
                     trusted_transport: bool = False) -> "BackendRunSnapshot":
        """Parse only assertions from an authenticated backend channel.

        ``trusted_transport`` must be set by the authenticated transport layer
        after its own session and permission checks; UI state does not grant it.
        Even then, this is a projection of backend verification, not proof the
        backend implemented verification correctly.
        """
        if not isinstance(payload, Mapping) or payload.get("schema") != SCHEMA:
            raise UnverifiedSnapshot("run snapshot schema mismatch")
        if not trusted_transport:
            raise UnverifiedSnapshot("backend transport has not been authenticated")
        identity = RunIdentity.from_mapping(payload.get("identity"))
        state = _nonempty(payload.get("state"), "state")
        if state not in RUN_STATES:
            raise UnverifiedSnapshot("unknown run state")
        sequence = payload.get("sequence")
        if type(sequence) is not int or sequence < 0:
            raise UnverifiedSnapshot("sequence must be nonnegative integer")
        epoch = _nonempty(payload.get("backend_epoch"), "backend_epoch")
        stage = _nonempty(payload.get("stage"), "stage")
        raw_verdict = payload.get("terminal_verdict")
        if raw_verdict not in ("PASS", "FAIL", "BLOCKED_EXTERNAL", "NOT_EVALUATED", None):
            raise UnverifiedSnapshot("unknown terminal verdict")
        verdict = raw_verdict or "NOT_EVALUATED"
        provenance = payload.get("provenance_verified") is True
        runtime = payload.get("runtime_verified") is True
        source = payload.get("source_verified") is True
        recorded_ci_sha = payload.get("ci_source_sha")
        ci_sha = _sha(recorded_ci_sha, "ci_source_sha", git=True) if recorded_ci_sha else None
        artifact_sha = payload.get("published_artifact_sha256")
        artifact_sha = _sha(artifact_sha, "published_artifact_sha256") if artifact_sha else None
        count = payload.get("report_count", 0)
        if type(count) is not int or not 0 <= count <= 100_000:
            raise UnverifiedSnapshot("report_count invalid")
        when = _timestamp(payload.get("last_verified_at", ""), "last_verified_at")
        ci_state = payload.get("ci_state", "UNKNOWN")
        carla_state = payload.get("carla_runtime_state", "UNKNOWN")
        gnn_state = payload.get("gnn_feature_state", "UNKNOWN")
        if ci_state not in {"PASS", "FAIL", "NOT_RUN", "BLOCKED_EXTERNAL", "UNKNOWN"}:
            raise UnverifiedSnapshot("unknown CI state")
        if carla_state not in {"PASS", "FAIL", "NOT_RUN", "BLOCKED_EXTERNAL", "UNKNOWN"}:
            raise UnverifiedSnapshot("unknown CARLA runtime state")
        if gnn_state not in {"SUPPORTED", "UNSUPPORTED", "UNKNOWN"}:
            raise UnverifiedSnapshot("unknown GNN feature state")
        gates = _gates(payload.get("gates"))
        if state == "SUCCEEDED_SOURCE_ONLY":
            if not (provenance and source and verdict == "PASS" and
                    ci_sha == identity.source_sha and ci_state == "PASS" and when):
                raise UnverifiedSnapshot("source-only success lacks backend verification")
            if runtime:
                raise UnverifiedSnapshot("runtime-certified result cannot be source-only")
        if state == "PUBLISHED_RUNTIME_CERTIFIED":
            if (identity.purpose != "release" or not all((provenance, source, runtime))
                    or verdict != "PASS" or ci_sha != identity.source_sha
                    or artifact_sha != identity.xodr_sha256 or not when
                    or ci_state != "PASS" or carla_state != "PASS"
                    or not any(g.required for g in gates)
                    or any(g.status != "PASS" for g in gates if g.required)):
                raise UnverifiedSnapshot("runtime publication evidence missing or contradictory")
        if state in {"CANCELLED", "FAILED", "BLOCKED_EXTERNAL"} and verdict == "PASS":
            raise UnverifiedSnapshot("terminal verdict contradicts failed/blocked state")
        if state in {"QUEUED", "RUNNING", "CANCEL_REQUESTED"} and runtime:
            raise UnverifiedSnapshot("in-progress run cannot be runtime-certified")
        return cls(identity, epoch, sequence, state, stage, verdict, when,
                   artifact_sha, count, provenance, runtime, source, ci_sha,
                   ci_state, carla_state, gnn_state, gates)

    @property
    def production_ready(self) -> bool:
        return self.state == "PUBLISHED_RUNTIME_CERTIFIED"


class RunProjection:
    """State updates for one run; never follows another identity silently."""

    def __init__(self, initial: BackendRunSnapshot) -> None:
        self._snapshot = initial

    @property
    def current(self) -> BackendRunSnapshot:
        return self._snapshot

    def accept(self, update: BackendRunSnapshot) -> BackendRunSnapshot:
        prior = self._snapshot
        if update.identity != prior.identity:
            raise StaleSnapshot("run identity changed; choose the new run explicitly")
        if update.backend_epoch != prior.backend_epoch:
            raise StaleSnapshot("backend restarted; reauthenticate and resync")
        if update.sequence <= prior.sequence:
            raise StaleSnapshot("replayed or out-of-order event")
        if prior.state in {"FAILED", "BLOCKED_EXTERNAL", "CANCELLED",
                           "SUCCEEDED_SOURCE_ONLY", "PUBLISHED_RUNTIME_CERTIFIED"}:
            raise StaleSnapshot("immutable terminal run cannot be changed")
        if prior.state == "CANCEL_REQUESTED" and update.state in {"QUEUED", "RUNNING"}:
            raise StaleSnapshot("cancellation cannot be silently rolled back")
        self._snapshot = update
        return update


def verified_report_bytes(root: Path, relative_path: str, expected_sha256: str,
                          *, max_bytes: int = 32 * 1024 * 1024) -> bytes:
    """Read a bounded, hash-matched artifact from a local read-only sandbox.

    The REST endpoint must additionally authorize the run and session before
    invoking this helper. No filesystem writes or command execution occur.
    """
    _sha(expected_sha256, "expected_sha256")
    if type(max_bytes) is not int or not 0 < max_bytes <= 256 * 1024 * 1024:
        raise ValueError("max_bytes is not an approved bounded size")
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise ValueError("invalid report path")
    rel = Path(relative_path)
    if rel.is_absolute() or any(part in ("..", ".", "") for part in rel.parts):
        raise ValueError("report path traversal refused")
    base = Path(root).resolve(strict=True)
    candidate = base / rel
    # Disallow symbolic links at every hop, even those pointing back in sandbox.
    current = base
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("report symlink refused")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(base) or not resolved.is_file():
        raise ValueError("report is not a regular file inside the sandbox")
    if resolved.stat().st_size > max_bytes:
        raise ValueError("report exceeds size limit")
    with resolved.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("report digest or size mismatch")
    return data
