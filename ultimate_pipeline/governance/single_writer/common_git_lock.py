"""Common-Git lock for shared Git metadata operations.

Git worktrees share the common directory (<main_repo>/.git) which contains:
- refs/ (branches, tags)
- objects/ (blobs, trees, commits)
- config
- packed-refs
- logs/

Operations that modify common metadata MUST be serialized:
- git fetch (updates refs, objects)
- git push (updates refs)
- git branch/tag creation/deletion
- git worktree add/remove/prune
- git gc
- git repack

This lock is SEPARATE from per-worktree mutation leases. It only
protects the shared .git directory, not worktree-specific state.

GAP052: Prevents concurrent mutations of shared Git metadata.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = "common-git-lock/v1"
DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes max wait

# Fresh publication re-read budget (same pattern as writer_lock.py)
_FRESH_PUBLISH_MAX_REREADS = 100
_FRESH_PUBLISH_REREAD_DELAY_S = 0.005


@dataclass
class CommonGitLock:
    """Exclusive lock for shared Git metadata operations."""
    
    schema: str = SCHEMA_VERSION
    status: str = "active"  # active, released, expired
    lock_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    acquired_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    expires_at: str = ""  # ISO8601 UTC
    holder_pid: int = 0
    holder_ppid: int = 0
    holder_cmdline: str = ""
    holder_start_utc: str = ""  # Process creation time for identity
    operation: str = ""  # Description of the operation (fetch, push, gc, etc.)
    repo_root: str = ""  # Main repository root (not worktree root)
    
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = time.strptime(self.expires_at, "%Y-%m-%dT%H:%M:%SZ")
            now = time.gmtime()
            return time.mktime(now) > time.mktime(exp)
        except Exception:
            return True
    
    def to_json(self) -> dict:
        return {
            "schema": self.schema,
            "status": self.status,
            "lock_id": self.lock_id,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "holder_pid": self.holder_pid,
            "holder_ppid": self.holder_ppid,
            "holder_cmdline": self.holder_cmdline,
            "holder_start_utc": self.holder_start_utc,
            "operation": self.operation,
            "repo_root": self.repo_root,
        }
    
    @classmethod
    def from_json(cls, data: dict) -> "CommonGitLock":
        lock = cls()
        lock.schema = data.get("schema", SCHEMA_VERSION)
        lock.status = data.get("status", "active")
        lock.lock_id = data.get("lock_id", uuid.uuid4().hex)
        lock.acquired_at = data.get("acquired_at", "")
        lock.expires_at = data.get("expires_at", "")
        lock.holder_pid = data.get("holder_pid", 0)
        lock.holder_ppid = data.get("holder_ppid", 0)
        lock.holder_cmdline = data.get("holder_cmdline", "")
        lock.holder_start_utc = data.get("holder_start_utc", "")
        lock.operation = data.get("operation", "")
        lock.repo_root = data.get("repo_root", "")
        return lock


def _get_common_git_lock_path(repo_root: Path) -> Path:
    """Get the path to the common Git lock file."""
    repo_root = Path(repo_root).resolve()
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        raise RuntimeError(f"Not a Git repository: {repo_root}")
    
    # Lock file lives inside the .git directory so it's shared by all worktrees
    lock_dir = git_dir / ".agent_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / "common_git_lock.json"


def _read_lock(repo_root: Path) -> Optional["CommonGitLock"]:
    """Read the common Git lock, if it exists."""
    path = _get_common_git_lock_path(repo_root)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return CommonGitLock.from_json(data)
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _write_lock(lock: "CommonGitLock") -> None:
    """Atomically write the lock file."""
    path = _get_common_git_lock_path(Path(lock.repo_root))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(lock.to_json(), f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _remove_lock(repo_root: Path) -> None:
    """Remove the common Git lock file."""
    path = _get_common_git_lock_path(repo_root)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _is_lock_holder_alive(lock: "CommonGitLock") -> bool:
    """Check if the lock holder process is still alive."""
    pid = lock.holder_pid
    if pid <= 0:
        return False
    try:
        if platform.system() == "Windows":
            # Use tasklist to check
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, timeout=10
            )
            return str(pid) in result.stdout
        else:
            # Unix: send signal 0
            os.kill(pid, 0)
            return True
    except (OSError, subprocess.SubprocessError):
        return False


def acquire_common_git_lock(
    repo_root: Path,
    operation: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> "CommonGitLock":
    """Acquire the common Git metadata lock.
    
    Args:
        repo_root: Main repository root (the one containing .git, not a worktree).
        operation: Human-readable description of the operation (fetch, push, gc, etc.).
        timeout_seconds: Maximum time to wait for lock acquisition.
    
    Returns:
        The acquired CommonGitLock.
    
    Raises:
        RuntimeError: If lock cannot be acquired within timeout.
    """
    repo_root = Path(repo_root).resolve()
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        raise RuntimeError(f"Not a Git repository: {repo_root}")
    
    path = _get_common_git_lock_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    start_time = time.time()
    attempt = 0
    
    while time.time() - start_time < timeout_seconds:
        attempt += 1
        
        # Try to atomically create the lock file
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            # Lock exists; check if it's stale
            existing = _read_lock(repo_root)
            if existing and existing.status == "active":
                if existing.is_expired() or not _is_lock_holder_alive(existing):
                    # Stale lock; remove and retry
                    _remove_lock(repo_root)
                    time.sleep(_FRESH_PUBLISH_REREAD_DELAY_S)
                    continue
                # Active lock held by live process
                remaining = int(timeout_seconds - (time.time() - start_time))
                raise RuntimeError(
                    f"Common Git lock held by pid={existing.holder_pid} "
                    f"(operation={existing.operation}, "
                    f"acquired={existing.acquired_at}, "
                    f"expires={existing.expires_at}). "
                    f"Waited {int(time.time() - start_time)}s, "
                    f"{remaining}s remaining."
                )
            else:
                # Lock file exists but is stale/invalid; remove and retry
                _remove_lock(repo_root)
                time.sleep(_FRESH_PUBLISH_REREAD_DELAY_S)
                continue
        except Exception as e:
            raise RuntimeError(f"Failed to create common Git lock: {e}")
        
        # Successfully created lock file; now write the lock data
        lock = CommonGitLock(
            repo_root=str(repo_root),
            operation=operation,
            holder_pid=os.getpid(),
            holder_ppid=os.getppid(),
            holder_cmdline=" ".join(sys.argv),
            holder_start_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            expires_at=time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(time.time() + timeout_seconds)
            ),
        )
        
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(lock.to_json(), f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            os.close(fd)
            _remove_lock(repo_root)
            raise
        
        return lock
    
    raise RuntimeError(f"Failed to acquire common Git lock after {timeout_seconds}s (attempts: {attempt})")


def release_common_git_lock(repo_root: Path, lock_id: str = "") -> bool:
    """Release the common Git metadata lock.
    
    Args:
        repo_root: Main repository root.
        lock_id: Optional lock ID to verify before release.
    
    Returns:
        True if lock was released, False if not found or ID mismatch.
    """
    repo_root = Path(repo_root).resolve()
    existing = _read_lock(repo_root)
    if not existing:
        return False
    if lock_id and existing.lock_id != lock_id:
        return False
    
    existing.status = "released"
    _write_lock(existing)
    _remove_lock(repo_root)
    return True


@contextmanager
def common_git_lock(
    repo_root: Path,
    operation: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
):
    """Context manager for common Git lock.
    
    Usage:
        with common_git_lock(repo_root, "git fetch"):
            subprocess.run(["git", "fetch"])
    """
    lock = acquire_common_git_lock(repo_root, operation, timeout_seconds)
    try:
        yield lock
    finally:
        release_common_git_lock(Path(lock.repo_root), lock.lock_id)


def get_lock_status(repo_root: Path) -> dict:
    """Get current lock status for debugging/monitoring."""
    existing = _read_lock(repo_root)
    if not existing:
        return {"status": "unlocked", "lock_id": None}
    
    alive = _is_lock_holder_alive(existing)
    expired = existing.is_expired()
    
    if existing.status == "active" and alive and not expired:
        status = "active"
    elif existing.status == "active" and (not alive or expired):
        status = "stale"
    else:
        status = existing.status
    
    return {
        "status": status,
        "lock_id": existing.lock_id,
        "holder_pid": existing.holder_pid,
        "operation": existing.operation,
        "acquired_at": existing.acquired_at,
        "expires_at": existing.expires_at,
        "repo_root": existing.repo_root,
    }


# CLI for standalone usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Common Git metadata lock management")
    parser.add_argument("--acquire", action="store_true", help="Acquire the lock")
    parser.add_argument("--release", action="store_true", help="Release the lock")
    parser.add_argument("--status", action="store_true", help="Show lock status")
    parser.add_argument("--repo", type=str, default=".", help="Repository root path")
    parser.add_argument("--operation", type=str, default="", help="Operation description")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Timeout in seconds")
    parser.add_argument("--lock-id", type=str, help="Lock ID for release")
    
    args = parser.parse_args()
    
    repo_root = Path(args.repo).resolve()
    
    if args.acquire:
        try:
            lock = acquire_common_git_lock(repo_root, args.operation, args.timeout)
            print(f"Acquired common Git lock: {lock.lock_id}")
            print(f"  Operation: {lock.operation}")
            print(f"  Expires: {lock.expires_at}")
        except RuntimeError as e:
            print(f"FAILED: {e}")
            sys.exit(1)
    elif args.release:
        if release_common_git_lock(repo_root, args.lock_id):
            print(f"Released common Git lock")
        else:
            print(f"FAILED: No matching lock found")
            sys.exit(1)
    elif args.status:
        status = get_lock_status(repo_root)
        print(json.dumps(status, indent=2))
    else:
        parser.print_help()