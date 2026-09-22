from __future__ import annotations
import json
import os
import shutil
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

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
JOURNAL_DIR = "journals"
LOCK_TIMEOUT_SECONDS = 300  # 5 minutes default stale lock timeout

def _lock_metadata() -> dict:
    """Create lock metadata with process identity."""
    return {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "created_at": time.time(),
        "owner": f"{os.getpid()}@{socket.gethostname()}",
    }

def _is_stale_lock(lock_path: Path, timeout: int = LOCK_TIMEOUT_SECONDS) -> bool:
    """Check if lock file is stale based on metadata."""
    try:
        if not lock_path.exists():
            return False
        metadata = json.loads(lock_path.read_text(encoding="utf-8"))
        created_at = metadata.get("created_at", 0)
        if time.time() - created_at > timeout:
            return True
    except Exception:
        # If we can't read metadata, treat as potentially stale
        pass
    return False

def _recover_stale_lock(lock_path: Path) -> bool:
    """Attempt to recover a stale lock. Returns True if lock was recovered."""
    if _is_stale_lock(lock_path):
        try:
            lock_path.unlink()
            return True
        except Exception:
            return False
    return False


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

    def _acquire_lock(self, timeout: int = 30) -> bool:
        """Acquire lock with stale lock recovery. Returns True if acquired."""
        start = time.time()
        while time.time() - start < timeout:
            # Try to create lock atomically with metadata
            try:
                metadata = _lock_metadata()
                self._lock_path.write_text(json.dumps(metadata), encoding="utf-8")
                return True
            except FileExistsError:
                # Lock exists, check if stale
                if _recover_stale_lock(self._lock_path):
                    continue  # Try again
                # Check if it's our own lock (reentrant)
                try:
                    metadata = json.loads(self._lock_path.read_text(encoding="utf-8"))
                    if metadata.get("owner") == f"{os.getpid()}@{socket.gethostname()}":
                        return True  # We already hold the lock
                except Exception:
                    pass
                time.sleep(0.1)
        return False

    def _release_lock(self) -> None:
        """Release lock only if we own it."""
        try:
            if self._lock_path.exists():
                metadata = json.loads(self._lock_path.read_text(encoding="utf-8"))
                if metadata.get("owner") == f"{os.getpid()}@{socket.gethostname()}":
                    self._lock_path.unlink()
        except Exception:
            pass

    def _with_lock(self):
        """Context manager for lock acquisition."""
        class LockContext:
            def __init__(self, store):
                self.store = store
                self.acquired = False

            def __enter__(self):
                self.acquired = self.store._acquire_lock()
                if not self.acquired:
                    raise ConcurrentWriteError(str(self.store.root))
                return self.store

            def __exit__(self, exc_type, exc_val, exc_tb):
                if self.acquired:
                    self.store._release_lock()
                return False
        return LockContext(self)

    def _validate_path_containment(self, path: Path, base: Path) -> bool:
        """Ensure path is contained within base directory."""
        try:
            path.resolve().relative_to(base.resolve())
            return True
        except ValueError:
            return False

    def create_run(self) -> RunId:
        with self._with_lock() as store:
            run_id = create_run_id()
            (store.root / PARENT_DIR).mkdir(parents=True, exist_ok=True)
            (store.root / CANDIDATES_DIR).mkdir(parents=True, exist_ok=True)
            (store.root / REJECTED_DIR).mkdir(parents=True, exist_ok=True)
            (store.root / ACCEPTED_DIR).mkdir(parents=True, exist_ok=True)
            (store.root / REPORTS_DIR).mkdir(parents=True, exist_ok=True)
            (store.root / MANIFESTS_DIR).mkdir(parents=True, exist_ok=True)
            (store.root / JOURNAL_DIR).mkdir(parents=True, exist_ok=True)
            manifest = Manifest(run_id=run_id)
            manifest.save(store.root / MANIFEST_NAME)
            return run_id

    def set_parent(self, path: Path, artifact_type: str) -> ArtifactRef:
        with self._with_lock() as store:
            if store.current_manifest is None:
                store.create_run()
            manifest = store.current_manifest
            if manifest is None:
                raise ManifestCorruptionError(str(store.root / MANIFEST_NAME), "manifest was not created")

            if not store._validate_path_containment(path, store.root):
                raise ValueError(f"Source path {path} is not contained within store root")

            parent_dir = store.root / PARENT_DIR
            parent_dir.mkdir(parents=True, exist_ok=True)
            dest = parent_dir / path.name
            if path.resolve() != dest.resolve():
                shutil.copy2(path, dest)
            ar = ArtifactRef(
                path=dest,
                sha256=sha256_of(dest),
                semantic_sha256=compute_semantic_sha256(dest),
                parent_sha256=None,
                configuration_sha256=store.configuration_sha256,
                git_sha=store.git_sha,
                artifact_type=artifact_type,
            )
            manifest.accepted = ar
            manifest.accepted_history.append(ar)
            manifest.updated_at = datetime.now(timezone.utc).isoformat()
            manifest.save(store.root / MANIFEST_NAME)
            return ar

    def get_parent(self) -> ArtifactRef | None:
        manifest = self.current_manifest
        return manifest.accepted if manifest else None

    def store_candidate(self, candidate_id: str, path: Path, artifact_type: str, parent: ArtifactRef) -> ArtifactRef | None:
        with self._with_lock() as store:
            if not store._validate_path_containment(path, store.root):
                raise ValueError(f"Source path {path} is not contained within store root")
            
            if not candidate_id or candidate_id in {".", ".."} or "/" in candidate_id or "\\" in candidate_id:
                raise ValueError("candidate_id must be a single path-safe segment")

            cand_dir = store.root / CANDIDATES_DIR / candidate_id
            # Atomic directory creation - fail if already exists
            try:
                cand_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                return None
            
            dest = cand_dir / path.name
            source_sha_before = sha256_of(path)
            
            try:
                shutil.copy2(path, dest)
            except Exception:
                shutil.rmtree(cand_dir, ignore_errors=True)
                return None
            
            source_sha_after = sha256_of(path)
            stored_sha = sha256_of(dest)
            
            # Verify copy integrity
            if source_sha_before != source_sha_after or source_sha_before != stored_sha:
                shutil.rmtree(cand_dir, ignore_errors=True)
                raise ValueError(f"Source file mutated during copy for candidate {candidate_id}")

            return ArtifactRef(
                path=dest,
                sha256=stored_sha,
                semantic_sha256=compute_semantic_sha256(dest),
                parent_sha256=parent.sha256,
                configuration_sha256=store.configuration_sha256,
                git_sha=store.git_sha,
                artifact_type=artifact_type,
            )

    def _write_journal(self, run_id: str, phase: str, candidate_id: str, old_accepted: ArtifactRef | None, new_candidate: ArtifactRef | None) -> None:
        """Write a transaction journal entry for recovery."""
        journal = {
            "transaction_id": f"{run_id}_{candidate_id}_{int(time.time()*1000)}",
            "run_id": run_id,
            "operation": "promote",
            "candidate_id": candidate_id,
            "old_accepted": old_accepted.to_dict() if old_accepted else None,
            "new_candidate": new_candidate.to_dict() if new_candidate else None,
            "phase": phase,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        journal_path = self.root / JOURNAL_DIR / f"{run_id}_{candidate_id}_{phase}.json"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_text(json.dumps(journal, indent=2, sort_keys=True), encoding="utf-8")

    def promote_candidate(self, candidate_id: str, result: CandidateResult) -> ArtifactRef | None:
        with self._with_lock() as store:
            manifest = store.current_manifest
            if manifest is None or manifest.accepted is None or result.candidate is None:
                return None
            
            # Verify parent integrity
            if manifest.accepted.sha256 != result.parent.sha256:
                return None
            if not manifest.accepted.path.exists() or sha256_of(manifest.accepted.path) != result.parent.sha256:
                return None
            
            accepted_dir = store.root / ACCEPTED_DIR
            accepted_dir.mkdir(parents=True, exist_ok=True)
            src = store.root / CANDIDATES_DIR / candidate_id
            if not src.exists():
                return None
            dest = accepted_dir / candidate_id
            if dest.exists():
                return None
            
            # Write journal - PREPARED phase
            store._write_journal(manifest.run_id, "PREPARED", candidate_id, manifest.accepted, result.candidate)
            
            temp_dest = accepted_dir / f".{candidate_id}.tmp"
            if temp_dest.exists():
                shutil.rmtree(str(temp_dest))
            
            try:
                shutil.copytree(str(src), str(temp_dest))
            except Exception:
                shutil.rmtree(str(temp_dest), ignore_errors=True)
                return None
            
            promoted_path = temp_dest / result.candidate.path.name
            if not promoted_path.exists():
                shutil.rmtree(str(temp_dest), ignore_errors=True)
                return None
            
            # Verify promoted artifact integrity
            promoted_sha = sha256_of(promoted_path)
            promoted_semantic = compute_semantic_sha256(promoted_path)
            
            promoted = ArtifactRef(
                path=dest / result.candidate.path.name,
                sha256=sha256_of(promoted_path),
                semantic_sha256=promoted_semantic,
                parent_sha256=result.parent.sha256,
                configuration_sha256=store.configuration_sha256,
                git_sha=store.git_sha,
                artifact_type=result.candidate.artifact_type,
            )
            
            # Write journal - ARTIFACT_PROMOTED phase
            store._write_journal(manifest.run_id, "ARTIFACT_PROMOTED", candidate_id, None, promoted)
            
            # Atomic replace with fsync
            temp_dest.replace(dest)
            # fsync for durability
            try:
                with open(dest, 'rb') as f:
                    os.fsync(f.fileno())
                # Try to fsync parent directory (best effort, may fail on Windows)
                try:
                    with open(accepted_dir, 'rb') as f:
                        os.fsync(f.fileno())
                except (OSError, AttributeError):
                    pass  # Not supported on all platforms
            except OSError:
                pass  # fsync not available
            
            promoted_result = CandidateResult(
                status=result.status,
                parent=result.parent,
                candidate=promoted,
                mutation_declaration=result.mutation_declaration,
                gate_results=result.gate_results,
                blockers=result.blockers,
            )
            
            old_accepted = manifest.accepted
            manifest.accepted = promoted
            manifest.candidates[candidate_id] = promoted_result
            manifest.accepted_history.append(promoted)
            manifest.updated_at = datetime.now(timezone.utc).isoformat()
            
            # Write journal - MANIFEST_COMMITTED phase
            store._write_journal(manifest.run_id, "MANIFEST_COMMITTED", candidate_id, None, None)
            
            manifest.save(store.root / MANIFEST_NAME)
            
            # Write journal - COMPLETE phase
            store._write_journal(manifest.run_id, "COMPLETE", candidate_id, None, None)
            
            # Clean up intermediate journal files (PREPARED, ARTIFACT_PROMOTED, MANIFEST_COMMITTED)
            # Only keep the COMPLETE journal as evidence of successful promotion
            journal_dir = store.root / JOURNAL_DIR
            for phase in ("PREPARED", "ARTIFACT_PROMOTED", "MANIFEST_COMMITTED"):
                journal_path = journal_dir / f"{manifest.run_id}_{candidate_id}_{phase}.json"
                if journal_path.exists():
                    try:
                        journal_path.unlink()
                    except Exception:
                        pass  # Best effort cleanup
            
            # Save manifest snapshot
            (store.root / MANIFESTS_DIR / f"{manifest.run_id}.json").write_text(
                json.dumps(manifest.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            return promoted

    def reject_candidate(self, candidate_id: str, result: CandidateResult) -> None:
        with self._with_lock() as store:
            if not store._validate_path_containment(Path(candidate_id), store.root):
                raise ValueError(f"Invalid candidate_id: {candidate_id}")
            
            rejected_dir = store.root / REJECTED_DIR / candidate_id
            rejected_dir.mkdir(parents=True, exist_ok=True)
            src = store.root / CANDIDATES_DIR / candidate_id
            if src.exists():
                shutil.copytree(str(src), str(rejected_dir), dirs_exist_ok=True)
            manifest = store.current_manifest
            if manifest:
                manifest.rejected[candidate_id] = result
                manifest.updated_at = datetime.now(timezone.utc).isoformat()
                manifest.save(store.root / MANIFEST_NAME)

    def rollback(self) -> ArtifactRef | None:
        with self._with_lock() as store:
            manifest = store.current_manifest
            if manifest is None or manifest.accepted is None or not manifest.accepted_history:
                return None
            
            # Remove current accepted from history and restore previous
            current = manifest.accepted_history.pop()
            if manifest.accepted_history:
                previous = manifest.accepted_history[-1]
                manifest.accepted = previous
            else:
                manifest.accepted = None
            
            manifest.updated_at = datetime.now(timezone.utc).isoformat()
            manifest.save(store.root / MANIFEST_NAME)
            return current

    def verify_integrity(self, mode: Literal["QUICK", "FULL"] = "QUICK") -> list[str]:
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
        
        if mode == "FULL":
            # Verify accepted history chain
            for i, ref in enumerate(manifest.accepted_history):
                if not ref.path.exists():
                    issues.append(f"History artifact missing: {ref.path}")
                elif sha256_of(ref.path) != ref.sha256:
                    issues.append(f"History artifact hash mismatch: {ref.path}")
                if i > 0 and ref.parent_sha256 != manifest.accepted_history[i-1].sha256:
                    issues.append(f"History chain broken at index {i}: parent_sha256 mismatch")
            
            # Verify candidates
            for cid, result in manifest.candidates.items():
                if result.candidate and result.candidate.path.exists():
                    if sha256_of(result.candidate.path) != result.candidate.sha256:
                        issues.append(f"Candidate {cid} hash mismatch")
            
            # Verify rejected
            for cid, result in manifest.rejected.items():
                if result.candidate and result.candidate.path.exists():
                    if sha256_of(result.candidate.path) != result.candidate.sha256:
                        issues.append(f"Rejected {cid} hash mismatch")
            
            # Check for orphan accepted directories
            accepted_dir = self.root / ACCEPTED_DIR
            if accepted_dir.exists():
                for entry in accepted_dir.iterdir():
                    if entry.is_dir() and entry.name not in manifest.candidates:
                        issues.append(f"Orphan accepted directory: {entry.name}")
            
            # Check for orphan journals
            journal_dir = self.root / JOURNAL_DIR
            if journal_dir.exists():
                for entry in journal_dir.iterdir():
                    if entry.suffix == ".json":
                        try:
                            journal = json.loads(entry.read_text(encoding="utf-8"))
                            if journal.get("phase") != "COMPLETE":
                                issues.append(f"Incomplete transaction journal: {entry.name}")
                        except Exception:
                            pass
        
        return issues
