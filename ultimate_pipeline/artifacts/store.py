from __future__ import annotations
import json
import shutil
from pathlib import Path

from ultimate_pipeline.artifacts.errors import (
    ConcurrentWriteError,
    ManifestCorruptionError,
)
from ultimate_pipeline.artifacts.model import (
    ArtifactRef,
    CandidateResult,
    Manifest,
    RunId,
    create_run_id,
    sha256_of,
    compute_semantic_sha256,
)


LOCK_SUFFIX = ".lock"
MANIFEST_NAME = "manifest.json"
PARENT_DIR = "parent"
CANDIDATES_DIR = "candidates"
REJECTED_DIR = "rejected"
ACCEPTED_DIR = "accepted"
REPORTS_DIR = "reports"
MANIFESTS_DIR = "manifests"


class ArtifactStore:
    def __init__(self, root: Path, git_sha: str, configuration_sha256: str):
        self.root = root.resolve()
        self.git_sha = git_sha
        self.configuration_sha256 = configuration_sha256
        self._lock_path = root / ".store.lock"
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def current_manifest(self) -> Manifest | None:
        path = self.root / MANIFEST_NAME
        if not path.exists():
            return None
        try:
            return Manifest.load(path)
        except (json.JSONDecodeError, KeyError) as e:
            raise ManifestCorruptionError(str(path), str(e))

    def _acquire_lock(self) -> bool:
        try:
            self._lock_path.touch(exist_ok=False)
            return True
        except FileExistsError:
            return False

    def _release_lock(self) -> None:
        self._lock_path.unlink(missing_ok=True)

    def create_run(self) -> RunId:
        run_id = create_run_id()
        (self.root / PARENT_DIR).mkdir(parents=True, exist_ok=True)
        (self.root / CANDIDATES_DIR).mkdir(parents=True, exist_ok=True)
        (self.root / REJECTED_DIR).mkdir(parents=True, exist_ok=True)
        (self.root / ACCEPTED_DIR).mkdir(parents=True, exist_ok=True)
        (self.root / REPORTS_DIR).mkdir(parents=True, exist_ok=True)
        (self.root / MANIFESTS_DIR).mkdir(parents=True, exist_ok=True)
        manifest = Manifest(run_id=run_id)
        manifest.save(self.root / MANIFEST_NAME)
        return run_id

    def set_parent(self, path: Path, artifact_type: str) -> ArtifactRef:
        if not self._acquire_lock():
            raise ConcurrentWriteError(str(self.root))
        try:
            if self.current_manifest is None:
                self.create_run()
            manifest = self.current_manifest
            if manifest is None:
                raise ManifestCorruptionError(str(self.root / MANIFEST_NAME), "manifest was not created")

            parent_dir = self.root / PARENT_DIR
            parent_dir.mkdir(parents=True, exist_ok=True)
            dest = parent_dir / path.name
            if path.resolve() != dest.resolve():
                shutil.copy2(path, dest)
            ar = ArtifactRef(
                path=dest,
                sha256=sha256_of(dest),
                semantic_sha256=compute_semantic_sha256(dest),
                parent_sha256=None,
                configuration_sha256=self.configuration_sha256,
                git_sha=self.git_sha,
                artifact_type=artifact_type,
            )
            manifest.accepted = ar
            manifest.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            manifest.save(self.root / MANIFEST_NAME)
            return ar
        finally:
            self._release_lock()

    def get_parent(self) -> ArtifactRef | None:
        manifest = self.current_manifest
        return manifest.accepted if manifest else None

    def store_candidate(self, candidate_id: str, path: Path, artifact_type: str, parent: ArtifactRef) -> ArtifactRef | None:
        cand_dir = self.root / CANDIDATES_DIR / candidate_id
        if cand_dir.exists():
            return None
        cand_dir.mkdir(parents=True)
        dest = cand_dir / path.name
        try:
            shutil.copy2(path, dest)
        except Exception:
            shutil.rmtree(cand_dir, ignore_errors=True)
            return None
        return ArtifactRef(
            path=dest,
            sha256=sha256_of(dest),
            semantic_sha256=compute_semantic_sha256(dest),
            parent_sha256=parent.sha256,
            configuration_sha256=self.configuration_sha256,
            git_sha=self.git_sha,
            artifact_type=artifact_type,
        )

    def promote_candidate(self, candidate_id: str, result: CandidateResult) -> ArtifactRef | None:
        if not self._acquire_lock():
            raise ConcurrentWriteError(str(self.root / ACCEPTED_DIR))
        temp_dest: Path | None = None
        try:
            manifest = self.current_manifest
            if manifest is None or manifest.accepted is None or result.candidate is None:
                return None
            if manifest.accepted.sha256 != result.parent.sha256:
                return None
            if not manifest.accepted.path.exists() or sha256_of(manifest.accepted.path) != result.parent.sha256:
                return None
            accepted_dir = self.root / ACCEPTED_DIR
            accepted_dir.mkdir(parents=True, exist_ok=True)
            src = self.root / CANDIDATES_DIR / candidate_id
            if not src.exists():
                return None
            dest = accepted_dir / candidate_id
            if dest.exists():
                return None
            temp_dest = accepted_dir / f".{candidate_id}.tmp"
            if temp_dest.exists():
                shutil.rmtree(str(temp_dest))
            shutil.copytree(str(src), str(temp_dest))
            promoted_path = temp_dest / result.candidate.path.name
            if not promoted_path.exists():
                return None
            promoted = ArtifactRef(
                path=dest / result.candidate.path.name,
                sha256=sha256_of(promoted_path),
                semantic_sha256=compute_semantic_sha256(promoted_path),
                parent_sha256=result.parent.sha256,
                configuration_sha256=self.configuration_sha256,
                git_sha=self.git_sha,
                artifact_type=result.candidate.artifact_type,
            )
            temp_dest.replace(dest)
            temp_dest = None
            promoted_result = CandidateResult(
                status=result.status,
                parent=result.parent,
                candidate=promoted,
                mutation_declaration=result.mutation_declaration,
                gate_results=result.gate_results,
                blockers=result.blockers,
            )
            manifest.accepted = promoted
            manifest.candidates[candidate_id] = promoted_result
            manifest.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            manifest.save(self.root / MANIFEST_NAME)
            (self.root / MANIFESTS_DIR / f"{manifest.run_id}.json").write_text(
                __import__("json").dumps(manifest.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            return promoted
        finally:
            if temp_dest is not None and temp_dest.exists():
                shutil.rmtree(str(temp_dest), ignore_errors=True)
            self._release_lock()

    def reject_candidate(self, candidate_id: str, result: CandidateResult) -> None:
        rejected_dir = self.root / REJECTED_DIR / candidate_id
        rejected_dir.mkdir(parents=True, exist_ok=True)
        src = self.root / CANDIDATES_DIR / candidate_id
        if src.exists():
            shutil.copytree(str(src), str(rejected_dir), dirs_exist_ok=True)
        manifest = self.current_manifest
        if manifest:
            manifest.rejected[candidate_id] = result
            manifest.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            manifest.save(self.root / MANIFEST_NAME)

    def rollback(self) -> ArtifactRef | None:
        if not self._acquire_lock():
            raise ConcurrentWriteError(str(self.root))
        try:
            manifest = self.current_manifest
            if manifest is None or manifest.accepted is None:
                return None
            previous_accepted = manifest.accepted
            manifest.accepted = None
            manifest.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            manifest.save(self.root / MANIFEST_NAME)
            return previous_accepted
        finally:
            self._release_lock()

    def verify_integrity(self) -> list[str]:
        issues: list[str] = []
        manifest = self.current_manifest
        if manifest is None:
            return ["No manifest found"]
        if manifest.accepted:
            p = manifest.accepted.path
            if not p.exists():
                issues.append(f"Accepted artifact missing: {p}")
            elif sha256_of(p) != manifest.accepted.sha256:
                issues.append(f"Accepted artifact hash mismatch: {p}")
        return issues
