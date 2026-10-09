"""Machine-wide single-writer OS lock for governed CARLA mutations.

Authority is a Windows named mutex (kernel32), NOT a JSON file. The JSON
lease receipt is evidence; the mutex is the gate.

Namespace: tries ``Global\\<name>`` (machine-wide) and falls back to
``Local\\<name>`` (logon-session-wide) when Global creation is denied.
The effective namespace is recorded in every receipt.
"""
from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from typing import Optional


def _get_kernel32():
    """Lazily initialize kernel32 DLL on Windows; returns None on non-Windows."""
    if sys.platform != "win32":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        return kernel32
    except Exception:
        return None


def _require_windows():
    """Raise if not on Windows."""
    if sys.platform != "win32":
        raise RuntimeError("Windows-only operation attempted on non-Windows platform")


if sys.platform == "win32":
    _kernel32 = _get_kernel32()
    _CreateMutexW = _kernel32.CreateMutexW
    _CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    _CreateMutexW.restype = ctypes.c_void_p

    _WaitForSingleObject = _kernel32.WaitForSingleObject
    _WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    _WaitForSingleObject.restype = ctypes.c_uint32

    _ReleaseMutex = _kernel32.ReleaseMutex
    _ReleaseMutex.argtypes = [ctypes.c_void_p]
    _ReleaseMutex.restype = ctypes.c_bool

    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [ctypes.c_void_p]
    _CloseHandle.restype = ctypes.c_bool
else:
    # Non-Windows stubs
    _CreateMutexW = None
    _WaitForSingleObject = None
    _ReleaseMutex = None
    _CloseHandle = None

WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080
WAIT_TIMEOUT = 0x00000102
WAIT_FAILED = 0xFFFFFFFF

# Canonical cross-session name (Batch 17 arbitration). Previous name
# "CarlaGovernedOpsSingleWriter" remains accepted as an alias by acquiring
# both in canonical-first order; the canonical mutex is authority.
MUTEX_BASE_NAME = "CARLA_Mutating_Operation_Lock"
MUTEX_ALIAS_NAME = "CarlaGovernedOpsSingleWriter"


@dataclass
class MutexAcquisition:
    acquired: bool
    namespace: str  # "Global" or "Local"
    abandoned: bool = False
    handle: Optional[int] = None
    error: str = ""


class NamedMutex:
    """One acquisition of the machine-wide single-writer mutex."""

    def __init__(self, base_name: str = MUTEX_BASE_NAME) -> None:
        self._base = base_name
        self._handle: Optional[int] = None
        self._namespace = ""
        self._abandoned = False

    def acquire(self, timeout_ms: int = 0) -> MutexAcquisition:
        _require_windows()
        for ns in ("Global", "Local"):
            handle = _CreateMutexW(None, False, f"{ns}\\{self._base}")
            if not handle:
                continue
            rc = _WaitForSingleObject(handle, timeout_ms)
            if rc == WAIT_OBJECT_0:
                self._handle, self._namespace = handle, ns
                return MutexAcquisition(True, ns, False, handle)
            if rc == WAIT_ABANDONED:
                # Previous owner died holding the mutex. The OS transfers
                # ownership to us; the LEASE layer must still reconcile
                # (STALE_RECONCILIATION_REQUIRED) before any mutation.
                # NOTE (empirical, this host): a dead owner's mutex is
                # frequently observed as plain signaled (WAIT_OBJECT_0),
                # NOT abandoned. Crash detection therefore rests on the
                # LEASE heartbeat + PID/creation-time check, never on this
                # flag alone.
                self._handle, self._namespace, self._abandoned = handle, ns, True
                return MutexAcquisition(True, ns, True, handle)
            _CloseHandle(handle)
            if rc == WAIT_TIMEOUT:
                return MutexAcquisition(False, ns, False, None, "WAIT_TIMEOUT")
            return MutexAcquisition(False, ns, False, None, f"WAIT_FAILED rc={rc}")
        return MutexAcquisition(False, "", False, None, "mutex creation denied")

    @property
    def abandoned(self) -> bool:
        return self._abandoned

    def release(self) -> None:
        _require_windows()
        if self._handle:
            _ReleaseMutex(self._handle)
            _CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> "NamedMutex":
        res = self.acquire(timeout_ms=0)
        if not res.acquired:
            raise RuntimeError(f"single-writer mutex busy ({res.error})")
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def read_only_session() -> bool:
    return os.environ.get("READ_ONLY_SESSION", "").strip().lower() in (
        "1", "true", "yes",
    )
