"""Per-worktree mutation leases.

Each worktree has its own index and working tree. This module grants exclusive
mutation authority over the files inside one specific worktree while allowing
concurrent leases on *different* worktrees.

Distinct from:

* the machine-wide Win32 named mutex in :mod:`os_lock`, which gates governed
  CARLA asset mutation;
* the repository-global shared-Git-metadata lock in :mod:`common_git_lock`,
  which gates refs, objects and the worktree registry.

Leases are registered in the repository's **common** Git directory and keyed by
a SHA-256 digest of the canonical worktree path. The previous scheme flattened
the path into a filename, so ``C:\\a\\b`` and ``C:\\a_b`` produced the same file,
and the lease directory was anchored to whichever checkout happened to run the
code, so two worktrees running different copies shared no authority at all.

Safety properties match the common-Git lock: tri-state liveness, OS-derived
process start identity, mandatory owner token, fencing generation, ABA-safe
release, and a malformed record that blocks rather than being deleted.
"""
from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ultimate_pipeline.governance.single_writer import lock_paths, process_identity
from ultimate_pipeline.governance.single_writer.os_lock import read_only_session

SCHEMA_VERSION = "worktree-mutation-lease/v2"
DEFAULT_LEASE_MINUTES = 240

_ACQUIRE_MAX_ATTEMPTS = 64
_FRESH_PUBLISH_REREAD_DELAY_S = 0.005


class MalformedLeaseError(RuntimeError):
    """A lease file exists but cannot be parsed.

    Ownership evidence is never silently destroyed. Recover deliberately with
    :func:`recover_malformed_lease`, which records what it removed.
    """

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(
            f"BLOCKED_MALFORMED_LEASE at {path}: {reason}. "
            f"Refusing to delete ownership evidence automatically. "
            f"Inspect it, then run recover_malformed_lease(repo_root, worktree_root, "
            f"operator, reason) if it is genuinely corrupt."
        )
        self.path = path
        self.reason = reason


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_in(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds))


@dataclass
class WorktreeLease:
    """One published generation of per-worktree mutation authority."""

    schema: str = SCHEMA_VERSION
    status: str = "active"  # active, released
    worktree_root: str = ""
    worktree_identity: str = ""
    worktree_name: str = ""
    lease_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    owner_token: str = field(default_factory=lambda: uuid.uuid4().hex)
    generation: int = 0
    acquired_at: str = field(default_factory=_utc_now)
    expires_at: str = ""
    holder_pid: int = 0
    holder_ppid: int = 0
    holder_cmdline: str = ""
    # OS-derived process start identity; makes the PID an identity, not a guess.
    holder_start_identity: str = ""
    purpose: str = ""

    @property
    def holder_start_utc(self) -> str:
        return self.holder_start_identity

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = calendar.timegm(time.strptime(self.expires_at, "%Y-%m-%dT%H:%M:%SZ"))
            return time.time() > exp
        except Exception:
            # An unparsable expiry is not proof of death.
            return False

    def to_json(self) -> dict:
        return {
            "schema": self.schema,
            "status": self.status,
            "worktree_root": self.worktree_root,
            "worktree_identity": self.worktree_identity,
            "worktree_name": self.worktree_name,
            "lease_id": self.lease_id,
            "owner_token": self.owner_token,
            "generation": self.generation,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "holder_pid": self.holder_pid,
            "holder_ppid": self.holder_ppid,
            "holder_cmdline": self.holder_cmdline,
            "holder_start_identity": self.holder_start_identity,
            "purpose": self.purpose,
        }

    @classmethod
    def from_json(cls, data: dict) -> "WorktreeLease":
        lease = cls()
        lease.schema = data.get("schema", SCHEMA_VERSION)
        lease.status = data.get("status", "active")
        lease.worktree_root = data.get("worktree_root", "")
        lease.worktree_identity = data.get("worktree_identity", "")
        lease.worktree_name = data.get("worktree_name", "")
        lease.lease_id = data.get("lease_id", uuid.uuid4().hex)
        lease.owner_token = data.get("owner_token", "")
        lease.generation = int(data.get("generation", 0) or 0)
        lease.acquired_at = data.get("acquired_at", "")
        lease.expires_at = data.get("expires_at", "")
        lease.holder_pid = int(data.get("holder_pid", 0) or 0)
        lease.holder_ppid = int(data.get("holder_ppid", 0) or 0)
        lease.holder_cmdline = data.get("holder_cmdline", "")
        lease.holder_start_identity = data.get(
            "holder_start_identity", data.get("holder_start_utc", "")
        )
        lease.purpose = data.get("purpose", "")
        return lease


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def _repo_root_for(worktree_root: Path) -> Path:
    """Repository that owns ``worktree_root``.

    Resolution starts at the worktree itself, so a linked worktree resolves to
    the same common directory as the main checkout.
    """
    return worktree_root


def _worktree_lease_path(worktree_root: Path) -> Path:
    """Collision-safe lease path for one worktree."""
    worktree_root = Path(worktree_root).resolve()
    return lock_paths.worktree_lease_path(_repo_root_for(worktree_root), worktree_root)


def _ledger_path(worktree_root: Path) -> Path:
    lease_path = _worktree_lease_path(worktree_root)
    return lease_path.with_name(f"{lease_path.name}.generations")


# ---------------------------------------------------------------------------
# durable writes
# ---------------------------------------------------------------------------

def _fsync_dir(directory: Path) -> None:
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_payload(path: Path, payload: dict) -> None:
    """Serialise, fsync and atomically replace ``path`` via a unique temp file."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=2, sort_keys=True))
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def _publish_exclusive(path: Path, payload: dict) -> bool:
    """Publish a COMPLETE lease record atomically and exclusively.

    Returns True when this caller won ownership.

    Reserving the destination with ``O_CREAT|O_EXCL`` and filling it afterwards
    leaves a window in which a competing acquirer reads a ZERO-BYTE file, which
    is indistinguishable from corruption. Instead the record is written and
    fsynced to a unique temp file and then hard-linked into place: link creation
    is atomic and fails when the destination exists, on POSIX and Windows alike.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.pub")
    data = json.dumps(payload, indent=2, sort_keys=True)
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.link(str(tmp), str(path))
    except FileExistsError:
        return False
    except (OSError, NotImplementedError):
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return _publish_exclusive_fallback(path, payload)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    _fsync_dir(path.parent)
    return True


def _publish_exclusive_fallback(path: Path, payload: dict) -> bool:
    """O_EXCL reservation fallback for filesystems without hard links."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=2, sort_keys=True))
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    _fsync_dir(path.parent)
    return True


class _LeaseRead:
    ABSENT = "absent"
    PARSED = "parsed"
    MALFORMED = "malformed"


def _read_state(worktree_root: Path) -> tuple[str, Optional[WorktreeLease], str]:
    path = _worktree_lease_path(worktree_root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return _LeaseRead.ABSENT, None, ""
    except OSError as exc:
        return _LeaseRead.MALFORMED, None, f"unreadable: {exc}"
    if not raw.strip():
        return _LeaseRead.MALFORMED, None, "empty file (publisher died mid-write?)"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _LeaseRead.MALFORMED, None, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return _LeaseRead.MALFORMED, None, "top-level JSON is not an object"
    try:
        return _LeaseRead.PARSED, WorktreeLease.from_json(data), ""
    except (TypeError, ValueError) as exc:
        return _LeaseRead.MALFORMED, None, f"unusable lease record: {exc}"


def _read_lease(worktree_root: Path) -> Optional[WorktreeLease]:
    state, lease, reason = _read_state(worktree_root)
    if state is _LeaseRead.MALFORMED:
        raise MalformedLeaseError(_worktree_lease_path(worktree_root), reason)
    return lease


def _write_lease(lease: WorktreeLease) -> None:
    path = _worktree_lease_path(Path(lease.worktree_root))
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_payload(path, lease.to_json())


def _remove_lease(worktree_root: Path) -> None:
    """Unconditional removal. Internal: callers must have proved ownership."""
    try:
        _worktree_lease_path(worktree_root).unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# fencing
# ---------------------------------------------------------------------------

def _issue_generation(worktree_root: Path, floor: int = 0) -> int:
    path = _ledger_path(worktree_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    highest = max(0, int(floor))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.isdigit():
                    highest = max(highest, int(line))
    except (FileNotFoundError, OSError):
        pass
    nxt = highest + 1
    fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)
    try:
        os.write(fd, f"{nxt}\n".encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return nxt


# ---------------------------------------------------------------------------
# ABA-safe claim
# ---------------------------------------------------------------------------

def _claim_by_rename(
    worktree_root: Path, tag: str, expect
) -> tuple[bool, Optional[Path]]:
    """Move the published lease onto a private tombstone, then verify.

    ``os.replace`` is the linearization point. On success the caller owns the
    returned tombstone and must unlink it. When the moved bytes are not the
    generation the caller expected they are restored untouched.
    """
    path = _worktree_lease_path(worktree_root)
    tomb = path.with_name(f"{path.name}.{tag}.{uuid.uuid4().hex}.tombstone")
    try:
        os.replace(path, tomb)
    except OSError:
        return False, None
    try:
        moved = tomb.read_bytes()
    except OSError:
        moved = b""
    if expect(moved):
        return True, tomb
    try:
        os.replace(tomb, path)
    except OSError:
        pass
    return False, None


def _lease_matches(lease_id: str, owner_token: str, generation: int):
    def _check(raw: bytes) -> bool:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(data, dict):
            return False
        return (
            data.get("lease_id") == lease_id
            and data.get("owner_token") == owner_token
            and int(data.get("generation", -1) or 0) == int(generation)
        )
    return _check


def _token_eq(left: str, right: str) -> bool:
    return hmac.compare_digest(str(left), str(right))


# ---------------------------------------------------------------------------
# liveness
# ---------------------------------------------------------------------------

def holder_liveness(lease: WorktreeLease) -> process_identity.LivenessResult:
    return process_identity.probe_liveness(lease.holder_pid)


def reclaim_decision(lease: WorktreeLease) -> tuple[bool, str]:
    """May this lease be reclaimed automatically? Only proof of death qualifies."""
    if lease.status != "active":
        return True, f"recorded status is {lease.status!r}"

    observed = holder_liveness(lease)
    if observed.reclaimable:
        return True, f"holder proven dead ({observed.detail})"
    if observed.alive:
        if lease.holder_start_identity and observed.start_identity:
            if lease.holder_start_identity != observed.start_identity:
                return True, (
                    f"pid {lease.holder_pid} recycled: recorded start "
                    f"{lease.holder_start_identity} != live {observed.start_identity}"
                )
            return False, "holder is alive and is the same process"
        return False, "holder is alive but identity unconfirmed; refusing to reclaim"
    return False, (
        f"holder state UNKNOWN ({observed.detail}); a permission problem, timeout or "
        f"unreadable process record is not proof of death"
    )


# ---------------------------------------------------------------------------
# acquire / release / renew
# ---------------------------------------------------------------------------

def acquire_worktree_lease(
    worktree_root: Path,
    purpose: str = "",
    lease_minutes: int = DEFAULT_LEASE_MINUTES,
) -> WorktreeLease:
    """Acquire exclusive mutation authority over one worktree.

    Publication is atomic and exclusive over a complete record. A held lease is
    reclaimed only when its owner is proven dead: expiry alone, or an UNKNOWN
    owner state, never authorises a steal.
    """
    worktree_root = Path(worktree_root).resolve()
    path = _worktree_lease_path(worktree_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    pid, start_identity = process_identity.current_process_identity()

    for _attempt in range(_ACQUIRE_MAX_ATTEMPTS):
        state, observed, reason = _read_state(worktree_root)
        if state is _LeaseRead.MALFORMED:
            raise MalformedLeaseError(path, reason)

        floor = observed.generation if (observed is not None) else 0
        generation = _issue_generation(worktree_root, floor)

        candidate = WorktreeLease(
            worktree_root=str(worktree_root),
            worktree_identity=lock_paths.worktree_identity(worktree_root),
            worktree_name=worktree_root.name,
            purpose=purpose,
            generation=generation,
            holder_pid=pid,
            holder_ppid=os.getppid(),
            holder_cmdline=" ".join(sys.argv),
            holder_start_identity=start_identity or "",
            expires_at=_utc_in(lease_minutes * 60),
        )

        try:
            won = _publish_exclusive(path, candidate.to_json())
        except OSError as exc:
            raise RuntimeError(f"Failed to acquire worktree lease: {exc}") from exc
        if won:
            return candidate

        state2, existing, reason2 = _read_state(worktree_root)
        if state2 is _LeaseRead.MALFORMED:
            raise MalformedLeaseError(path, reason2)
        if state2 is _LeaseRead.ABSENT:
            time.sleep(_FRESH_PUBLISH_REREAD_DELAY_S)
            continue

        may_reclaim, why = reclaim_decision(existing)
        if may_reclaim:
            claimed, tomb = _claim_by_rename(
                worktree_root,
                "reclaim",
                _lease_matches(
                    existing.lease_id, existing.owner_token, existing.generation
                ),
            )
            if claimed and tomb is not None:
                try:
                    tomb.unlink()
                except OSError:
                    pass
            time.sleep(_FRESH_PUBLISH_REREAD_DELAY_S)
            continue

        raise RuntimeError(
            f"Worktree {worktree_root} leased by another process: "
            f"lease_id={existing.lease_id}, pid={existing.holder_pid}, "
            f"generation={existing.generation}, purpose={existing.purpose!r}; "
            f"not reclaimable because {why}"
        )

    raise RuntimeError(
        f"Failed to acquire worktree lease after {_ACQUIRE_MAX_ATTEMPTS} attempts"
    )



def _require_mine(
    current: Optional[WorktreeLease],
    owner_token: str,
    lease_id: Optional[str],
    action: str,
) -> WorktreeLease:
    if current is None:
        raise RuntimeError(f"cannot {action}: no worktree lease is published")
    if not owner_token:
        raise RuntimeError(
            f"cannot {action}: owner_token is mandatory; refusing token-optional release"
        )
    if not _token_eq(current.owner_token, owner_token):
        raise RuntimeError(
            f"cannot {action}: owner token does not match the published owner "
            f"(generation={current.generation}); refusing"
        )
    if lease_id is not None and current.lease_id != lease_id:
        raise RuntimeError(
            f"cannot {action}: lease_id does not match the published owner "
            f"(generation={current.generation}); refusing"
        )
    return current


def release_worktree_lease(
    worktree_root: Path,
    owner_token: str = "",
    lease_id: Optional[str] = None,
) -> bool:
    """Release the lease, and only with the exact owner token.

    ABA-safe: the published lease is claimed by an atomic rename onto an
    owner-specific tombstone, then verified against our own lease_id, token and
    generation before deletion. A previous owner waking up late cannot remove a
    successor's lease.
    """
    worktree_root = Path(worktree_root).resolve()
    current = _require_mine(_read_lease(worktree_root), owner_token, lease_id, "release")

    claimed, tomb = _claim_by_rename(
        worktree_root,
        "release",
        _lease_matches(current.lease_id, current.owner_token, current.generation),
    )
    if not claimed:
        raise RuntimeError(
            f"cannot release: the published lease changed while releasing "
            f"(expected generation={current.generation}); refusing"
        )
    if tomb is not None:
        try:
            tomb.unlink()
        except OSError:
            pass
    return True


def renew_worktree_lease(
    worktree_root: Path,
    owner_token: str,
    lease_id: Optional[str] = None,
    lease_minutes: int = DEFAULT_LEASE_MINUTES,
) -> WorktreeLease:
    """Extend a still-owned lease. Requires exact token and matching identity."""
    worktree_root = Path(worktree_root).resolve()
    current = _require_mine(_read_lease(worktree_root), owner_token, lease_id, "renew")

    pid, start_identity = process_identity.current_process_identity()
    if current.holder_pid != pid or (
        current.holder_start_identity
        and start_identity
        and current.holder_start_identity != start_identity
    ):
        raise RuntimeError(
            f"cannot renew: caller identity no longer matches the published owner "
            f"(published pid={current.holder_pid}, caller pid={pid})"
        )

    latest = _read_lease(worktree_root)
    if latest is None or latest.generation != current.generation or not _token_eq(
        latest.owner_token, owner_token
    ):
        raise RuntimeError(
            f"cannot renew: generation {current.generation} was superseded "
            f"before renewal completed; refusing"
        )

    updated = WorktreeLease.from_json(current.to_json())
    updated.expires_at = _utc_in(lease_minutes * 60)
    _write_lease(updated)
    return updated


def list_worktree_leases(repo_root: Path) -> list[WorktreeLease]:
    """List leases in the repository-global lease namespace.

    ``repo_root`` is any path inside the repository; the common Git directory is
    resolved from it.
    """
    try:
        leases_dir = lock_paths.worktree_leases_dir(repo_root)
    except RuntimeError:
        return []
    out = []
    for path in sorted(leases_dir.glob("*.lease.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append(WorktreeLease.from_json(data))
        except Exception:
            continue
    return out


def cleanup_expired_leases(repo_root: Path) -> int:
    """Remove leases whose owner is *proven* gone. Live owners are kept.

    Expiry alone is never sufficient: an expired lease whose holder is still
    alive (or whose state is UNKNOWN) is left in place, because expiry is
    evidence that renewal may be unhealthy, not proof that the owner died.
    """
    removed = 0
    for lease in list_worktree_leases(repo_root):
        if not lease.is_expired():
            continue
        may, _why = reclaim_decision(lease)
        if not may:
            continue
        claimed, tomb = _claim_by_rename(
            Path(lease.worktree_root),
            "cleanup",
            _lease_matches(lease.lease_id, lease.owner_token, lease.generation),
        )
        if claimed and tomb is not None:
            try:
                tomb.unlink()
            except OSError:
                pass
            removed += 1
    return removed


def recover_malformed_lease(
    repo_root: Path, worktree_root: Path, operator: str, reason: str
) -> dict:
    """Operator-only removal of a malformed lease, with an audit record."""
    worktree_root = Path(worktree_root).resolve()
    path = _worktree_lease_path(worktree_root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {"recovered": False, "detail": "no lease present"}
    record = {
        "recovered": True,
        "path": str(path),
        "removed_sha256": hashlib.sha256(raw).hexdigest(),
        "removed_bytes": len(raw),
        "recovered_at": _utc_now(),
        "operator": operator,
        "reason": reason,
    }
    claimed, tomb = _claim_by_rename(worktree_root, "recover", lambda _raw: True)
    if claimed and tomb is not None:
        try:
            tomb.unlink()
        except OSError:
            pass
    else:
        record["recovered"] = False
        record["detail"] = "lease changed or vanished during recovery; nothing removed"
    return record
