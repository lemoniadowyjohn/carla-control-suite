"""Per-worktree Git index mutation lease.

Each Git worktree has its own index file. This module provides exclusive
mutation leases for individual worktrees, allowing concurrent mutations
across DIFFERENT worktrees while preventing concurrent mutations on the
SAME worktree/index.

This is distinct from:
- The UE mutator lock (machine-wide, for CARLA asset mutations)
- The repo-wide writer lock (single .agent_locks/writer.lock at repo root)

GAP052: Prevents concurrent mutating agents from sharing one checkout/index.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from ultimate_pipeline.governance.single_writer.os_lock import read_only_session


LOCK_DIR_NAME = ".agent_locks"
WORKTREE_LEASES_DIR = "worktree_leases"
SCHEMA_VERSION = "worktree-mutation-lease/v1"
DEFAULT_LEASE_MINUTES = 240

# Maximum attempts for atomic create-exclusive
_ACQUIRE_MAX_ATTEMPTS = 64

# Fresh publication re-read budget (same pattern as writer_lock.py)
_FRESH_PUBLISH_MAX_REREADS = 100
_FRESH_PUBLISH_REREAD_DELAY_S = 0.005


@dataclass
class WorktreeLease:
    """Exclusive mutation lease for a single Git worktree."""
    
    schema: str = SCHEMA_VERSION
    status: str = "active"  # active, released, expired
    worktree_root: str = ""  # Absolute path to worktree root
    worktree_name: str = ""  # Git worktree name (basename of worktree_root)
    lease_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    acquired_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    expires_at: str = ""  # ISO8601 UTC
    holder_pid: int = 0
    holder_ppid: int = 0
    holder_cmdline: str = ""
    holder_start_utc: str = ""  # Process creation time for identity
    purpose: str = ""  # Human-readable purpose of this lease
    
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
            "worktree_root": self.worktree_root,
            "worktree_name": self.worktree_name,
            "lease_id": self.lease_id,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "holder_pid": self.holder_pid,
            "holder_ppid": self.holder_ppid,
            "holder_cmdline": self.holder_cmdline,
            "holder_start_utc": self.holder_start_utc,
            "purpose": self.purpose,
        }
    
    @classmethod
    def from_json(cls, data: dict) -> "WorktreeLease":
        lease = cls()
        lease.schema = data.get("schema", SCHEMA_VERSION)
        lease.status = data.get("status", "active")
        lease.worktree_root = data.get("worktree_root", "")
        lease.worktree_name = data.get("worktree_name", "")
        lease.lease_id = data.get("lease_id", uuid.uuid4().hex)
        lease.acquired_at = data.get("acquired_at", "")
        lease.expires_at = data.get("expires_at", "")
        lease.holder_pid = data.get("holder_pid", 0)
        lease.holder_ppid = data.get("holder_ppid", 0)
        lease.holder_cmdline = data.get("holder_cmdline", "")
        lease.holder_start_utc = data.get("holder_start_utc", "")
        lease.purpose = data.get("purpose", "")
        return lease


def _get_worktree_leases_dir() -> Path:
    """Get the directory for worktree lease files."""
    # Use the same base as the repo-wide writer lock
    repo_root = Path(__file__).resolve().parents[3]  # ultimate_pipeline/governance/single_writer/
    lock_dir = repo_root / LOCK_DIR_NAME / WORKTREE_LEASES_DIR
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir


def _worktree_lease_path(worktree_root: Path) -> Path:
    """Get the lease file path for a given worktree root."""
    leases_dir = _get_worktree_leases_dir()
    # Use a safe filename based on the worktree path
    safe_name = str(worktree_root).replace(":", "").replace("\\", "_").replace("/", "_").strip("_")
    return leases_dir / f"{safe_name}.lease.json"


def _read_lease(worktree_root: Path) -> Optional[WorktreeLease]:
    """Read the lease for a worktree, if it exists."""
    path = _worktree_lease_path(worktree_root)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return WorktreeLease.from_json(data)
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _write_lease(lease: WorktreeLease) -> None:
    """Atomically write a lease file."""
    path = _worktree_lease_path(Path(lease.worktree_root))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(lease.to_json(), f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _remove_lease(worktree_root: Path) -> None:
    """Remove the lease file for a worktree."""
    path = _worktree_lease_path(worktree_root)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def acquire_worktree_lease(
    worktree_root: Path,
    purpose: str = "",
    lease_minutes: int = DEFAULT_LEASE_MINUTES,
) -> WorktreeLease:
    """Acquire an exclusive mutation lease for a worktree.
    
    Args:
        worktree_root: Absolute path to the worktree root.
        purpose: Human-readable description of why this lease is needed.
        lease_minutes: Lease duration in minutes (default 4 hours).
    
    Returns:
        The acquired WorktreeLease.
    
    Raises:
        RuntimeError: If another active lease exists for this worktree.
    """
    worktree_root = Path(worktree_root).resolve()
    
    # Check for existing active lease
    existing = _read_lease(worktree_root)
    if existing and existing.status == "active" and not existing.is_expired():
        raise RuntimeError(
            f"Worktree {worktree_root} already has an active lease: "
            f"lease_id={existing.lease_id}, pid={existing.holder_pid}, "
            f"purpose={existing.purpose}"
        )
    
    # Create new lease
    lease = WorktreeLease(
        worktree_root=str(worktree_root),
        worktree_name=worktree_root.name,
        purpose=purpose,
        holder_pid=os.getpid(),
        holder_ppid=os.getppid(),
        holder_cmdline=" ".join(sys.argv),
        holder_start_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        expires_at=time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() + lease_minutes * 60)
        ),
    )
    
    # Atomic create-exclusive with retries
    path = _worktree_lease_path(worktree_root)
    for attempt in range(_ACQUIRE_MAX_ATTEMPTS):
        try:
            # Use O_EXCL equivalent: open with 'x' mode (exclusive create)
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(lease.to_json(), f, indent=2, sort_keys=True)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                os.close(fd)
                raise
            return lease
        except FileExistsError:
            # Another process created it; check if it's stale
            time.sleep(0.01)
            existing = _read_lease(worktree_root)
            if existing and (existing.is_expired() or existing.status != "active"):
                # Stale lease; remove and retry
                _remove_lease(worktree_root)
                continue
            # Active lease by another process
            raise RuntimeError(
                f"Worktree {worktree_root} leased by another process: "
                f"pid={existing.holder_pid if existing else 'unknown'}"
            )
        except Exception as e:
            # Other error
            raise RuntimeError(f"Failed to acquire worktree lease: {e}")
    
    raise RuntimeError(f"Failed to acquire worktree lease after {_ACQUIRE_MAX_ATTEMPTS} attempts")


def release_worktree_lease(worktree_root: Path, lease_id: str = "") -> bool:
    """Release a worktree lease.
    
    Args:
        worktree_root: The worktree root path.
        lease_id: Optional lease ID to verify before release.
    
    Returns:
        True if lease was released, False if not found or ID mismatch.
    """
    worktree_root = Path(worktree_root).resolve()
    existing = _read_lease(worktree_root)
    if not existing:
        return False
    if lease_id and existing.lease_id != lease_id:
        return False
    
    existing.status = "released"
    existing.expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_lease(existing)
    _remove_lease(worktree_root)
    return True


def list_worktree_leases() -> list[WorktreeLease]:
    """List all known worktree leases (active and expired)."""
    leases_dir = _get_worktree_leases_dir()
    leases = []
    for path in leases_dir.glob("*.lease.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            leases.append(WorktreeLease.from_json(data))
        except Exception:
            continue
    return leases


def cleanup_expired_leases() -> int:
    """Remove expired lease files. Returns count of removed leases."""
    removed = 0
    for lease in list_worktree_leases():
        if lease.is_expired():
            _remove_lease(Path(lease.worktree_root))
            removed += 1
    return removed


# CLI for standalone usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Worktree mutation lease management")
    parser.add_argument("--acquire", action="store_true", help="Acquire a lease")
    parser.add_argument("--release", action="store_true", help="Release a lease")
    parser.add_argument("--list", action="store_true", help="List all leases")
    parser.add_argument("--cleanup", action="store_true", help="Clean up expired leases")
    parser.add_argument("--worktree", type=str, help="Worktree root path (default: current dir)")
    parser.add_argument("--purpose", type=str, default="", help="Purpose of the lease")
    parser.add_argument("--minutes", type=int, default=DEFAULT_LEASE_MINUTES, help="Lease duration in minutes")
    parser.add_argument("--lease-id", type=str, help="Lease ID for release")
    
    args = parser.parse_args()
    
    worktree_root = Path(args.worktree).resolve() if args.worktree else Path.cwd().resolve()
    
    if args.acquire:
        try:
            lease = acquire_worktree_lease(worktree_root, args.purpose, args.minutes)
            print(f"Acquired lease: {lease.lease_id} for {worktree_root}")
            print(f"  Expires: {lease.expires_at}")
            print(f"  Purpose: {lease.purpose}")
        except RuntimeError as e:
            print(f"FAILED: {e}")
            sys.exit(1)
    elif args.release:
        if release_worktree_lease(worktree_root, args.lease_id):
            print(f"Released lease for {worktree_root}")
        else:
            print(f"FAILED: No matching lease found")
            sys.exit(1)
    elif args.list:
        leases = list_worktree_leases()
        for lease in leases:
            status = "ACTIVE" if not lease.is_expired() else "EXPIRED"
            print(f"{lease.lease_id} {status} {lease.worktree_root} pid={lease.holder_pid} purpose={lease.purpose}")
    elif args.cleanup:
        removed = cleanup_expired_leases()
        print(f"Cleaned up {removed} expired leases")
    else:
        parser.print_help()