"""Durable lease authority for the single-writer lock.

Location is machine-wide and session-independent:
``C:\\ProgramData\\carla-ops\\leases\\`` -- deliberately outside Temp,
agent scratch, worktrees, and session-local folders.

The OS mutex is authority for EXCLUSION; this store is authority for
provenance (who owns what, since when, heartbeat, terminal state).
Identity of a live owner is PID + CREATION_TIME (never PID alone).
"""
from __future__ import annotations

import ctypes
import datetime
import getpass
import hashlib
import json
import os
import socket
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_LEASE_DIR = r"C:\ProgramData\carla-ops\leases"
HEARTBEAT_TTL_S = 120

# Explicit in-process override (tests). Spawn children cannot inherit
# monkeypatches (module import is cached), so resolution ALWAYS consults
# the environment at call time; the override only wins when set in-process.
_DIR_OVERRIDE: Optional[str] = None


def set_dir_override(path: Optional[str]) -> None:
    global _DIR_OVERRIDE
    _DIR_OVERRIDE = path


def _lease_dir() -> Path:
    if _DIR_OVERRIDE:
        return Path(_DIR_OVERRIDE)
    return Path(os.environ.get("CARLA_OPS_LEASE_DIR", DEFAULT_LEASE_DIR))


def _current_file() -> Path:
    return _lease_dir() / "current_lease.json"


def _history_dir() -> Path:
    return _lease_dir() / "history"


# Legacy module-level paths (import-time snapshot; do NOT use internally --
# they go stale under spawn reimport and monkeypatching).
LEASE_DIR = Path(os.environ.get(
    "CARLA_OPS_LEASE_DIR", DEFAULT_LEASE_DIR))
CURRENT_LEASE_FILE = LEASE_DIR / "current_lease.json"
LEASE_HISTORY_DIR = LEASE_DIR / "history"

SCHEMA = "carla_ops_lease/v1"

VALID_STATES = (
    "ACQUIRED",
    "RUNNING",
    "RELEASING",
    "RELEASED",
    "STALE_RECONCILIATION_REQUIRED",
)


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace(
        "+00:00", "Z")


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32),
                ("dwHighDateTime", ctypes.c_uint32)]


_ct_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ct_kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool,
                                     ctypes.c_uint32]
_ct_kernel32.OpenProcess.restype = ctypes.c_void_p
_ct_kernel32.GetProcessTimes.argtypes = [ctypes.c_void_p,
                                         ctypes.POINTER(_FILETIME),
                                         ctypes.POINTER(_FILETIME),
                                         ctypes.POINTER(_FILETIME),
                                         ctypes.POINTER(_FILETIME)]
_ct_kernel32.GetProcessTimes.restype = ctypes.c_bool

_PROCESS_QUERY_LIMITED_INFORMATION = 0x00001000


def _filetime_to_us(ft: _FILETIME) -> int:
    value = (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    if not value:
        raise ValueError("zero FILETIME")
    return (value - 116444736000000000) // 10


def process_creation_time(pid: int) -> Optional[str]:
    """Creation time of a PID, None if the PID does not exist.

    PROCESS_QUERY_LIMITED_INFORMATION is required for GetProcessTimes;
    weaker rights fail and would yield a fake 1601 date, which defeats
    PID-reuse protection (all processes comparing equal). A zero FILETIME
    is never accepted. All four FILETIME out-params are real structs:
    NULL out-params crash this call on some hosts.
    """
    if not pid or pid < 0:
        return None
    try:
        h = _ct_kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return None
        try:
            ft_create, ft_exit, ft_kernel, ft_user = (
                _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME())
            ok = _ct_kernel32.GetProcessTimes(
                h, ctypes.byref(ft_create), ctypes.byref(ft_exit),
                ctypes.byref(ft_kernel), ctypes.byref(ft_user))
            if not ok:
                return None
            us = _filetime_to_us(ft_create)
            dt = datetime.datetime(1970, 1, 1) + datetime.timedelta(
                microseconds=us)
            return dt.replace(tzinfo=datetime.timezone.utc).isoformat().replace(
                "+00:00", "Z")
        finally:
            _ct_kernel32.CloseHandle(h)
    except Exception:
        return None


def owner_alive(root_pid: int, root_creation_time: str) -> bool:
    """True only if the SAME process (PID + creation time) still exists.

    Caveat: a dead process with an open handle held by the caller still
    exposes its original times and reads as alive. Callers must not hold
    the owner's handle (multiprocessing.Process.close() releases it).
    Combined with heartbeat TTL this is safe: a handle-held corpse has a
    frozen heartbeat and reconciles after expiry."""
    if not root_pid or not root_creation_time:
        return False
    actual = process_creation_time(root_pid)
    return actual == root_creation_time


def lease_owner_alive(lease: "Lease") -> bool:
    """Liveness against the executor when recorded, else the root PID."""
    if getattr(lease, "executor_pid", 0) and getattr(
            lease, "executor_creation_time", ""):
        return owner_alive(lease.executor_pid, lease.executor_creation_time)
    return owner_alive(lease.root_pid, lease.root_creation_time)


@dataclass
class Lease:
    schema: str = SCHEMA
    schema_version: int = 1
    run_id: str = ""
    session_id: str = ""
    operation: str = ""
    root_pid: int = 0
    root_creation_time: str = ""
    # True executor when the spawn launcher re-execs (proven: venv
    # python.exe respawns the base interpreter, so Popen.pid is a launcher
    # stub). Liveness is evaluated against the executor when present.
    executor_pid: int = 0
    executor_creation_time: str = ""
    engine_root: str = ""
    project_root: str = ""
    content_root: str = ""
    mutation_domains: List[str] = field(default_factory=list)
    operation_fingerprint: str = ""
    mutex_namespace: str = ""
    state: str = "ACQUIRED"
    start_utc: str = ""
    heartbeat_utc: str = ""
    end_utc: str = ""
    terminal_state: str = ""
    user: str = ""
    host: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Lease":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def _ensure_dirs() -> None:
    _lease_dir().mkdir(parents=True, exist_ok=True)
    _history_dir().mkdir(parents=True, exist_ok=True)


def read_current() -> Optional[Lease]:
    try:
        return Lease.from_dict(json.loads(_current_file().read_text(
            encoding="utf-8")))
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def _write_current(lease: Lease) -> None:
    _ensure_dirs()
    tmp = _current_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(lease.to_dict(), indent=2), encoding="utf-8")
    os.replace(tmp, _current_file())


def _archive(lease: Lease) -> None:
    _ensure_dirs()
    (_history_dir() / f"{lease.run_id}.json").write_text(
        json.dumps(lease.to_dict(), indent=2), encoding="utf-8")


def new_lease(operation: str, mutation_domains: List[str],
              fingerprint: str, mutex_namespace: str,
              engine_root: str = "", project_root: str = "",
              content_root: str = "", session_id: str = "") -> Lease:
    now = _utcnow()
    import ctypes

    pid = int(ctypes.windll.kernel32.GetCurrentProcessId())
    return Lease(
        run_id=f"{operation}_{uuid.uuid4().hex[:8]}",
        session_id=session_id or os.environ.get("CARLA_OPS_SESSION_ID", ""),
        operation=operation,
        root_pid=pid,
        root_creation_time=process_creation_time(pid) or "",
        engine_root=engine_root,
        project_root=project_root,
        content_root=content_root,
        mutation_domains=list(mutation_domains),
        operation_fingerprint=fingerprint,
        mutex_namespace=mutex_namespace,
        state="ACQUIRED",
        start_utc=now,
        heartbeat_utc=now,
        user=getpass.getuser(),
        host=socket.gethostname(),
    )


def rebind_mutation_root(lease: Lease, pid: int) -> Lease:
    """Bind the lease to the real mutation root.

    The mutation root does not exist until after Popen returns, so a lease
    acquired earlier can only be an admission lease owned by the supervisor.
    This rebinds ownership to the process that actually mutates, capturing
    its creation time so PID reuse is detectable.

    Contract V2: lease ownership binds to mutation_root_pid +
    mutation_root_creation_time, never to a bare PID and never to a
    previous run's identity.
    """
    lease.root_pid = int(pid)
    lease.root_creation_time = process_creation_time(int(pid)) or ""
    lease.executor_pid = 0
    lease.executor_creation_time = ""
    if not lease.root_creation_time:
        raise RuntimeError(
            "cannot bind lease: creation time unavailable for pid %s" % pid)
    return lease


def heartbeat(lease: Lease) -> Lease:
    """Refresh the heartbeat ONLY while the recorded owner is still valid.

    Historical defect: this only checked run_id equality and refreshed the
    timestamp, so a lease whose owner PID had died kept receiving fresh
    heartbeats and stayed RUNNING indefinitely. lease_owner_alive() already
    existed and would have caught exactly that, but was never called.

    It now fails closed: if the owner process is gone, or its creation time
    no longer matches (PID reuse), the lease is marked STALE and the
    timestamp is NOT advanced, so it stops representing valid coverage.
    """
    cur = read_current()
    if cur is None or cur.run_id != lease.run_id:
        return lease
    if lease.state in ("RELEASED", "RECONCILED"):
        return lease
    if not lease_owner_alive(lease):
        lease.state = "STALE"
        lease.terminal_state = lease.terminal_state or "OWNER_IDENTITY_LOST"
        _write_current(lease)
        _archive(lease)
        return lease
    lease.heartbeat_utc = _utcnow()
    if lease.state == "ACQUIRED":
        lease.state = "RUNNING"
    _write_current(lease)
    return lease


def heartbeat_age_s(lease: Lease) -> float:
    try:
        then = datetime.datetime.fromisoformat(
            lease.heartbeat_utc.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return max(0.0, (now - then).total_seconds())
    except Exception:
        return float("inf")


def is_stale(lease: Lease, ttl_s: int = HEARTBEAT_TTL_S) -> bool:
    """Stale = heartbeat expired AND owner process verifiably gone.

    A live owner with an old heartbeat is NOT stale (it may be mid-syscall);
    an ambiguous record is never auto-reclaimed -- it requires explicit
    reconcile(), which records the evidence either way.
    """
    if heartbeat_age_s(lease) < ttl_s:
        return False
    return not lease_owner_alive(lease)


def reconcile_stale() -> Dict[str, Any]:
    """Explicit, evidenced takeover of a dead owner's lease.

    Never called implicitly by the acquisition path. Returns a receipt
    describing what was found and done.
    """
    cur = read_current()
    if cur is None:
        return {"action": "none", "reason": "no current lease"}
    alive = lease_owner_alive(cur)
    age = heartbeat_age_s(cur)
    if alive:
        return {"action": "refused",
                "reason": "owner still alive; will not steal a live lease",
                "run_id": cur.run_id}
    if age < HEARTBEAT_TTL_S:
        cur.state = "STALE_RECONCILIATION_REQUIRED"
        _write_current(cur)
        return {"action": "flagged",
                "reason": "owner dead but heartbeat fresh; flagged for review",
                "run_id": cur.run_id}
    cur.state = "STALE_RECONCILIATION_REQUIRED"
    cur.end_utc = _utcnow()
    cur.terminal_state = "RECONCILED_OWNER_DEAD"
    _archive(cur)
    try:
        _current_file().unlink()
    except OSError:
        pass
    return {"action": "reconciled", "reason": "dead owner, expired heartbeat; lease archived and cleared",
            "run_id": cur.run_id}


def release(lease: Lease, terminal_state: str) -> Lease:
    lease.state = "RELEASING"
    _write_current(lease)
    lease.state = "RELEASED"
    lease.end_utc = _utcnow()
    lease.terminal_state = terminal_state
    _archive(lease)
    cur = read_current()
    if cur is not None and cur.run_id == lease.run_id:
        try:
            _current_file().unlink()
        except OSError:
            pass
    return lease


def fingerprint_operation(parts: Dict[str, Any]) -> str:
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
