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
import errno
import hashlib
import hmac
import json
import os
import sys
import threading
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

# Windows denies ``os.replace`` on a file another thread holds open for reading
# (WinError 32, no FILE_SHARE_DELETE). A concurrent acquirer reads the published
# record while deciding whether it may reclaim, so a legitimate claim-by-rename
# can lose that race. The rename is therefore retried for a bounded interval.
# These are retry budgets for one rename, not a wait on another party.
_CLAIM_RENAME_RETRY_S = 2.0
_CLAIM_RENAME_RETRY_DELAY_S = 0.005
_LOCK_FILENAME = lock_paths.COMMON_GIT_LOCK_FILENAME
_LEDGER_FILENAME = "common_git_lock.generations"
_GENERATION_CLAIM_FILENAME = "common_git_lock.generation.claim"
_TRANSITION_CLAIM_FILENAME = "common_git_lock.transition.claim"
_LOCAL_CLAIM_LOCKS: dict[str, threading.Lock] = {}
_LOCAL_CLAIM_LOCKS_GUARD = threading.Lock()


class CommonGitLockReleaseError(RuntimeError):
    """The body completed, but verified release of its authority failed."""


class GenerationLedgerError(RuntimeError):
    """The durable fencing ledger is missing, corrupt, or unreadable."""


class UnsupportedFilesystemError(RuntimeError):
    """The common-Git filesystem cannot provide required atomic publication."""


@contextmanager
def _cross_process_file_claim(repo_root: Path, filename: str, timeout_s: float = 30.0):
    """Serialize one common-Git operation with an OS-released file lock.

    The lock file is persistent metadata in the canonical common-Git namespace;
    its existence conveys no ownership. POSIX uses ``flock`` and Windows uses
    a one-byte ``msvcrt.locking`` region. The kernel releases either lock after
    process death, so no PID-based stale-claim recovery can race a successor.
    """
    directory = lock_paths.agent_locks_dir(Path(repo_root))
    with _cross_process_file_claim_at(directory, filename, timeout_s):
        yield


@contextmanager
def _cross_process_file_claim_at(directory: Path, filename: str, timeout_s: float = 30.0):
    """The file-claim implementation for an already resolved common directory."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    key = os.path.normcase(str(path.resolve()))
    with _LOCAL_CLAIM_LOCKS_GUARD:
        local_lock = _LOCAL_CLAIM_LOCKS.setdefault(key, threading.Lock())
    timeout_s = max(0.0, float(timeout_s))
    if not local_lock.acquire(timeout=timeout_s):
        raise TimeoutError(f"timed out waiting for in-process common-Git claim {path}")
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
        deadline = time.monotonic() + timeout_s
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt

                while True:
                    os.lseek(fd, 0, os.SEEK_SET)
                    try:
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        acquired = True
                        break
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EDEADLK, errno.EAGAIN):
                            raise
                        if time.monotonic() >= deadline:
                            raise TimeoutError(
                                f"timed out waiting for common-Git claim {path}"
                            ) from exc
                        time.sleep(0.01)
            else:
                import fcntl

                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                        break
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EAGAIN):
                            raise
                        if time.monotonic() >= deadline:
                            raise TimeoutError(
                                f"timed out waiting for common-Git claim {path}"
                            ) from exc
                        time.sleep(0.01)
            yield
        finally:
            if acquired:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    finally:
        local_lock.release()


def _generation_claim(repo_root: Path):
    return _cross_process_file_claim(repo_root, _GENERATION_CLAIM_FILENAME)


def _transition_claim(repo_root: Path):
    return _cross_process_file_claim(repo_root, _TRANSITION_CLAIM_FILENAME)


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


def _generation_authority_path(repo_root: Path) -> Path:
    return _ledger_path(repo_root).with_name(f"{_LEDGER_FILENAME}.highwater")


def _generation_marker_path(repo_root: Path) -> Path:
    return _ledger_path(repo_root).with_name(f"{_LEDGER_FILENAME}.initialized")


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


def _fsync_dir_required(directory: Path) -> None:
    """Require directory-entry durability for fencing authority updates."""
    if os.name != "nt":
        fd = os.open(str(directory), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    flush = kernel32.FlushFileBuffers
    flush.argtypes = [wintypes.HANDLE]
    flush.restype = wintypes.BOOL
    close = kernel32.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create_file(
        str(directory), 0x80000000 | 0x40000000,
        0x00000001 | 0x00000002 | 0x00000004,
        None, 3, 0x02000000, None,
    )
    invalid = wintypes.HANDLE(-1).value
    if handle == invalid:
        raise OSError(ctypes.get_last_error(), "cannot open common-Git directory for flush")
    try:
        if not flush(handle):
            raise OSError(ctypes.get_last_error(), "cannot flush common-Git directory")
    finally:
        if not close(handle):
            raise OSError(ctypes.get_last_error(), "cannot close common-Git directory handle")


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
    _atomic_replace(tmp, path)
    _fsync_dir_required(path.parent)


def _atomic_replace(source: Path, destination: Path) -> None:
    """Replace a file atomically and request write-through durability on NT."""
    if os.name != "nt":
        os.replace(source, destination)
        return
    import ctypes
    from ctypes import wintypes

    move_file = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move_file.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move_file.restype = wintypes.BOOL
    # MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH
    if not move_file(str(source), str(destination), 0x1 | 0x8):
        error = ctypes.get_last_error()
        raise OSError(error, "write-through atomic replacement failed", str(destination))


def _publish_exclusive_bytes(path: Path, data: bytes) -> bool:
    """Atomically publish complete bytes without an empty-file visibility gap."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            view = memoryview(data)
            while view:
                count = stream.write(view)
                if count is None or count <= 0:
                    raise OSError("atomic publication made no progress")
                view = view[count:]
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(str(tmp), str(path))
        except FileExistsError:
            return False
        except NotImplementedError as exc:
            raise UnsupportedFilesystemError(
                f"UNSUPPORTED_FILESYSTEM: atomic no-replace link unavailable for {path}"
            ) from exc
        except OSError as exc:
            if exc.errno in (errno.EOPNOTSUPP, errno.ENOTSUP) or getattr(
                exc, "winerror", None
            ) in (1, 50):
                raise UnsupportedFilesystemError(
                    f"UNSUPPORTED_FILESYSTEM: atomic no-replace link unavailable for {path}"
                ) from exc
            raise
        _fsync_dir_required(path.parent)
        return True
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _publish_exclusive(path: Path, payload: dict) -> bool:
    """Publish ``payload`` at ``path`` atomically and exclusively.

    Returns True when this caller won ownership, False when someone else
    already published there.

    Creating the destination with ``O_CREAT|O_EXCL`` and filling it afterwards
    leaves a window in which a concurrent reader observes a ZERO-BYTE file,
    which is indistinguishable from corruption and would abort every competing
    acquirer. Instead the complete record is written and fsynced to a unique
    temp file, then hard-linked into place: link creation is atomic and fails
    if the destination exists. The published path is therefore never seen empty
    or half-written. Filesystems without atomic no-replace hard-link support
    fail closed; no O_EXCL reservation fallback is used.
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
    except NotImplementedError as exc:
        raise UnsupportedFilesystemError(
            f"UNSUPPORTED_FILESYSTEM: atomic no-replace link unavailable for {path}"
        ) from exc
    except OSError as exc:
        if exc.errno in (errno.EOPNOTSUPP, errno.ENOTSUP) or getattr(
            exc, "winerror", None
        ) in (1, 50):
            raise UnsupportedFilesystemError(
                f"UNSUPPORTED_FILESYSTEM: atomic no-replace link unavailable for {path}"
            ) from exc
        raise
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    _fsync_dir_required(path.parent)
    return True


def _publish_exclusive_fallback(path: Path, payload: dict) -> bool:
    """Compatibility name; unsafe O_EXCL reservation is no longer supported."""
    raise UnsupportedFilesystemError(
        f"UNSUPPORTED_FILESYSTEM: no safe atomic exclusive publisher for {path}"
    )


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


def _write_lock_unlocked(lock: CommonGitLock) -> None:
    """Durably publish while the caller holds the transition claim."""
    path = _get_common_git_lock_path(Path(lock.repo_root))
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_payload(path, lock.to_json())


def _write_lock(lock: CommonGitLock) -> None:
    """Durably publish under repository-global transition serialization."""
    repo_root = Path(lock.repo_root).resolve()
    with _transition_claim(repo_root):
        _write_lock_unlocked(lock)


# ---------------------------------------------------------------------------
# fencing ledger
# ---------------------------------------------------------------------------

def _issue_generation(repo_root: Path, floor: int = 0) -> int:
    """Durably issue one unique, monotonic generation in allocation order.

    The OS file claim is independent of lock publication. A crash after this
    function returns may leave a gap, but no process can reuse that number.
    Existing malformed, truncated, unreadable, or nonmonotonic ledgers are
    never repaired by truncation or by ignoring bad rows.
    """
    repo_root = Path(repo_root).resolve()
    if type(floor) is not int or floor < 0:
        raise GenerationLedgerError("invalid generation floor")
    common_dir = lock_paths.resolve_git_common_dir(repo_root)
    directory = common_dir / lock_paths.AGENT_LOCKS_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _LEDGER_FILENAME
    with _cross_process_file_claim_at(directory, _GENERATION_CLAIM_FILENAME):
        highest = 0
        authority_path = directory / f"{_LEDGER_FILENAME}.highwater"
        authority_missing = False
        try:
            authority_raw = authority_path.read_bytes()
        except FileNotFoundError:
            authority_raw = b""
            authority_missing = True
        except OSError as exc:
            raise GenerationLedgerError(f"generation high-water unreadable: {exc}") from exc
        authority_high = 0
        if not authority_missing and not authority_raw:
            raise GenerationLedgerError("generation high-water authority is empty")
        if authority_raw:
            if not authority_raw.endswith(b"\n"):
                raise GenerationLedgerError("generation high-water is truncated")
            try:
                authority_lines = authority_raw.decode("utf-8").splitlines()
            except UnicodeError as exc:
                raise GenerationLedgerError("generation high-water is not UTF-8") from exc
            expected_header = (
                "common-git-generation-high-water/v1 "
                f"{common_dir}"
            )
            if not authority_lines or authority_lines[0] != expected_header:
                raise GenerationLedgerError("generation high-water authority is malformed")
            for line in authority_lines[1:]:
                if not line.isdecimal() or int(line) <= authority_high:
                    raise GenerationLedgerError(
                        "generation high-water is corrupt or nonmonotonic"
                    )
                authority_high = int(line)
        marker_path = directory / f"{_LEDGER_FILENAME}.initialized"
        try:
            marker = marker_path.read_bytes()
        except FileNotFoundError:
            marker = None
        except OSError as exc:
            raise GenerationLedgerError(f"generation marker unreadable: {exc}") from exc
        expected_marker = b"common-git-generation-ledger/v1\n"
        if marker is not None and marker != expected_marker:
            raise GenerationLedgerError("generation initialization marker is corrupt")
        ledger_missing = False
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            ledger_missing = True
            if not authority_missing:
                raise GenerationLedgerError(
                    "generation ledger missing while high-water authority exists"
                )
            if marker is not None:
                raise GenerationLedgerError("initialized generation ledger is missing")
            raw = b""
        except OSError as exc:
            raise GenerationLedgerError(f"cannot read generation ledger: {exc}") from exc
        if not ledger_missing and not raw:
            raise GenerationLedgerError("generation ledger is empty")
        if raw:
            if not raw.endswith(b"\n"):
                raise GenerationLedgerError("generation ledger is truncated")
            try:
                lines = raw.decode("ascii").splitlines()
            except UnicodeError as exc:
                raise GenerationLedgerError("generation ledger is not ASCII") from exc
            for line in lines:
                if not line.isdecimal() or int(line) <= highest:
                    raise GenerationLedgerError("generation ledger is corrupt or nonmonotonic")
                highest = int(line)
        if highest < authority_high:
            raise GenerationLedgerError(
                "generation ledger is below independent high-water authority"
            )
        nxt = max(highest, floor) + 1
        if marker is None:
            if not _publish_exclusive_bytes(marker_path, expected_marker):
                try:
                    marker = marker_path.read_bytes()
                except OSError as exc:
                    raise GenerationLedgerError(
                        f"generation marker publication could not be verified: {exc}"
                    ) from exc
                if marker != expected_marker:
                    raise GenerationLedgerError("generation marker conflicts with authority")
        fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        try:
            payload = f"{nxt}\n".encode("ascii")
            written = 0
            while written < len(payload):
                count = os.write(fd, payload[written:])
                if count <= 0:
                    raise OSError("generation ledger append made no progress")
                written += count
            os.fsync(fd)
        except OSError as exc:
            raise GenerationLedgerError(f"generation ledger publication failed: {exc}") from exc
        finally:
            os.close(fd)
        if ledger_missing:
            _fsync_dir_required(path.parent)
        authority_header = (
            "common-git-generation-high-water/v1 "
            f"{common_dir}\n"
        ).encode("utf-8")
        authority_fd = os.open(
            str(authority_path), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600
        )
        try:
            authority_payload = (
                authority_header if authority_missing else b""
            ) + f"{nxt}\n".encode("ascii")
            authority_written = 0
            while authority_written < len(authority_payload):
                count = os.write(authority_fd, authority_payload[authority_written:])
                if count <= 0:
                    raise OSError("generation high-water append made no progress")
                authority_written += count
            os.fsync(authority_fd)
        except OSError as exc:
            raise GenerationLedgerError(
                f"generation high-water publication failed: {exc}"
            ) from exc
        finally:
            os.close(authority_fd)
        if authority_missing:
            _fsync_dir_required(authority_path.parent)
        return nxt


# ---------------------------------------------------------------------------
# ABA-safe transition primitives
# ---------------------------------------------------------------------------

def _claim_by_rename_unlocked(repo_root: Path, tag: str, expect):
    """Atomically move the published lock onto a private tombstone.

    ``os.replace`` is the claim linearization point. Afterwards the caller owns
    *exactly* the bytes that were at the
    published path; nobody else can write there because the path is gone.

    ``expect`` receives the bytes actually moved and returns True when they are
    the generation the caller is entitled to act on. When it returns False the
    bytes are restored only through exclusive no-replace publication; a successor
    already at the destination is never overwritten.

    On success the caller owns the returned tombstone path and must unlink it.

    Returns ``(claimed, tombstone)``. ``(False, None)`` means the claim could not
    be performed or verified -- callers must NOT read that as "somebody stole
    the lock", because on Windows the rename is denied (WinError 32) whenever a
    concurrent reader holds the published file open without FILE_SHARE_DELETE.
    That is a transient condition, not evidence of a successor, so it is retried
    for a bounded interval before giving up.
    """
    path = _get_common_git_lock_path(repo_root)
    deadline = time.time() + _CLAIM_RENAME_RETRY_S
    while True:
        tomb = path.with_name(
            f"{path.name}.{tag}.{uuid.uuid4().hex}.tombstone")
        try:
            os.replace(path, tomb)
        except OSError:
            # A concurrent reader can hold the published record open on
            # Windows. Give it a bounded moment to finish and retry; only a
            # persistent failure means the claim genuinely did not happen.
            if time.time() < deadline and path.exists():
                time.sleep(_CLAIM_RENAME_RETRY_DELAY_S)
                continue
            return False, None
        _fsync_dir_required(path.parent)
        try:
            moved = tomb.read_bytes()
        except OSError:
            moved = b""
        if expect(moved):
            return True, tomb
        # Not ours: put the bytes back ONLY while the published path is still
        # free. A concurrent acquirer may have published into the claim window;
        # replacing that successor would destroy a live owner's record, which is
        # exactly the evidence loss this module exists to prevent. When the path
        # is occupied the tombstone is kept as the preserved evidence.
        if path.exists():
            # Hand the tombstone back: the displaced evidence stays reachable by
            # the caller instead of being orphaned.
            return False, tomb
        # Restore with an atomic no-replace publication. A check followed by
        # os.replace could overwrite a successor published in between.
        try:
            os.link(str(tomb), str(path))
        except FileExistsError:
            return False, tomb
        except (OSError, NotImplementedError):
            # If exclusive restoration is unavailable, keep the tombstone as
            # recovery evidence and fail closed.
            return False, tomb
        try:
            tomb.unlink()
        except OSError:
            return False, tomb
        _fsync_dir_required(path.parent)
        return False, None


def _claim_by_rename(repo_root: Path, tag: str, expect):
    """Serialize a public claim operation in the common-Git namespace."""
    repo_root = Path(repo_root).resolve()
    with _transition_claim(repo_root):
        return _claim_by_rename_unlocked(repo_root, tag, expect)


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
        with _transition_claim(repo_root):
            state, existing, reason = _read_state(repo_root)
            if state is _LockRead.MALFORMED:
                raise MalformedLockError(path, reason)
            if state is _LockRead.ABSENT:
                generation = _issue_generation(repo_root)
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
                state, existing, reason = _read_state(repo_root)
                if state is _LockRead.MALFORMED:
                    raise MalformedLockError(path, reason)
                if state is _LockRead.ABSENT:
                    continue

            may_reclaim, why = reclaim_decision(existing)
            if may_reclaim:
                claimed, tomb = _claim_by_rename_unlocked(
                    repo_root,
                    "reclaim",
                    _lock_matches(existing.lock_id, existing.owner_token, existing.generation),
                )
                if claimed and tomb is not None:
                    try:
                        tomb.unlink()
                        _fsync_dir_required(tomb.parent)
                    except OSError:
                        pass
                time.sleep(_FRESH_PUBLISH_REREAD_DELAY_S)
                continue

            waited = int(time.time() - start_time)
            message = (
                f"held by pid={existing.holder_pid} (operation={existing.operation!r}, "
                f"generation={existing.generation}, acquired={existing.acquired_at}, "
                f"expires={existing.expires_at}); not reclaimable because {why}"
            )
            if waited >= timeout_seconds:
                raise RuntimeError(
                    f"Failed to acquire common Git lock after {timeout_seconds}s: {message}"
                )
            raise RuntimeError(
                f"Common Git lock {message}. Waited {waited}s, "
                f"{int(timeout_seconds - waited)}s remaining."
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
    with _transition_claim(repo_root):
        current = _read_lock(repo_root)
        current = _require_mine(current, owner_token, lock_id, "release")

        claimed, tomb = _claim_by_rename_unlocked(
            repo_root,
            "release",
            _lock_matches(current.lock_id, current.owner_token, current.generation),
        )
        if not claimed:
            try:
                latest = _read_lock(repo_root)
            except Exception:
                latest = None
            unchanged = (
                latest is not None
                and latest.lock_id == current.lock_id
                and latest.owner_token == current.owner_token
                and latest.generation == current.generation
            )
            if unchanged:
                raise RuntimeError(
                    f"cannot release: the published lock could not be claimed "
                    f"(rename persistently denied; generation={current.generation} "
                    f"is unchanged); refusing"
                )
            raise RuntimeError(
                f"cannot release: the published lock changed while releasing "
                f"(expected generation={current.generation}); refusing"
            )
        if tomb is not None:
            try:
                tomb.unlink()
                _fsync_dir_required(tomb.parent)
            except OSError as exc:
                raise RuntimeError(f"release tombstone retained at {tomb}: {exc}") from exc
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
    with _transition_claim(repo_root):
        current = _require_mine(_read_lock(repo_root), owner_token, lock_id, "renew")
        pid, start_identity = process_identity.current_process_identity()
        if (
            current.holder_pid != pid
            or not current.holder_start_identity
            or not start_identity
            or current.holder_start_identity != start_identity
        ):
            raise RuntimeError(
                "cannot renew: exact caller process identity does not match "
                f"published owner (published pid={current.holder_pid}, caller pid={pid})"
            )
        updated = CommonGitLock.from_json(current.to_json())
        updated.expires_at = _utc_in(ttl_seconds)
        latest = _read_lock(repo_root)
        if (
            latest is None
            or latest.lock_id != current.lock_id
            or latest.generation != current.generation
            or not hmac_compare(latest.owner_token, owner_token)
            or latest.holder_pid != pid
            or latest.holder_start_identity != start_identity
        ):
            raise RuntimeError(
                f"cannot renew: generation {current.generation} was superseded "
                "or process identity changed; refusing"
            )
        _write_lock_unlocked(updated)
        published = _read_lock(repo_root)
        if (
            published is None
            or published.lock_id != current.lock_id
            or published.generation != current.generation
            or not hmac_compare(published.owner_token, owner_token)
            or published.expires_at != updated.expires_at
        ):
            raise RuntimeError("cannot renew: exact owner publication was not verified")
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
    except BaseException as body_error:
        try:
            release_common_git_lock(Path(lock.repo_root), lock.owner_token, lock.lock_id)
        except Exception as release_error:
            # Keep the original body exception as the primary error while
            # attaching the failed authority release for operators/callers.
            try:
                setattr(body_error, "lock_release_error", release_error)
            except Exception:
                pass
            if hasattr(body_error, "add_note"):
                body_error.add_note(f"common Git lock release also failed: {release_error!r}")
        raise
    else:
        try:
            release_common_git_lock(Path(lock.repo_root), lock.owner_token, lock.lock_id)
        except Exception as release_error:
            raise CommonGitLockReleaseError(
                "operation body completed, but common Git authority release "
                "was not verified; success must not be claimed"
            ) from release_error


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
    if not isinstance(operator, str) or not operator.strip():
        raise ValueError("operator identity is required for malformed-lock recovery")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason is required for malformed-lock recovery")
    repo_root = Path(repo_root).resolve()
    path = _get_common_git_lock_path(repo_root)
    with _transition_claim(repo_root):
        try:
            audited_raw = path.read_bytes()
        except FileNotFoundError:
            return {"recovered": False, "detail": "no lock present"}
        state, _parsed, detail = _read_state(repo_root)
        if state is not _LockRead.MALFORMED:
            return {
                "recovered": False,
                "detail": "lock is absent or parseable; malformed recovery refused",
            }
        digest = hashlib.sha256(audited_raw).hexdigest()
        audit_dir = lock_paths.agent_locks_dir(repo_root) / "common_git_lock_recovery"
        audit_dir.mkdir(parents=True, exist_ok=True)
        _fsync_dir_required(audit_dir.parent)
        evidence_path = audit_dir / f"lock-{digest}.raw"
        if not _publish_exclusive_bytes(evidence_path, audited_raw):
            if evidence_path.read_bytes() != audited_raw:
                raise RuntimeError("recovery evidence path contains different bytes")
        receipt_path = audit_dir / f"lock-{digest}.json"
        record = {
            "schema": "common-git-lock-recovery/v1",
            "status": "INTENT",
            "path": str(path),
            "audited_sha256": digest,
            "removed_sha256": digest,
            "audited_bytes": len(audited_raw),
            "removed_bytes": len(audited_raw),
            "evidence_path": str(evidence_path),
            "operator": operator.strip(),
            "reason": reason.strip(),
            "detail": detail,
            "recovered_at": _utc_now(),
        }
        _write_payload(receipt_path, record)
        _fsync_dir_required(audit_dir)
        claimed, tomb = _claim_by_rename_unlocked(
            repo_root, "recover", lambda moved: moved == audited_raw
        )
        if not claimed or tomb is None:
            record["status"] = "LOCKED_UNKNOWN"
            record["recovered"] = False
            _write_payload(receipt_path, record)
            _fsync_dir_required(audit_dir)
            return record
        try:
            if hashlib.sha256(tomb.read_bytes()).hexdigest() != digest:
                raise RuntimeError("claimed malformed-lock bytes differ from audited bytes")
            tomb.unlink()
            _fsync_dir_required(path.parent)
        except OSError:
            # Tombstone and exact evidence copy are both retained on failure.
            record["status"] = "LOCKED_UNKNOWN"
            record["recovered"] = False
            record["tombstone_path"] = str(tomb)
            _write_payload(receipt_path, record)
            _fsync_dir_required(audit_dir)
            raise
        record["status"] = "RECOVERED"
        record["recovered"] = True
        _write_payload(receipt_path, record)
        _fsync_dir_required(audit_dir)
        return record
