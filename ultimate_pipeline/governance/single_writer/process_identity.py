"""Tri-state process liveness and OS-backed process-start identity.

This module is the single authority for "is this process still alive?" and
"is this the same process that was there before?" for the single-writer lock
layer. It replaces a boolean liveness probe that collapsed every kind of
uncertainty into DEAD.

Why the collapse mattered
-------------------------
The previous probe returned False for any of: PID absent, EPERM (process exists
but is owned by another user), tasklist timeout, access denied, malformed
output. The lock layer consumed that False as "safe to steal", so a *live*
owner's lock could be deleted on a momentary permission or scheduling problem.

Invariant enforced here
-----------------------
``UNKNOWN`` is never proof of death. Only ``DEAD`` is. A caller that reclaims on
anything other than ``DEAD`` is wrong.

Process-start identity
----------------------
A bare PID is not an identity: PIDs are recycled. ``start_identity`` is derived
from the OS (kernel ``/proc`` on Linux, the Win32 process API on Windows) and
never from wall-clock sampling, the PID, the command line, or a lease
timestamp. Two observations of the same live process always agree; a recycled
PID always differs.

The Linux path deliberately mirrors ``scripts/orch_core.py::process_creation_time``
rather than importing it: ``scripts/`` is not a package and no governance
module imports from it, so importing would add a fragile cross-layer dependency.
``tests/unit/test_single_writer_authority.py`` asserts the two agree on a live
PID, so the duplication is verified rather than assumed.
"""
from __future__ import annotations

import ctypes
import datetime
import enum
import os
import sys
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "LivenessState",
    "LivenessResult",
    "probe_liveness",
    "process_start_identity",
    "process_identity_key",
    "same_process",
    "current_process_identity",
    "PROCESS_QUERY_LIMITED_INFORMATION",
]


class LivenessState(str, enum.Enum):
    """Outcome of a liveness probe.

    ``UNKNOWN`` means the probe could not decide. It is deliberately distinct
    from ``DEAD`` and must never be treated as evidence that a lock is stale.
    """

    ALIVE = "ALIVE"
    DEAD = "DEAD"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class LivenessResult:
    """A liveness verdict plus the evidence that produced it."""

    state: LivenessState
    pid: int
    detail: str = ""
    start_identity: Optional[str] = None

    @property
    def reclaimable(self) -> bool:
        """True only when the process is *proven* gone.

        This is the sole predicate the lock layer may use to decide that
        reclaiming a lock is safe. UNKNOWN and ALIVE both return False.
        """
        return self.state is LivenessState.DEAD

    @property
    def alive(self) -> bool:
        return self.state is LivenessState.ALIVE

    @property
    def uncertain(self) -> bool:
        return self.state is LivenessState.UNKNOWN


# ---------------------------------------------------------------------------
# Windows direct process API
# ---------------------------------------------------------------------------
# No shell, no tasklist, no text parsing, no timeout. OpenProcess +
# GetProcessTimes is a direct API call that yields both liveness and the
# process creation instant.

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_PARAMETER = 87

# FILETIME (100 ns intervals since 1601-01-01) -> Unix epoch seconds
_FILETIME_UNIX_EPOCH_DELTA = 11644473600

if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _OpenProcess = _kernel32.OpenProcess
    _OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    _OpenProcess.restype = ctypes.c_void_p

    _GetProcessTimes = _kernel32.GetProcessTimes
    _GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64),
    ]
    _GetProcessTimes.restype = ctypes.c_int

    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [ctypes.c_void_p]
    _CloseHandle.restype = ctypes.c_int
else:
    _kernel32 = None
    _OpenProcess = None
    _GetProcessTimes = None
    _CloseHandle = None


def _file_time_to_iso(raw: int) -> str:
    """Convert a Win32 FILETIME to a UTC ISO-8601 instant."""
    epoch = (raw / 10_000_000.0) - _FILETIME_UNIX_EPOCH_DELTA
    return (
        datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _windows_start_identity(pid: int) -> Optional[str]:
    """Win32 process creation instant, or None if it cannot be read."""
    if _OpenProcess is None:  # pragma: no cover - non-Windows guard
        return None
    handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        # Access denied still means the process EXISTS. Report the instant as
        # unavailable but keep the caller from concluding the process is gone.
        return None
    creation = ctypes.c_uint64(0)
    exit_time = ctypes.c_uint64(0)
    kernel = ctypes.c_uint64(0)
    user = ctypes.c_uint64(0)
    try:
        ok = _GetProcessTimes(
            ctypes.c_void_p(handle),
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not ok:
            return None
        return _file_time_to_iso(creation.value)
    finally:
        _CloseHandle(ctypes.c_void_p(handle))


def _windows_liveness(pid: int) -> LivenessState:
    """Classify a PID using the Win32 process API. Never guesses DEAD."""
    if _OpenProcess is None:  # pragma: no cover - non-Windows guard
        return LivenessState.UNKNOWN
    handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        err = ctypes.get_last_error()
        if err == ERROR_INVALID_PARAMETER:
            # No such process.
            return LivenessState.DEAD
        if err == ERROR_ACCESS_DENIED:
            # The process exists and is simply not openable by this user.
            # Treating this as death is the defect this module exists to fix.
            return LivenessState.ALIVE
        return LivenessState.UNKNOWN
    _CloseHandle(ctypes.c_void_p(handle))
    return LivenessState.ALIVE


# ---------------------------------------------------------------------------
# Linux / POSIX
# ---------------------------------------------------------------------------

def _process_start_ticks(pid: int) -> Optional[int]:
    """Field 22 (``starttime``) of ``/proc/<pid>/stat``, in clock ticks.

    ``comm`` is parenthesised and may itself contain spaces and parentheses, so
    the record is split at the FINAL ``)``; the first token after that
    delimiter is field 3, which makes field 22 index 19.
    """
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except (FileNotFoundError, ProcessLookupError):
        return None
    except OSError:
        return None
    close = raw.rfind(")")
    if close < 0:
        return None
    fields = raw[close + 1:].split()
    if len(fields) < 20:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def _boot_epoch_seconds() -> Optional[float]:
    """Seconds since the Unix epoch at boot, from ``/proc/stat`` ``btime``."""
    try:
        with open("/proc/stat", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("btime "):
                    return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _clock_ticks() -> Optional[int]:
    try:
        hz = os.sysconf("SC_CLK_TCK")
    except (AttributeError, ValueError, OSError):
        return None
    if not hz or hz <= 0:
        return None
    return int(hz)


def _linux_start_identity(pid: int) -> Optional[str]:
    """Kernel-derived process start instant, or None when unobtainable."""
    if sys.platform == "darwin" and os.path.isdir("/proc") is False:
        # macOS has no /proc; the generic POSIX probe still answers liveness.
        return None
    ticks = _process_start_ticks(pid)
    if ticks is None:
        return None
    boot = _boot_epoch_seconds()
    hz = _clock_ticks()
    if boot is None or hz is None:
        return None
    epoch = boot + (ticks / float(hz))
    try:
        stamp = datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return stamp.isoformat().replace("+00:00", "Z")


def _posix_liveness(pid: int) -> LivenessState:
    """Classify a PID with ``os.kill(pid, 0)``, keeping EPERM distinct."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        # ESRCH: genuinely gone.
        return LivenessState.DEAD
    except PermissionError:
        # EPERM: the process EXISTS and is merely not signalable by us.
        return LivenessState.ALIVE
    except OSError:
        # Anything else (EINVAL, transient kernel errors) proves nothing.
        return LivenessState.UNKNOWN
    return LivenessState.ALIVE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_start_identity(pid: int) -> Optional[str]:
    """OS-backed process start instant, or None if it cannot be established.

    None means "unknown", never "dead". Callers must combine this with
    :func:`probe_liveness` rather than reading it as a death certificate.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if sys.platform == "win32":
        return _windows_start_identity(pid)
    return _linux_start_identity(pid)


def probe_liveness(pid: int) -> LivenessResult:
    """Probe a PID and classify it as ALIVE, DEAD or UNKNOWN."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return LivenessResult(
            LivenessState.UNKNOWN, 0, "pid is not an integer", None
        )
    if pid <= 0:
        # No valid PID was recorded. That is missing evidence, not proof of
        # death, so this is UNKNOWN and therefore non-reclaimable.
        return LivenessResult(
            LivenessState.UNKNOWN, pid, "non-positive pid: no valid owner identity", None
        )

    if sys.platform == "win32":
        state = _windows_liveness(pid)
        detail = {
            LivenessState.ALIVE: "OpenProcess succeeded",
            LivenessState.DEAD: "OpenProcess: ERROR_INVALID_PARAMETER",
            LivenessState.UNKNOWN: "OpenProcess failed with an unclassified error",
        }[state]
    else:
        state = _posix_liveness(pid)
        detail = {
            LivenessState.ALIVE: "os.kill(pid, 0) succeeded, or EPERM (exists, not signalable)",
            LivenessState.DEAD: "os.kill(pid, 0): ESRCH",
            LivenessState.UNKNOWN: "os.kill(pid, 0) raised an unclassified OSError",
        }[state]

    start = process_start_identity(pid) if state is not LivenessState.DEAD else None
    return LivenessResult(state, pid, detail, start)


def process_identity_key(pid: int, start_identity: Optional[str]) -> str:
    """Stable identity key, or "" when it cannot be established."""
    if not start_identity:
        return ""
    return f"{int(pid)}|{start_identity}"


def same_process(
    recorded_pid: int,
    recorded_start: Optional[str],
    observed: LivenessResult,
) -> bool:
    """True when ``observed`` is provably the very process that was recorded.

    A matching PID is not sufficient: PIDs are recycled. When both the recorded
    and observed start identities are available they must agree exactly.
    """
    if observed.state is not LivenessState.ALIVE:
        return False
    if int(recorded_pid) != int(observed.pid):
        return False
    if not recorded_start or not observed.start_identity:
        # Identity could not be proven either way. Do not claim a match.
        return False
    return recorded_start == observed.start_identity


def current_process_identity() -> tuple[int, Optional[str]]:
    """(pid, start identity) of the calling process."""
    pid = os.getpid()
    return pid, process_start_identity(pid)