from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Sequence


RunId = str


def create_run_id() -> RunId:
    return datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S_%f")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_semantic_sha256(path: Path) -> str:
    data = path.read_bytes()
    return sha256_of_bytes(data)


@dataclass(frozen=True)
class ArtifactRef:
    path: Path
    sha256: str
    semantic_sha256: str
    parent_sha256: str | None
    configuration_sha256: str
    git_sha: str
    artifact_type: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "path": self.path.as_posix(),
            "sha256": self.sha256,
            "semantic_sha256": self.semantic_sha256,
            "parent_sha256": self.parent_sha256,
            "configuration_sha256": self.configuration_sha256,
            "git_sha": self.git_sha,
            "artifact_type": self.artifact_type,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ArtifactRef:
        data = dict(d)
        data["path"] = Path(data["path"])
        return cls(**data)


@dataclass(frozen=True)
class MutationDeclaration:
    operation: str
    allowed_xml_domains: tuple[str, ...]
    forbidden_xml_domains: tuple[str, ...]
    affected_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> MutationDeclaration:
        return cls(**d)


@dataclass(frozen=True)
class GateResult:
    gate_name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"gate_name": self.gate_name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class CandidateResult:
    status: Literal["PASS", "FAIL", "BLOCKED"]
    parent: ArtifactRef
    candidate: ArtifactRef | None
    mutation_declaration: MutationDeclaration
    gate_results: tuple[GateResult, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "parent": self.parent.to_dict(),
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "mutation_declaration": self.mutation_declaration.to_dict(),
            "gate_results": [g.to_dict() for g in self.gate_results],
            "blockers": list(self.blockers),
        }


@dataclass
class Manifest:
    run_id: RunId
    accepted: ArtifactRef | None = None
    candidates: dict[str, CandidateResult] = field(default_factory=dict)
    rejected: dict[str, CandidateResult] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "accepted": self.accepted.to_dict() if self.accepted else None,
            "candidates": {k: v.to_dict() for k, v in self.candidates.items()},
            "rejected": {k: v.to_dict() for k, v in self.rejected.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Manifest:
        m = cls(run_id=d["run_id"])
        m.accepted = ArtifactRef.from_dict(d["accepted"]) if d.get("accepted") else None
        m.candidates = {k: CandidateResult(**{**v, "parent": ArtifactRef.from_dict(v["parent"]), "candidate": ArtifactRef.from_dict(v["candidate"]) if v.get("candidate") else None, "gate_results": tuple(GateResult(**g) for g in v["gate_results"]), "blockers": tuple(v["blockers"])}) for k, v in d.get("candidates", {}).items()}
        m.rejected = {k: CandidateResult(**{**v, "parent": ArtifactRef.from_dict(v["parent"]), "candidate": ArtifactRef.from_dict(v["candidate"]) if v.get("candidate") else None, "gate_results": tuple(GateResult(**g) for g in v["gate_results"]), "blockers": tuple(v["blockers"])}) for k, v in d.get("rejected", {}).items()}
        m.created_at = d.get("created_at", m.created_at)
        m.updated_at = d.get("updated_at", m.updated_at)
        return m

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
