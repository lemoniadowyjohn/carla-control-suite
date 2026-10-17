"""Repository-global authority for mutations of shared Git metadata.

Git worktrees share one common directory (``git rev-parse --git-common-dir``)
holding refs, objects, config, packed-refs and the worktree registry. Anything
that mutates that state must be serialised: fetch, push, branch/tag creation and
deletion, worktree add/remove/prune, gc, repack.

This authority is separate from per-worktree mutation leases, which protect
files inside one checkout only.

Safety properties implemented here
----------------------------------
Tri-state liveness
    A holder is reclaimed only when it is *proven* dead. ``UNKNOWN`` -- EPERM,
    access denied, an API timeout, an unreadable process record -- is never
    reclaimed. See :mod:`process_identity`.

Process identity, not PID
    Every publication records the holder's PID *and* an OS-derived process start
    identity. A recycled PID is therefore detectable.

Mandatory owner token
    Release and renewal require an exact token. No token, a wrong token, or a
    stale token from a previous generation all fail closed.

Fencing token
    Each acquisition carries a strictly increasing ``generation`` taken from an
    append-only ledger, so successive acquisitions are ordered and a generation
    is never reused.

ABA-safe release and reclaim
    Both claim ownership by atomically renaming the published lock onto an
    owner-specific tombstone and then verifying that what was moved is still the
    generation the caller expected. The ``os.replace`` is the linearization
    point: after it, either the caller provably owns the exact bytes it removed,
    or it restores them.

Expiry is evidence, not death
    An expired lease whose owner is demonstrably alive is still owned. Expiry
    only means renewal may be unhealthy.

Malformed evidence is never silently destroyed
    An unreadable lock blocks acquisition with an actionable diagnostic and is
    removed only by an explicit operator recovery call that records the old
    bytes.
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
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ultimate_pipeline.governance.single_writer import lock_paths, process_identity

SCHEMA_VERSION = "common-git-lock/v2"
DEFAULT_TIMEOUT_SECONDS = 300

_FRESH_PUBLISH_REREAD_DELAY_S = 0.005
_LOCK_FILENAME = lock_paths.COMMON_GIT_LOCK_FILENAME
_LEDGER_FILENAME = "common_git_lock.generations"


class MalformedLockError(RuntimeError):
    """Ownership evidence exists but cannot be parsed.

    Raised instead of silently deleting the file. Recover with
    :func:`recover_malformed_lock`, which records what it removed.
    """

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(
            f"BLOCKED_MALFORMED_LOCK at {path}: {reason}. "
            f"Refusing to delete ownership evidence automatically. "
            f"Inspect it, then run recover_malformed_lock(repo_root, operator, reason) "
            f"if it is genuinely corrupt."
        )
        self.path = path
        self.reason = reason


@dataclass
class CommonGitLock:
    """One published generation of the repository-global authority."""

    schema: str = SCHEMA_VERSION
    status: str = "active"  # active, released
    lock_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    owner_token: str = field(default_factory=lambda: uuid.uuid4().hex)
    generation: int = 0
    acquired_at: str = field(default_factory=lambda: _utc_now())
    expires_at: str = ""  # ISO8601 UTC
    holder_pid: int = 0
    holder_ppid: int = 0
    holder_cmdline: str = ""
    # OS-derived process start identity. This is what makes the PID an identity.
    holder_start_identity: str = ""
    operation: str = ""
    repo_root: str = ""

    @property
    def holder_start_utc(self) -> str:
        """Backwards-compatible alias for the start identity."""
        return self.holder_start_identity

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            # Pure UTC arithmetic: never time.mktime, which applies local time
            # and DST and skewed expiry by an hour on DST-active hosts.
            exp = calendar.timegm(time.strptime(self.expires_at, "%Y-%m-%dT%H:%M:%SZ"))
            return time.time() > exp
        except Exception:
            # An unparsable expiry is not proof of death; treat as not expired
            # so a damaged record cannot authorise a steal.
            return False

    def to_json(self) -> dict:
        return {
            "schema": self.schema,
            "status": self.status,
            "lock_id": self.lock_id,
            "owner_token": self.owner_token,
            "generation": self.generation,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "holder_pid": self.holder_pid,
            "holder_ppid": self.holder_ppid,
            "holder_cmdline": self.holder_cmdline,
            "holder_start_identity": self.holder_start_identity,
            "operation": self.operation,
            "repo_root": self.repo_root,
        }

    @classmethod
    def from_json(cls, data: dict) -> "CommonGitLock":
        lock = cls()
        lock.schema = data.get("schema", SCHEMA_VERSION)
        lock.status = data.get("status", "active")
        lock.lock_id = data.get("lock_id", uuid.uuid4().hex)
        lock.owner_token = data.get("owner_token", "")
        lock.generation = int(data.get("generation", 0) or 0)
        lock.acquired_at = data.get("acquired_at", "")
        lock.expires_at = data.get("expires_at", "")
        lock.holder_pid = int(data.get("holder_pid", 0) or 0)
        lock.holder_ppid = int(data.get("holder_ppid", 0) or 0)
        lock.holder_cmdline = data.get("holder_cmdline", "")
        lock.holder_start_identity = data.get(
            "holder_start_identity", data.get("holder_start_utc", "")
        )
        lock.operation = data.get("operation", "")
        lock.repo_root = data.get("repo_root", "")
        return lock


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_in(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds))


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def _get_common_git_lock_path(repo_root: Path) -> Path:
    """Path of the lock, anchored in the common Git directory.

    Resolved by Git itself so a main checkout and every linked worktree land on
    the same file. ``repo_root/".git"`` cannot be used: in a linked worktree
    ``.git`` is a file, and tolerating that would give each worktree its own
    'shared' lock.
    """
    return lock_paths.common_git_lock_path(repo_root)


def _ledger_path(repo_root: Path) -> Path:
    return lock_paths.agent_locks_dir(repo_root) / _LEDGER_FILENAME


# ---------------------------------------------------------------------------
# durable, atomic publication
# ---------------------------------------------------------------------------

def _fsync_dir(directory: Path) -> None:
    """Best-effort parent-directory durability.

    On POSIX fsync of the containing directory is what makes a rename/create
    durable. Windows rejects opening a directory this way, so failure is
    expected and ignored there.
    """
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
    """Serialise, fsync and atomically replace ``path``.

    The temp name is unique per writer. A fixed ``.tmp`` name let concurrent
    writers collide on one file and publish each other's bytes.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    data = json.dumps(payload, indent=2, sort_keys=True)
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # fdopen took ownership of fd; there is no second close on this path.
            fh.write(data)
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
    """Publish ``payload`` at ``path`` atomically and exclusively.

    Returns True when this caller won ownership, False when someone else
    already published there.

    Creating the destination with ``O_CREAT|O_EXCL`` and filling it afterwards
    leaves a window in which a concurrent reader observes a ZERO-BYTE file,
    which is indistinguishable from corruption and would abort every competing
    acquirer. Instead the complete record is written and fsynced to a unique
    temp file, then hard-linked into place: link creation is atomic and fails
    if the destination exists, on both POSIX and Windows. The published path is
    therefore never seen empty or half-written.
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
        # Filesystems without hard links (some network shares) fall back to
        # O_EXCL reservation. The empty-file window returns there, so the
        # published record is written immediately and unreadable-bytes are
        # retried rather than treated as corruption.
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
    data = json.dumps(payload, indent=2, sort_keys=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
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


class _LockRead:
    """Result of reading the published lock."""

    ABSENT = "absent"
    PARSED = "parsed"
    MALFORMED = "malformed"


def _read_state(repo_root: Path) -> tuple[str, Optional[CommonGitLock], str]:
    """Read the published lock, distinguishing absent from malformed."""
    path = _get_common_git_lock_path(repo_root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return _LockRead.ABSENT, None, ""
    except OSError as exc:
        return _LockRead.MALFORMED, None, f"unreadable: {exc}"
    if not raw.strip():
        # A zero-byte lock means a publisher died between O_EXCL and its body
        # write. That is damaged evidence, not an absent lock.
        return _LockRead.MALFORMED, None, "empty file (publisher died mid-write?)"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _LockRead.MALFORMED, None, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return _LockRead.MALFORMED, None, "top-level JSON is not an object"
    try:
        return _LockRead.PARSED, CommonGitLock.from_json(data), ""
    except (TypeError, ValueError) as exc:
        return _LockRead.MALFORMED, None, f"unusable lock record: {exc}"


def _read_lock(repo_root: Path) -> Optional[CommonGitLock]:
    """Parsed lock, or None when absent. Raises when malformed."""
    state, lock, reason = _read_state(repo_root)
    if state is _LockRead.MALFORMED:
        raise MalformedLockError(_get_common_git_lock_path(repo_root), reason)
    return lock


def _write_lock(lock: CommonGitLock) -> None:
    """Durably publish ``lock``."""
    path = _get_common_git_lock_path(Path(lock.repo_root))
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_payload(path, lock.to_json())


# ---------------------------------------------------------------------------
# fencing ledger
# ---------------------------------------------------------------------------

def _issue_generation(repo_root: Path, floor: int = 0) -> int:
    """Append one line to the ledger and return the generation it represents.

    O_APPEND writes below PIPE_BUF are atomic on POSIX and are atomic appends on
    Windows, so concurrent winners cannot collide. Reading the file afterwards
    yields the highest issued value. A crash can leave a gap in the sequence,
    which is harmless; a generation is never reused or reordered.

    ``floor`` raises the ledger to at least the generation currently published.
    That keeps the sequence monotonic even if the ledger is truncated or the
    published record was written by an older writer, so a fencing token is
    never issued below a generation that has already been handed out.
    """
    path = _ledger_path(repo_root)
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
# ABA-safe transition primitives
# ---------------------------------------------------------------------------

def _claim_by_rename(repo_root: Path, tag: str, expect) -> tuple[bool, Optional[bytes]]:
    """Atomically move the published lock onto a private tombstone.

    ``os.replace`` is the linearization point of every ownership transition in
    this module. Afterwards the caller owns *exactly* the bytes that were at the
    published path; nobody else can write there because the path is gone.

    ``expect`` receives the bytes actually moved and returns True when they are
    the generation the caller is entitled to act on. When it returns False the
    bytes are restored to the published path, because they belong to someone
    else and must not be destroyed.

    On success the caller owns the returned tombstone path and must unlink it.
    """
    path = _get_common_git_lock_path(repo_root)
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
    # Not ours: put the bytes straight back. A concurrent acquirer may briefly
    # observe the path missing, but the evidence is never destroyed.
    try:
        os.replace(tomb, path)
    except OSError:
        pass
    return False, None


def _lock_matches(lock_id: str, owner_token: str, generation: int):
    """Build a predicate: are these bytes the exact generation the caller owns?"""
    def _check(raw: bytes) -> bool:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(data, dict):
            return False
        return (
            data.get("lock_id") == lock_id
            and data.get("owner_token") == owner_token
            and int(data.get("generation", -1) or 0) == int(generation)
        )
    return _check


# ---------------------------------------------------------------------------
# liveness / reclaim decision
# ---------------------------------------------------------------------------

def _remove_lock(repo_root: Path) -> None:
    """Unconditional removal. Internal: callers must have proved ownership."""
    try:
        _get_common_git_lock_path(repo_root).unlink(missing_ok=True)
    except OSError:
        pass


def _is_lock_holder_alive(lock: CommonGitLock) -> bool:
    """Fail-closed compatibility wrapper.

    Returns False only for a *proven* dead holder. ``UNKNOWN`` returns True so
    that a caller still using this boolean cannot mistake uncertainty for
    permission to steal. New code should use :func:`holder_liveness`.
    """
    return not holder_liveness(lock).reclaimable


def holder_liveness(lock: CommonGitLock) -> process_identity.LivenessResult:
    """Tri-state liveness of a published holder."""
    return process_identity.probe_liveness(lock.holder_pid)


def owner_identity_matches(lock: CommonGitLock) -> bool:
    """Is the recorded holder still the very process that published this?

    A PID alone proves nothing because PIDs are recycled. When the recorded start
    identity is present it must equal the live process's, otherwise the PID now
    belongs to somebody else and the lock is a genuine leftover.
    """
    observed = holder_liveness(lock)
    if not observed.alive:
        return False
    if not lock.holder_start_identity:
        # No identity was recorded, so we cannot distinguish "same process" from
        # "recycled PID". Refuse to claim a match.
        return False
    return process_identity.same_process(
        lock.holder_pid, lock.holder_start_identity, observed
    )


def reclaim_decision(lock: CommonGitLock) -> tuple[bool, str]:
    """May this published lock be reclaimed automatically? Returns (may, why).

    Only proof of death authorises a steal:

    * recorded status is not ``active`` (explicit release);
    * the holder is proven ``DEAD``;
    * the PID is alive but its process start identity differs, i.e. the PID was
      recycled and this record belongs to a process that no longer exists.

    An expired lease is **not** proof. Neither is UNKNOWN liveness.
    """
    if lock.status != "active":
        return True, f"recorded status is {lock.status!r}"

    observed = holder_liveness(lock)
    if observed.reclaimable:
        return True, f"holder proven dead ({observed.detail})"

    if observed.alive:
        if lock.holder_start_identity and observed.start_identity:
            if lock.holder_start_identity != observed.start_identity:
                return True, (
                    f"pid {lock.holder_pid} recycled: recorded start "
                    f"{lock.holder_start_identity} != live {observed.start_identity}"
                )
            return False, "holder is alive and is the same process"
        return False, (
            f"holder is alive but its process start identity could not be "
            f"confirmed; refusing to reclaim"
        )

    # UNKNOWN
    return False, (
        f"holder state UNKNOWN ({observed.detail}); a permission problem, "
        f"timeout or unreadable process record is not proof of death"
    )


# ---------------------------------------------------------------------------
# acquire / release / renew
# ---------------------------------------------------------------------------

def acquire_common_git_lock(
    repo_root: Path,
    operation: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> CommonGitLock:
    """Acquire the repository-global authority for shared Git metadata.

    Publication is atomic and exclusive over a COMPLETE record, so a competing
    acquirer never observes a half-written file. A published lock is reclaimed
    only when its owner is proven dead, so a permission problem, an API timeout
    or an unreadable process record can never authorise a steal.
    """
    repo_root = Path(repo_root).resolve()
    path = _get_common_git_lock_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    pid, start_identity = process_identity.current_process_identity()
    start_time = time.time()

    while True:
        state, existing, reason = _read_state(repo_root)
        if state is _LockRead.MALFORMED:
            raise MalformedLockError(path, reason)
        floor = existing.generation if (existing is not None) else 0
        generation = _issue_generation(repo_root, floor)

        candidate = CommonGitLock(
            repo_root=str(repo_root),
            operation=operation,
            generation=generation,
            holder_pid=pid,
            holder_ppid=os.getppid(),
            holder_cmdline=" ".join(sys.argv),
            holder_start_identity=start_identity or "",
            expires_at=_utc_in(timeout_seconds),
        )

        try:
            won = _publish_exclusive(path, candidate.to_json())
        except OSError as exc:
            raise RuntimeError(f"Failed to create common Git lock: {exc}") from exc
        if won:
            return candidate

        # Another acquirer won. Re-read and decide whether that lock may be
        # reclaimed, or refuse.
        state, existing, reason = _read_state(repo_root)
        if state is _LockRead.MALFORMED:
            raise MalformedLockError(path, reason)
        if state is _LockRead.ABSENT:
            time.sleep(_FRESH_PUBLISH_REREAD_DELAY_S)
            continue

        may_reclaim, why = reclaim_decision(existing)
        if may_reclaim:
            # ABA-safe reclaim: rename the exact generation we judged, then
            # verify the bytes we actually moved. If the lock changed under us
            # it is restored untouched and we reevaluate the new owner.
            claimed, tomb = _claim_by_rename(
                repo_root,
                "reclaim",
                _lock_matches(
                    existing.lock_id, existing.owner_token, existing.generation
                ),
            )
            if claimed and tomb is not None:
                try:
                    tomb.unlink()
                except OSError:
                    pass
            time.sleep(_FRESH_PUBLISH_REREAD_DELAY_S)
            continue

        waited = int(time.time() - start_time)
        if waited >= timeout_seconds:
            raise RuntimeError(
                f"Failed to acquire common Git lock after {timeout_seconds}s: "
                f"held by pid={existing.holder_pid} "
                f"(operation={existing.operation!r}, generation={existing.generation}, "
                f"acquired={existing.acquired_at}, expires={existing.expires_at}); "
                f"not reclaimable because {why}"
            )
        raise RuntimeError(
            f"Common Git lock held by pid={existing.holder_pid} "
            f"(operation={existing.operation!r}, generation={existing.generation}, "
            f"acquired={existing.acquired_at}, expires={existing.expires_at}); "
            f"not reclaimable because {why}. "
            f"Waited {waited}s, {int(timeout_seconds - waited)}s remaining."
        )


def _require_mine(
    current: Optional[CommonGitLock],
    owner_token: str,
    lock_id: Optional[str],
    action: str,
) -> CommonGitLock:
    """Exact-ownership check. Any mismatch fails closed."""
    if current is None:
        raise RuntimeError(f"cannot {action}: no common Git lock is published")
    if not owner_token:
        raise RuntimeError(
            f"cannot {action}: owner_token is mandatory; refusing token-optional release"
        )
    if not hmac_compare(current.owner_token, owner_token):
        raise RuntimeError(
            f"cannot {action}: owner token does not match the published owner "
            f"(generation={current.generation}); refusing"
        )
    if lock_id is not None and current.lock_id != lock_id:
        raise RuntimeError(
            f"cannot {action}: lock_id does not match the published owner "
            f"(generation={current.generation}); refusing"
        )
    return current


def hmac_compare(left: str, right: str) -> bool:
    """Constant-time comparison for capability tokens."""
    return hmac.compare_digest(str(left), str(right))


def release_common_git_lock(
    repo_root: Path,
    owner_token: str = "",
    lock_id: Optional[str] = None,
) -> bool:
    """Release the authority, and only with the exact owner token.

    The ``os.replace`` onto an owner-specific tombstone is the linearization
    point. After it the caller owns exactly the bytes it removed, and those
    bytes are verified against its own lock_id/token/generation before deletion.
    A previous owner that wakes up late therefore cannot delete its successor.
    """
    repo_root = Path(repo_root).resolve()
    current = _read_lock(repo_root)
    current = _require_mine(current, owner_token, lock_id, "release")

    claimed, tomb = _claim_by_rename(
        repo_root,
        "release",
        _lock_matches(current.lock_id, current.owner_token, current.generation),
    )
    if not claimed:
        # The published lock changed between our read and our claim.
        raise RuntimeError(
            f"cannot release: the published lock changed while releasing "
            f"(expected generation={current.generation}); refusing"
        )
    if tomb is not None:
        try:
            tomb.unlink()
        except OSError:
            pass
    return True


def renew_common_git_lock(
    repo_root: Path,
    owner_token: str,
    lock_id: Optional[str] = None,
    ttl_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> CommonGitLock:
    """Extend the lease of a still-owned lock.

    Renewal requires the exact owner token, and re-verifies that the caller's own
    process identity still matches the published record, so a process that has
    lost the lock cannot resurrect it. A previous generation cannot renew a
    successor: the token and generation must both still match.
    """
    repo_root = Path(repo_root).resolve()
    current = _require_mine(_read_lock(repo_root), owner_token, lock_id, "renew")

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

    updated = CommonGitLock.from_json(current.to_json())
    updated.expires_at = _utc_in(ttl_seconds)
    # Renewal must not race a successor: re-check and rewrite only if the
    # published generation is still ours.
    latest = _read_lock(repo_root)
    if latest is None or latest.generation != current.generation or not hmac_compare(
        latest.owner_token, owner_token
    ):
        raise RuntimeError(
            f"cannot renew: generation {current.generation} was superseded "
            f"before renewal completed; refusing"
        )
    _write_lock(updated)
    return updated


@contextmanager
def common_git_lock(
    repo_root: Path,
    operation: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
):
    """Context manager holding the repository-global authority.

    Usage:
        with common_git_lock(repo_root, "git fetch"):
            subprocess.run(["git", "fetch"])
    """
    lock = acquire_common_git_lock(repo_root, operation, timeout_seconds)
    try:
        yield lock
    finally:
        try:
            release_common_git_lock(Path(lock.repo_root), lock.owner_token, lock.lock_id)
        except RuntimeError:
            # The lock was reclaimed or superseded; do not mask the body's
            # outcome with a release error.
            pass


def get_lock_status(repo_root: Path) -> dict:
    """Current authority status, with the evidence behind any reclaim verdict."""
    state, lock, reason = _read_state(repo_root)
    if state is _LockRead.ABSENT:
        return {"status": "unlocked", "lock_id": None}
    if state is _LockRead.MALFORMED:
        return {
            "status": "BLOCKED_MALFORMED_LOCK",
            "lock_id": None,
            "detail": reason,
            "path": str(_get_common_git_lock_path(repo_root)),
        }

    observed = holder_liveness(lock)
    may_reclaim, why = reclaim_decision(lock)
    expired = lock.is_expired()

    if lock.status != "active":
        status = lock.status
    elif may_reclaim:
        status = "stale"
    elif expired:
        # Owned, but renewal may be unhealthy: surfaced, never auto-stolen.
        status = "active_expired_owner_alive"
    else:
        status = "active"

    return {
        "status": status,
        "lock_id": lock.lock_id,
        "generation": lock.generation,
        "holder_pid": lock.holder_pid,
        "holder_start_identity": lock.holder_start_identity,
        "holder_liveness": observed.state.value,
        "holder_liveness_detail": observed.detail,
        "reclaimable": may_reclaim,
        "reclaim_rationale": why,
        "operation": lock.operation,
        "acquired_at": lock.acquired_at,
        "expires_at": lock.expires_at,
        "expired": expired,
        "repo_root": lock.repo_root,
    }


def recover_malformed_lock(repo_root: Path, operator: str, reason: str) -> dict:
    """Operator-only removal of malformed ownership evidence.

    Never called by acquisition. Records a SHA-256 of the bytes removed, the
    recovery timestamp and the stated operator intent, so the destruction is
    auditable.
    """
    repo_root = Path(repo_root).resolve()
    path = _get_common_git_lock_path(repo_root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {"recovered": False, "detail": "no lock present"}
    digest = hashlib.sha256(raw).hexdigest()
    record = {
        "recovered": True,
        "path": str(path),
        "removed_sha256": digest,
        "removed_bytes": len(raw),
        "recovered_at": _utc_now(),
        "operator": operator,
        "reason": reason,
    }
    claimed, tomb = _claim_by_rename(repo_root, "recover", lambda _raw: True)
    if claimed and tomb is not None:
        try:
            tomb.unlink()
        except OSError:
            pass
    else:
        record["recovered"] = False
        record["detail"] = "lock changed or vanished during recovery; nothing removed"
    return record
