"""Per-worktree mutation leases.

Each worktree has its own index and working tree. This module grants exclusive
mutation authority over the files inside one specific worktree while allowing
concurrent leases on *different* worktrees.

Distinct from:

* the machine-wide Win32 named mutex in :mod:`os_lock`, which gates governed
  CARLA asset mutation;
* the repository-global shared-Git-metadata lock in :mod:`common_git_lock`,
  which gates refs, objects and the worktree registry.

Leases for repository worktrees are registered in their repository's **common**
Git directory; external output roots keep the lease record beneath that root so
independent clones publishing there share one authority. Records are keyed by a
SHA-256 digest of the canonical scope path. The previous scheme flattened the
path into a filename, so ``C:\\a\\b`` and ``C:\\a_b`` produced the same file,
and the lease directory was anchored to whichever checkout happened to run the
code, so two worktrees running different copies shared no authority at all.

Safety properties match the common-Git lock: tri-state liveness, OS-derived
process start identity, mandatory owner token, fencing generation, ABA-safe
release, and a malformed record that blocks rather than being deleted.
"""
from __future__ import annotations

import calendar
from contextlib import contextmanager
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
_GENERATION_CLAIM_TIMEOUT_S = 30.0
_GENERATION_CLAIM_CLEANUP_RETRIES = 1000


class GenerationClaimTimeout(RuntimeError):
    """A particular lease scope was busy for the configured claim interval."""


class MalformedGenerationClaim(RuntimeError):
    """A scope claim exists but its owner record is malformed; retain it."""


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
    host: str = ""
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
            "host": self.host,
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
        lease.host = data.get("host", "")
        lease.purpose = data.get("purpose", "")
        return lease


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def _canonical_lease_root(raw: str) -> Path:
    """Reject missing, relative, or noncanonical roots before path operations."""
    if not isinstance(raw, str) or not raw or not Path(raw).is_absolute():
        raise ValueError("LOCKED_UNKNOWN: worktree_root must be nonempty and absolute")
    root = Path(raw)
    resolved = root.resolve()
    if os.path.normcase(raw) != os.path.normcase(str(resolved)):
        raise ValueError("LOCKED_UNKNOWN: worktree_root must already be canonical")
    return resolved


def _repo_root_for(worktree_root: Path) -> Path | None:
    """Git namespace for the scope, including output roots outside the repo.

    A scope is usually a worktree (or a directory below it). Pipeline output
    roots may be configured elsewhere, so if no ancestor is in a repository,
    anchor their hashed lease record under the output root so separate clones
    contend on the same record. The scope path remains the lease identity.
    """
    scope = Path(worktree_root).resolve()
    for candidate in (scope, *scope.parents):
        if (candidate / ".git").exists():
            return candidate
    # External scopes need a namespace shared by every process targeting that
    # root, including processes launched from different clones. Their lease
    # records are therefore stored under the scope itself by _worktree_lease_path.
    return None


def _worktree_lease_path(worktree_root: Path) -> Path:
    """Collision-safe lease path for one worktree."""
    worktree_root = Path(worktree_root).resolve()
    repo_root = _repo_root_for(worktree_root)
    if repo_root is not None:
        return lock_paths.worktree_lease_path(repo_root, worktree_root)
    path = (
        worktree_root
        / lock_paths.AGENT_LOCKS_DIRNAME
        / lock_paths.WORKTREE_LEASES_DIRNAME
        / f"{lock_paths.worktree_identity(worktree_root)}.lease.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _ledger_path(worktree_root: Path) -> Path:
    lease_path = _worktree_lease_path(worktree_root)
    return lease_path.with_name(f"{lease_path.name}.generations")


def _generation_claim_path_for_lease(lease_path: Path) -> Path:
    """Stable claim beside a lease, without consulting its worktree path."""
    return lease_path.with_name(f"{lease_path.name}.generation-claim")


def _generation_claim_path(worktree_root: Path) -> Path:
    """Stable per-scope mutex file; the O_EXCL-created file is never a lease."""
    return _generation_claim_path_for_lease(_worktree_lease_path(worktree_root))


@contextmanager
def _generation_claim_at_path(
    lease_path: Path, *, timeout_s: float = _GENERATION_CLAIM_TIMEOUT_S
):
    """Hold the exclusive O_EXCL claim while allocating and publishing a lease.

    The claim is a short-lived O_CREAT|O_EXCL file. Its complete owner identity
    permits safe cleanup after a crashed holder; the claim is never parsed as a
    lease or generation ledger.
    """
    path = _generation_claim_path_for_lease(lease_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout_s = max(0.0, float(timeout_s))
    deadline = time.monotonic() + timeout_s

    def _remaining_s() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GenerationClaimTimeout(
                f"LOCKED_UNKNOWN: timed out waiting for generation claim at {path} "
                f"after {timeout_s:.3f}s"
            )
        return remaining

    pid, start_identity = process_identity.current_process_identity()
    claim_token = uuid.uuid4().hex
    payload = json.dumps({
        "pid": pid, "start_identity": start_identity or "", "token": claim_token,
    }, sort_keys=True).encode("utf-8")
    permission_denials = 0
    while True:
        _remaining_s()
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except (FileExistsError, PermissionError):
            # Windows can report an existing O_EXCL target as PermissionError
            # while its creator still has the file open. Treat a confirmed
            # existing path as contention and inspect the owner record below.
            try:
                claim_stat = path.stat()
            except FileNotFoundError:
                # Another process may have removed the claim after our failed
                # exclusive create. Retry the namespace operation.
                continue
            except OSError as exc:
                raise RuntimeError(
                    f"LOCKED_UNKNOWN: cannot inspect generation claim at {path}: {exc}"
                ) from exc
            claim_age = time.time() - claim_stat.st_mtime
            # Normal active claims are short. Avoid opening the record on every
            # contender attempt: Windows denies deletion while another process
            # has a reader handle open, which can starve claim release.
            if claim_age < 1.0:
                time.sleep(min(0.001, _remaining_s()))
                continue
            try:
                observed = path.read_bytes()
                claim = json.loads(observed.decode("utf-8"))
                owner_pid = int(claim["pid"])
                if not str(claim["token"]):
                    raise ValueError("generation claim token is empty")
                owner_start = str(claim.get("start_identity", ""))
            except FileNotFoundError:
                # The prior holder may remove the claim after stat() but
                # before read_bytes(). That is a normal namespace race; retry
                # acquisition rather than treating the missing record as
                # malformed or unknown ownership.
                continue
            except PermissionError as exc:
                # Windows can briefly deny a read while a prior holder removes
                # the claim. Re-read after that atomic namespace transition.
                permission_denials += 1
                if permission_denials > 200:
                    raise RuntimeError(
                        f"LOCKED_UNKNOWN: generation claim remained unreadable at {path}"
                    ) from exc
                time.sleep(min(0.001, _remaining_s()))
                continue
            except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
                raise MalformedGenerationClaim(
                    f"LOCKED_UNKNOWN: malformed generation claim at {path}: {exc}"
                ) from exc
            permission_denials = 0
            owner_state = process_identity.probe_liveness(owner_pid)
            owner_dead = owner_state.reclaimable or (
                owner_state.alive and owner_start and owner_state.start_identity
                and owner_start != owner_state.start_identity
            )
            if owner_dead:
                recovery_name = "WorktreeLeaseClaimRecovery_" + hashlib.sha256(
                    str(path.resolve()).encode("utf-8")
                ).hexdigest()[:32]
                from ultimate_pipeline.governance.single_writer.os_lock import NamedMutex
                recovery = NamedMutex(recovery_name)
                if recovery.acquire(timeout_ms=1000).acquired:
                    try:
                        current = path.read_bytes()
                        if current == observed:
                            state = process_identity.probe_liveness(owner_pid)
                            still_dead = state.reclaimable or (
                                state.alive and owner_start and state.start_identity
                                and owner_start != state.start_identity
                            )
                            if still_dead:
                                path.unlink(missing_ok=True)
                    except FileNotFoundError:
                        # The observed claim was removed before the serialized
                        # re-read; retry without treating it as ownership loss.
                        pass
                    finally:
                        recovery.release()
                continue
            time.sleep(min(0.001, _remaining_s()))
            continue
        try:
            view = memoryview(payload)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        else:
            os.close(fd)
        break
    try:
        yield
    finally:
        for _cleanup_attempt in range(_GENERATION_CLAIM_CLEANUP_RETRIES):
            try:
                path.unlink(missing_ok=True)
                break
            except PermissionError as exc:
                # Windows may briefly deny deletion while a contender has the
                # claim open for its liveness check. Retry, then fail visibly
                # instead of reporting success with a leaked live-owner claim.
                if _cleanup_attempt + 1 == _GENERATION_CLAIM_CLEANUP_RETRIES:
                    raise RuntimeError(
                        f"LOCKED_UNKNOWN: could not release generation claim at {path}"
                    ) from exc
                time.sleep(0.005)
            except OSError as exc:
                raise RuntimeError(
                    f"LOCKED_UNKNOWN: could not release generation claim at {path}: {exc}"
                ) from exc


@contextmanager
def _generation_claim(
    worktree_root: Path, *, timeout_s: float = _GENERATION_CLAIM_TIMEOUT_S
):
    """Claim the lease namespace associated with a worktree root."""
    with _generation_claim_at_path(
        _worktree_lease_path(Path(worktree_root)), timeout_s=timeout_s
    ):
        yield


# ---------------------------------------------------------------------------
# durable writes
# ---------------------------------------------------------------------------

def _fsync_dir(directory: Path, *, required: bool = False) -> None:
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        if required:
            raise
        return
    try:
        os.fsync(fd)
    except OSError:
        if required:
            raise
    finally:
        os.close(fd)


def _write_payload(path: Path, payload: dict, *, durable: bool = False) -> None:
    """Serialise, fsync and atomically replace ``path`` via a unique temp file."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, indent=2, sort_keys=True))
                fh.flush()
                os.fsync(fh.fileno())
        except BaseException:
            raise
        if os.name == "nt" and durable:
            # MOVEFILE_WRITE_THROUGH asks Windows to flush the move before it
            # returns.  The file itself was fsynced above.
            import ctypes

            move_file = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
            move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
            move_file.restype = ctypes.c_int
            if not move_file(str(tmp), str(path), 0x1 | 0x8):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            os.replace(tmp, path)
            _fsync_dir(path.parent, required=durable)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _publish_exclusive(path: Path, payload: dict | bytes) -> bool:
    data = payload if isinstance(payload, bytes) else json.dumps(
        payload, indent=2, sort_keys=True
    ).encode("utf-8")
    return _publish_exclusive_bytes(path, data)


def _publish_exclusive_bytes(path: Path, data: bytes) -> bool:
    """Publish a COMPLETE lease record atomically and exclusively.

    Returns True when this caller won ownership.

    Reserving the destination with ``O_CREAT|O_EXCL`` and filling it afterwards
    leaves a window in which a competing acquirer reads a ZERO-BYTE file, which
    is indistinguishable from corruption. Instead the record is written and
    fsynced to a unique temp file and then hard-linked into place: link creation
    is atomic and fails when the destination exists, on POSIX and Windows alike.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.pub")
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as fh:
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
        return _publish_exclusive_fallback_bytes(path, data)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    _fsync_dir(path.parent)
    return True


def _publish_exclusive_fallback(path: Path, payload: dict | bytes) -> bool:
    data = payload if isinstance(payload, bytes) else json.dumps(
        payload, indent=2, sort_keys=True
    ).encode("utf-8")
    return _publish_exclusive_fallback_bytes(path, data)


def _publish_exclusive_fallback_bytes(path: Path, data: bytes) -> bool:
    """O_EXCL reservation fallback for filesystems without hard links."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    except PermissionError:
        if path.exists():
            return False
        raise
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
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


def _read_lease_at_path(path: Path) -> Optional[WorktreeLease]:
    """Read a lease from its authoritative namespace path, even if its tree is gone."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise MalformedLeaseError(path, f"unreadable: {exc}") from exc
    if not raw.strip():
        raise MalformedLeaseError(path, "empty file (publisher died mid-write?)")
    try:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top-level JSON is not an object")
        return WorktreeLease.from_json(data)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise MalformedLeaseError(path, f"invalid lease record: {exc}") from exc


def _prepare_lease_publication(lease: WorktreeLease) -> Path:
    """Validate scope before I/O and populate missing helper metadata."""
    root = _canonical_lease_root(lease.worktree_root)
    identity = lock_paths.worktree_identity(root)
    if lease.worktree_identity and lease.worktree_identity != identity:
        raise RuntimeError("LOCKED_UNKNOWN: lease identity contradicts canonical root")
    lease.worktree_identity = identity
    if not lease.worktree_name:
        lease.worktree_name = root.name
    return root


def _reserve_publication_generation(root: Path, lease: WorktreeLease) -> None:
    """Durably reserve the supplied fresh fence (or allocate a default)."""
    high = _generation_high_water(root)
    if lease.generation < 0:
        raise RuntimeError("LOCKED_UNKNOWN: negative lease generation")
    if lease.generation == 0:
        lease.generation = high + 1
    if lease.generation <= high:
        raise RuntimeError(
            f"LOCKED_UNKNOWN: stale generation {lease.generation} "
            f"is not above durable high-water {high}"
        )
    issued = _issue_generation(root, floor=lease.generation - 1)
    if issued != lease.generation:
        raise RuntimeError("LOCKED_UNKNOWN: generation allocation did not match publication")


def _write_lease(lease: WorktreeLease) -> None:
    """Compatibility helper: fenced first publication or exact current update."""
    root = _prepare_lease_publication(lease)
    path = _worktree_lease_path(root)
    with _generation_claim(root):
        current = _read_lease(root)
        if current is None:
            _reserve_publication_generation(root, lease)
            if not _publish_exclusive(path, lease.to_json()):
                raise RuntimeError(
                    f"cannot write lease: another owner published at {path}; refusing"
                )
            return
        same_owner = (
            current.lease_id == lease.lease_id
            and _token_eq(current.owner_token, lease.owner_token)
            and current.generation == lease.generation
            and current.worktree_root == lease.worktree_root
            and current.worktree_identity == lease.worktree_identity
            and _generation_high_water(root) == lease.generation
        )
        if not same_owner:
            raise RuntimeError(
                f"cannot write lease: published owner or generation changed at {path}; refusing"
            )
        _write_payload(path, lease.to_json())


def _remove_lease(worktree_root: Path) -> None:
    """Unconditional removal. Internal: callers must have proved ownership."""
    try:
        _worktree_lease_path(worktree_root).unlink(missing_ok=True)
    except OSError:
        pass


def publish_lease(lease: WorktreeLease) -> None:
    """First publication requires an absent path and an unused durable fence."""
    root = _prepare_lease_publication(lease)
    path = _worktree_lease_path(root)
    with _generation_claim(root):
        if _read_lease(root) is not None:
            raise RuntimeError(
                f"cannot publish lease: an existing lease is present at {path}; refusing"
            )
        _reserve_publication_generation(root, lease)
        if not _publish_exclusive(path, lease.to_json()):
            raise RuntimeError(
                f"cannot publish lease: another publisher won at {path}; refusing"
            )


def validate_lease(lease: WorktreeLease) -> bool:
    """Validate that a lease record is well-formed and not stale.

    Returns True when the lease status is ``active``, has a non-empty generation
    number, and its payload fields are all present and consistent. Returns False
    for any malformed lease, LOCKED_UNKNOWN outcome, or generation gap.
    """
    if lease.status != "active":
        return False
    if lease.generation <= 0:
        return False
    required_fields = [
        "lease_id", "owner_token", "purpose", "schema",
        "worktree_root", "worktree_name",
    ]
    missing = [f for f in required_fields if not getattr(lease, f, None)]
    if missing:
        return False
    return True


def lease_is_current(lease: WorktreeLease) -> bool:
    """Verify that the published record still matches this exact owner.

    A caller-held dataclass and matching generation number alone do not prove
    current ownership: the lease ID and owner token must match on disk too.
    """
    if not validate_lease(lease):
        return False
    try:
        current = _read_lease(Path(lease.worktree_root))
    except (OSError, RuntimeError, MalformedLeaseError):
        return False
    return bool(
        current
        and current.status == "active"
        and current.generation == lease.generation
        and current.lease_id == lease.lease_id
        and _token_eq(current.owner_token, lease.owner_token)
    )


def current_generation(scope_path: Path) -> int:
    """Return the latest generation number for a scope path, or 0 if absent.

    This is the public API for other modules to discover the current generation
    without acquiring a lease themselves.
    """
    path = _worktree_lease_path(Path(scope_path))
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return 0
    except OSError:
        return 0
    if not raw.strip():
        return 0
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 0
    generation = int(data.get("generation", 0) or 0)
    return max(0, generation)


def release_lease(lease: WorktreeLease) -> bool:
    """Release the lease with the exact owner token. Token-less release fails closed."""
    worktree_root = Path(lease.worktree_root)
    return release_worktree_lease(worktree_root, lease.owner_token, lease.lease_id)


# ---------------------------------------------------------------------------
# fencing
# ---------------------------------------------------------------------------

def _generation_marker_path(worktree_root: Path) -> Path:
    ledger = _ledger_path(worktree_root)
    return ledger.with_name(f"{ledger.name}.initialized")


def _generation_high_water(worktree_root: Path) -> int:
    """Read an intact monotonic ledger; missing initialized ledgers fail closed."""
    path = _ledger_path(worktree_root)
    marker = _generation_marker_path(worktree_root)
    try:
        marker_data = marker.read_bytes()
    except FileNotFoundError:
        marker_data = None  # Compatibility with older (unmarked) ledgers.
    except OSError as exc:
        raise RuntimeError(f"LOCKED_UNKNOWN: generation marker unreadable: {exc}") from exc
    if marker_data is not None and marker_data != b"worktree-generation-ledger/v1\n":
        raise RuntimeError("LOCKED_UNKNOWN: malformed generation initialization marker")
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        if marker_data is not None:
            raise RuntimeError("LOCKED_UNKNOWN: initialized generation ledger is missing")
        return 0
    except OSError as exc:
        raise RuntimeError(f"LOCKED_UNKNOWN: generation ledger unreadable: {exc}") from exc
    if not raw or not raw.endswith(b"\n"):
        raise RuntimeError("LOCKED_UNKNOWN: empty or partially written generation ledger")
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise RuntimeError("LOCKED_UNKNOWN: generation ledger is not ASCII") from exc
    previous = 0
    for line in lines:
        if not line.isdigit() or int(line) <= previous:
            raise RuntimeError("LOCKED_UNKNOWN: corrupt or nonmonotonic generation ledger")
        previous = int(line)
    return previous


def _issue_generation(worktree_root: Path, floor: int = 0) -> int:
    """Allocate and fsync the next monotonic generation under the claim."""
    path = _ledger_path(worktree_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    high = _generation_high_water(worktree_root)
    marker = _generation_marker_path(worktree_root)
    if not marker.exists():
        if not _publish_exclusive_bytes(marker, b"worktree-generation-ledger/v1\n"):
            raise RuntimeError("LOCKED_UNKNOWN: generation marker publication raced")
    nxt = max(0, high, int(floor)) + 1
    fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)
    try:
        payload = f"{nxt}\n".encode("ascii")
        written = 0
        while written < len(payload):
            count = os.write(fd, payload[written:])
            if count <= 0:
                raise OSError("generation ledger append made no progress")
            written += count
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)
    return nxt

# ---------------------------------------------------------------------------
# ABA-safe claim
# ---------------------------------------------------------------------------

def _claim_lease_path(
    path: Path, tag: str, expect
) -> tuple[bool, Optional[Path]]:
    """Move the published lease onto a private tombstone, then verify.

    ``os.replace`` is the linearization point. On success the caller owns the
    returned tombstone and must unlink it. When the moved bytes are not the
    generation the caller expected they are restored untouched.
    """
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
    # Restore through the same exclusive publisher used for initial lease
    # admission. This preserves the exact audited bytes without overwriting a
    # successor that appeared while the original record was at the tombstone.
    try:
        raw = tomb.read_bytes()
        restored = _publish_exclusive_bytes(path, raw)
    except OSError as exc:
        raise RuntimeError(
            f"LOCKED_UNKNOWN: failed to restore lease from {tomb} to {path}; "
            f"recovery copy retained at {tomb}: {exc}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"LOCKED_UNKNOWN: failed to restore lease from {tomb} to {path}; "
            f"recovery copy retained at {tomb}: {exc}"
        ) from exc
    if not restored:
        if path.exists():
            orphan = path.with_name(f"{path.name}.{tag}.{uuid.uuid4().hex}.orphaned")
            try:
                os.replace(tomb, orphan)
            except OSError as exc:
                raise RuntimeError(
                    f"LOCKED_UNKNOWN: successor lease exists at {path}; could not "
                    f"preserve displaced lease {tomb} as an orphan: {exc}. "
                    f"The displaced lease remains at {tomb}."
                ) from exc
            return False, None
        raise RuntimeError(
            f"LOCKED_UNKNOWN: exclusive restore did not publish {tomb} to {path}; "
            f"recovery copy retained at {tomb}"
        )
    try:
        tomb.unlink()
    except OSError:
        pass
    return False, None


def _claim_by_rename(
    worktree_root: Path, tag: str, expect
) -> tuple[bool, Optional[Path]]:
    return _claim_lease_path(_worktree_lease_path(worktree_root), tag, expect)


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
    owner_token: str | None = None,
) -> WorktreeLease:
    """Acquire exclusive mutation authority over one worktree.

    A read-only session is refused outright: no mutation lease may be taken
    while READ_ONLY_SESSION is set.

    Publication is atomic and exclusive over a complete record. A held lease is
    reclaimed only when its owner is proven dead: expiry alone, or an UNKNOWN
    owner state, never authorises a steal.
    """
    if read_only_session():
        raise RuntimeError(
            "READ_ONLY_SESSION is set: refusing worktree mutation lease acquisition"
        )
    worktree_root = Path(worktree_root).resolve()
    path = _worktree_lease_path(worktree_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    pid, start_identity = process_identity.current_process_identity()

    for _attempt in range(_ACQUIRE_MAX_ATTEMPTS):
        try:
            claim = _generation_claim(worktree_root)
            claim.__enter__()
        except OSError as exc:
            # A competing process owns the exclusive scope claim. Retry without
            # allocating a generation outside that critical section.
            if getattr(exc, "winerror", None) in (33, 36) or getattr(exc, "errno", None) in (11, 13):
                time.sleep(_FRESH_PUBLISH_REREAD_DELAY_S)
                continue
            raise RuntimeError(f"Failed to acquire generation claim: {exc}") from exc
        try:
            state, observed, reason = _read_state(worktree_root)
            if state is _LeaseRead.MALFORMED:
                raise MalformedLeaseError(path, reason)

            if observed is not None:
                may_reclaim, why = reclaim_decision(observed)
                if not may_reclaim:
                    raise RuntimeError(
                        f"Worktree {worktree_root} leased by another process: "
                        f"lease_id={observed.lease_id}, pid={observed.holder_pid}, "
                        f"generation={observed.generation}, purpose={observed.purpose!r}; "
                        f"not reclaimable because {why}"
                    )
                claimed, tomb = _claim_by_rename(
                    worktree_root,
                    "reclaim",
                    _lease_matches(
                        observed.lease_id, observed.owner_token, observed.generation
                    ),
                )
                if claimed and tomb is not None:
                    try:
                        tomb.unlink()
                    except OSError:
                        pass
                time.sleep(_FRESH_PUBLISH_REREAD_DELAY_S)
                continue

            generation = _issue_generation(worktree_root)
            candidate = WorktreeLease(
                worktree_root=str(worktree_root),
                worktree_identity=lock_paths.worktree_identity(worktree_root),
                worktree_name=worktree_root.name,
                purpose=purpose,
                owner_token=owner_token or uuid.uuid4().hex,
                generation=generation,
                holder_pid=pid,
                holder_ppid=os.getppid(),
                holder_cmdline=" ".join(sys.argv),
                host=os.uname().nodename if hasattr(os, "uname") else "",
                holder_start_identity=start_identity or "",
                expires_at=_utc_in(lease_minutes * 60),
            )
            try:
                won = _publish_exclusive(path, candidate.to_json())
            except OSError as exc:
                raise RuntimeError(f"Failed to acquire worktree lease: {exc}") from exc
            if won:
                return candidate
            # All compliant writers hold the claim, so this indicates an
            # external/legacy writer. Do not infer generation ownership.
            raise RuntimeError(
                f"LOCKED_UNKNOWN: lease appeared outside generation claim for {worktree_root}"
            )
        finally:
            claim.__exit__(None, None, None)

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
    with _generation_claim(worktree_root):
        current = _require_mine(
            _read_lease(worktree_root), owner_token, lease_id, "release"
        )
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
    with _generation_claim(worktree_root):
        current = _require_mine(_read_lease(worktree_root), owner_token, lease_id, "renew")
        pid, start_identity = process_identity.current_process_identity()
        if current.holder_pid != pid or (
            current.holder_start_identity and start_identity
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
        # _write_payload is intentionally called only while the claim is held.
        _write_payload(_worktree_lease_path(worktree_root), updated.to_json())
        return updated


def _lease_path_matches_identity(path: Path, lease: WorktreeLease) -> bool:
    """Require explicit canonical identity and bind live roots to Git namespace."""
    try:
        root = _canonical_lease_root(lease.worktree_root)
        identity = lock_paths.worktree_identity(root)
        if path.name != f"{identity}.lease.json":
            return False
        if lease.worktree_identity != identity:
            return False
        owning_repo = _repo_root_for(root)
        if owning_repo is not None:
            namespace = lock_paths.worktree_leases_dir(owning_repo)
            if path.parent.resolve() != namespace.resolve():
                return False
        return True
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _iter_worktree_leases(repo_root: Path):
    """Yield ``(physical lease path, parsed record)`` from the common Git dir."""
    try:
        leases_dir = lock_paths.worktree_leases_dir(repo_root)
    except RuntimeError:
        return
    for path in sorted(leases_dir.glob("*.lease.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            lease = WorktreeLease.from_json(data)
        except Exception:
            continue
        if _lease_path_matches_identity(path, lease):
            yield path, lease


def list_worktree_leases(repo_root: Path) -> list[WorktreeLease]:
    """List valid leases in the repository-global lease namespace.

    ``repo_root`` is any path inside the repository; the common Git directory is
    resolved from it.
    """
    return [lease for _path, lease in _iter_worktree_leases(repo_root)]


def cleanup_expired_leases(
    repo_root: Path, *, diagnostics: list[dict] | None = None
) -> int:
    """Sweep independent expired/dead leases and retain corrupt evidence."""
    removed = 0
    for lease_path, lease in _iter_worktree_leases(repo_root):
        # Do not consult blocked/malformed claims for unexpired records.
        if not lease.is_expired():
            continue
        try:
            with _generation_claim_at_path(lease_path):
                current = _read_lease_at_path(lease_path)
                if (
                    current is None
                    or not _lease_path_matches_identity(lease_path, current)
                    or current.generation != lease.generation
                    or current.lease_id != lease.lease_id
                    or not _token_eq(current.owner_token, lease.owner_token)
                ):
                    continue
                # Recheck expiry, liveness and identity under the claim.
                if not current.is_expired():
                    continue
                may, _why = reclaim_decision(current)
                if not may:
                    continue
                claimed, tomb = _claim_lease_path(
                    lease_path, "cleanup",
                    _lease_matches(
                        current.lease_id, current.owner_token, current.generation
                    ),
                )
                if claimed and tomb is not None:
                    try:
                        tomb.unlink()
                    except OSError:
                        pass
                    removed += 1
        except MalformedLeaseError as exc:
            # Changed between listing and under-claim reread: operator-only.
            if diagnostics is not None:
                diagnostics.append({
                    "status": "LOCKED_UNKNOWN",
                    "lease_path": str(lease_path),
                    "reason": str(exc),
                    "evidence_preserved": True,
                })
            continue
        except (GenerationClaimTimeout, MalformedGenerationClaim) as exc:
            # A claim is scoped to this physical lease.  Keep its bytes for
            # operator recovery and continue with unrelated expired entries.
            if diagnostics is not None:
                diagnostics.append({
                    "status": "LOCKED_UNKNOWN",
                    "lease_path": str(lease_path),
                    "claim_path": str(_generation_claim_path_for_lease(lease_path)),
                    "reason": str(exc),
                    "evidence_preserved": True,
                })
            continue
    return removed


def recover_malformed_lease(
    repo_root: Path, worktree_root: Path, operator: str, reason: str
) -> dict:
    """Operator recovery within the repo's common Git namespace.

    Persist a BEFORE receipt under the claim, then move only the exact audited
    malformed bytes. A crash leaves an INTENT receipt and/or tombstone for
    subsequent operator inspection; nothing outside the lease namespace is
    modified.
    """
    if not isinstance(operator, str) or not operator.strip():
        raise ValueError("operator identity is required for malformed recovery")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason is required for malformed recovery")
    root = _canonical_lease_root(str(worktree_root))
    path = lock_paths.worktree_lease_path(Path(repo_root), root)
    with _generation_claim_at_path(path):
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return {"recovered": False, "detail": "no lease present", "path": str(path)}
        try:
            current = _read_lease_at_path(path)
        except MalformedLeaseError:
            current = None
        if current is not None and _lease_path_matches_identity(path, current):
            raise RuntimeError(
                "LOCKED_UNKNOWN: valid lease evidence cannot be removed "
                "through malformed-lease recovery"
            )
        # Keep the intent receipt in the already-existing lease namespace.
        # This avoids a newly-created directory entry whose parent durability
        # would otherwise need a separate crash-safe publication protocol.
        audit = path.parent / f"{path.name}.recovery.{uuid.uuid4().hex}.json"
        record = {
            "recovered": False,
            "path": str(path),
            "removed_sha256": hashlib.sha256(raw).hexdigest(),
            "removed_bytes": len(raw),
            "recovered_at": _utc_now(),
            "operator": operator,
            "reason": reason,
            "audit_path": str(audit),
        }
        _write_payload(audit, {**record, "phase": "INTENT"}, durable=True)
        claimed, tomb = _claim_lease_path(
            path, "recover", lambda candidate: candidate == raw
        )
        if claimed and tomb is not None:
            try:
                tomb.unlink()
            except OSError as exc:
                _write_payload(audit, {
                    **record, "phase": "BLOCKED_TOMBSTONE", "tombstone": str(tomb),
                }, durable=True)
                raise RuntimeError(
                    f"LOCKED_UNKNOWN: recovered bytes retained at {tomb}; "
                    f"operator inspection required"
                ) from exc
            record["recovered"] = True
            record["phase"] = "COMPLETE"
        else:
            record["detail"] = "lease changed or vanished; nothing removed"
            record["phase"] = "NO_CHANGE"
        _write_payload(audit, record, durable=True)
        return record
