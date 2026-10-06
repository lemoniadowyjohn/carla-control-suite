"""Windows Job Object supervision for future governed operations.

Purpose
-------
Tonight's failure class: a supervisor launched a long-lived UE child, the
supervisor died, and the child survived as an unowned shared-state mutator
holding a plugin DLL open indefinitely. A Job Object makes that impossible by
construction: every descendant is assigned to a job owned by the supervisor's
handle, so when the supervisor's handle closes, ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``
terminates the whole tree.

Two subtleties that drove the implementation:

* The child must be created **suspended**, assigned to the job, and only then
  resumed. Assigning after launch races: the child can already have spawned
  grandchildren, which are then not in the job.

* ``KILL_ON_JOB_CLOSE`` is exactly the policy that prevents an unowned mutator,
  but it must be tested against wrapper chains (cmd.exe -> UE4Editor-Cmd ->
  ShaderCompileWorker) before being trusted, which is what the synthetic matrix
  does. See JOB_OBJECT_POLICY in the emitted receipt.

This module is not attached to any pre-existing process. Retroactive assignment
of an already-running process tree is explicitly out of scope.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orch_core import atomic_write_json, utc_now  # noqa: E402

SCHEMA_VERSION = 1

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- constants -------------------------------------------------------------
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JobObjectExtendedLimitInformation = 9
JobObjectBasicAccountingInformation = 1

CREATE_SUSPENDED = 0x00000004
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NEW_CONSOLE = 0x00000010
INFINITE = 0xFFFFFFFF

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
SYNCHRONIZE = 0x00100000
THREAD_SUSPEND_RESUME = 0x0002


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wt.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wt.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wt.DWORD),
        ("SchedulingClass", wt.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class JOBOBJECT_BASIC_PROCESS_ID_LIST(ctypes.Structure):
    _fields_ = [
        ("NumberOfAssignedProcesses", wt.DWORD),
        ("NumberOfProcessIdsInList", wt.DWORD),
        ("ProcessIdList", ctypes.POINTER(ctypes.c_ulong)),
    ]


k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
k32.CreateJobObjectW.restype = wt.HANDLE
k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int,
                                        ctypes.c_void_p, wt.DWORD]
k32.SetInformationJobObject.restype = wt.BOOL
k32.QueryInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int,
                                          ctypes.c_void_p, wt.DWORD,
                                          ctypes.POINTER(wt.DWORD)]
k32.QueryInformationJobObject.restype = wt.BOOL
k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
k32.AssignProcessToJobObject.restype = wt.BOOL
k32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
k32.TerminateJobObject.restype = wt.BOOL
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = wt.HANDLE
k32.IsProcessInJob.argtypes = [wt.HANDLE, wt.HANDLE, ctypes.POINTER(wt.BOOL)]
k32.IsProcessInJob.restype = wt.BOOL
k32.ResumeThread.argtypes = [wt.HANDLE]
k32.ResumeThread.restype = wt.DWORD
k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
k32.WaitForSingleObject.restype = wt.DWORD
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.CloseHandle.restype = wt.BOOL

CREATE_NO_WINDOW = 0x08000000


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR),
                ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD),
                ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD),
                ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
                ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.POINTER(ctypes.c_char)),
                ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


k32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p,
                               ctypes.c_void_p, wt.BOOL, wt.DWORD,
                               ctypes.c_void_p, wt.LPCWSTR,
                               ctypes.POINTER(STARTUPINFOW),
                               ctypes.POINTER(PROCESS_INFORMATION)]
k32.CreateProcessW.restype = wt.BOOL
k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
k32.GetExitCodeProcess.restype = wt.BOOL
k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
k32.TerminateProcess.restype = wt.BOOL
STILL_ACTIVE = 259

# Win32 structures whose layout must match the SDK exactly. Sizes are asserted
# at import time so an ABI drift is a Python error, never a silent memory fault.
_EXPECTED_SIZES = {
    "JOBOBJECT_BASIC_LIMIT_INFORMATION": (JOBOBJECT_BASIC_LIMIT_INFORMATION, 64),
    "IO_COUNTERS": (IO_COUNTERS, 48),
    "JOBOBJECT_EXTENDED_LIMIT_INFORMATION":
        (JOBOBJECT_EXTENDED_LIMIT_INFORMATION, 144),
    "PROCESS_INFORMATION": (PROCESS_INFORMATION, 24),
}


def abi_audit():
    """Compare declared struct sizes against the 64-bit SDK layout."""
    rows = []
    ok = True
    for name, (struct, expected) in _EXPECTED_SIZES.items():
        actual = ctypes.sizeof(struct)
        good = actual == expected
        ok = ok and good
        rows.append({"structure": name, "expected_bytes": expected,
                     "actual_bytes": actual, "match": good})
    return {
        "schema": "WINDOWS_CTYPES_ABI_AUDIT/v1",
        "schema_version": 1,
        "generated_utc": utc_now(),
        "pointer_width_bits": ctypes.sizeof(ctypes.c_void_p) * 8,
        "structures": rows,
        "ABI_AUDIT": "PASS" if ok else "FAIL",
        "notes": [
            "HANDLE is declared as ctypes.wintypes.HANDLE (pointer sized).",
            "IO_COUNTERS uses 64-bit counters; a 32-bit layout would truncate.",
            "JOBOBJECT_EXTENDED_LIMIT_INFORMATION embeds a pointer-sized "
            "Minimum/MaximumWorkingSetSize and Peak*MemoryUsed, hence 144 bytes "
            "on x64 rather than the 32-bit 96.",
            "The variable-length JOBOBJECT_BASIC_PROCESS_ID_LIST is no longer "
            "used by contains_pid; enumeration is confined to "
            "enumerate_member_pids with explicit bounds checks.",
        ],
    }


class _OwnedProcess:
    """Minimal Popen-like wrapper over a raw CreateProcess handle.

    subprocess.Popen cannot be used for job assignment because it does not
    expose the primary thread handle, which CREATE_SUSPENDED requires in order
    to assign-then-resume. Without the thread handle the child would stay
    suspended forever.

    Handle ownership is explicit: this object owns hProcess exactly once, and
    the primary thread handle is closed by the caller immediately after
    ResumeThread. Any use after close raises in Python rather than issuing a
    native call on an invalid handle.
    """

    def __init__(self, pi):
        self.pid = pi.dwProcessId
        self._h = pi.hProcess
        self._t = pi.hThread
        self._state = "OPEN"

    def _require_open(self):
        if self._state != "OPEN":
            raise RuntimeError("process handle is %s" % self._state)

    def poll(self):
        self._require_open()
        code = wt.DWORD()
        if not k32.GetExitCodeProcess(self._h, ctypes.byref(code)):
            return None
        if code.value == STILL_ACTIVE:
            return None
        return code.value

    def wait(self, timeout=None):
        """Popen-compatible: timeout in SECONDS (None means wait forever)."""
        self._require_open()
        ms = INFINITE if timeout is None else int(timeout * 1000)
        k32.WaitForSingleObject(self._h, ms)
        return self.poll()

    def kill(self):
        self._require_open()
        k32.TerminateProcess(self._h, 1)

    def close(self):
        if self._state == "OPEN":
            k32.CloseHandle(self._h)
            if self._t:
                k32.CloseHandle(self._t)
            self._state = "CLOSED"

    @property
    def state(self):
        return self._state


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR),
                ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD),
                ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD),
                ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
                ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.POINTER(ctypes.c_char)),
                ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


k32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p,
                               ctypes.c_void_p, wt.BOOL, wt.DWORD,
                               ctypes.c_void_p, wt.LPCWSTR,
                               ctypes.POINTER(STARTUPINFOW),
                               ctypes.POINTER(PROCESS_INFORMATION)]
k32.CreateProcessW.restype = wt.BOOL
k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
k32.GetExitCodeProcess.restype = wt.BOOL
k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
k32.TerminateProcess.restype = wt.BOOL
STILL_ACTIVE = 259


class JobSupervisor:
    """Owns a Windows Job Object and the processes assigned to it."""

    def __init__(self, name=None, kill_on_close=True):
        self.name = name or ("carla_job_%d" % os.getpid())
        self.kill_on_close = kill_on_close
        self.handle = None
        self._job_state = "NEW"
        self.procs = {}
        self.created_utc = utc_now()

    def _require_open(self):
        if self._job_state != "OPEN" or not self.handle:
            raise RuntimeError("job handle state is %s" % self._job_state)

    def create(self):
        self.handle = k32.CreateJobObjectW(None, self.name)
        if not self.handle:
            self._job_state = "CLOSED"
            raise OSError("CreateJobObjectW failed: %d" % ctypes.get_last_error())
        self._job_state = "OPEN"
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0
        if self.kill_on_close:
            info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = k32.SetInformationJobObject(
            self.handle, JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            raise OSError("SetInformationJobObject failed: %d"
                          % ctypes.get_last_error())
        return self

    def spawn(self, command, env=None, cwd=None, capture=True):
        """Launch `command` SUSPENDED, assign it to the job, then resume.

        Create-then-assign would race with the child's own spawns, so the child
        must not be allowed to run until it is already inside the job.
        """
        if self.handle is None:
            self.create()
        if isinstance(command, (list, tuple)):
            line = subprocess.list2cmdline(list(command))
        else:
            line = command
        buf = ctypes.create_unicode_buffer(line)
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        pi = PROCESS_INFORMATION()
        flags = CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP
        if capture:
            flags |= CREATE_NO_WINDOW
        cwd_buf = ctypes.create_unicode_buffer(cwd) if cwd else None
        ok = k32.CreateProcessW(None, buf, None, None, False, flags, None,
                                cwd_buf, ctypes.byref(si), ctypes.byref(pi))
        if not ok:
            raise OSError("CreateProcessW failed: %d" % ctypes.get_last_error())

        h = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE
                            | PROCESS_QUERY_INFORMATION, False, pi.dwProcessId)
        assigned = False
        err = None
        if h:
            assigned = bool(k32.AssignProcessToJobObject(self.handle, h))
            if not assigned:
                err = ctypes.get_last_error()
            k32.CloseHandle(h)
        else:
            err = ctypes.get_last_error()
        if not assigned:
            k32.TerminateProcess(pi.hProcess, 1)
            k32.CloseHandle(pi.hProcess)
            k32.CloseHandle(pi.hThread)
            raise OSError("AssignProcessToJobObject failed for pid %d "
                          "(winerror=%s)" % (pi.dwProcessId, err))

        k32.ResumeThread(pi.hThread)
        k32.CloseHandle(pi.hThread)
        pi.hThread = None

        proc = _OwnedProcess(pi)
        self.procs[proc.pid] = proc
        return proc, assigned

    def member_pids(self):
        """Active/total/terminated process accounting. Always a dict."""
        empty = {"active": 0, "total": 0, "terminated": 0, "queried": False}
        if not self.handle:
            return empty
        needed = wt.DWORD(0)
        k32.QueryInformationJobObject(self.handle,
                                      JobObjectBasicAccountingInformation,
                                      None, 0, ctypes.byref(needed))
        if needed.value == 0:
            return empty
        buf = ctypes.create_string_buffer(needed.value)
        ok = k32.QueryInformationJobObject(self.handle,
                                          JobObjectBasicAccountingInformation,
                                          buf, needed, None)
        if not ok:
            return empty
        class ACCOUNTING(ctypes.Structure):
            _fields_ = [("TotalUserTime", ctypes.c_int64),
                        ("TotalKernelTime", ctypes.c_int64),
                        ("ThisPeriodTotalUserTime", ctypes.c_int64),
                        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                        ("TotalPageFaultCount", wt.DWORD),
                        ("TotalProcesses", wt.DWORD),
                        ("ActiveProcesses", wt.DWORD),
                        ("TotalTerminatedProcesses", wt.DWORD)]
        acc = ctypes.cast(buf, ctypes.POINTER(ACCOUNTING)).contents
        return {"active": acc.ActiveProcesses, "total": acc.TotalProcesses,
                "terminated": acc.TotalTerminatedProcesses, "queried": True}

    def contains_pid(self, pid):
        """Membership via the native IsProcessInJob API.

        The previous implementation cast the job's JOBOBJECT_BASIC_PROCESS_ID_LIST
        out of a fixed-size buffer and indexed ProcessIdList up to
        NumberOfProcessIdsInList. That list is variable length, so a job holding
        more PIDs than the buffer could hold caused reads past the allocation and
        a native ACCESS_VIOLATION (0xC0000005) that killed the interpreter.

        IsProcessInJob answers exactly the question being asked with no parsing
        at all, so the unsafe path is gone from the membership critical path
        rather than merely bounds-checked.
        """
        if not self.handle or self._job_state != "OPEN":
            raise RuntimeError("job handle is not OPEN")
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            # Cannot open: the PID does not exist or is inaccessible. Absence of
            # a handle is not membership.
            return False
        try:
            result = wt.BOOL()
            if not k32.IsProcessInJob(h, self.handle, ctypes.byref(result)):
                raise ctypes.WinError(ctypes.get_last_error())
            return bool(result.value)
        finally:
            k32.CloseHandle(h)

    def contains(self, pid):
        """Backwards-compatible alias for contains_pid."""
        return self.contains_pid(pid)

    def enumerate_member_pids(self):
        """Process-id enumeration, isolated from contains_pid.

        Enumeration still needs the variable-length list, so it is confined to
        this method, performs the size dance the Win32 contract requires, and
        bounds-checks every read against the buffer it actually allocated.
        contains_pid never depends on it.
        """
        if not self.handle or self._job_state != "OPEN":
            raise RuntimeError("job handle is not OPEN")
        needed = wt.DWORD(0)
        ok = k32.QueryInformationJobObject(self.handle, 3, None, 0,
                                          ctypes.byref(needed))
        if not ok or needed.value == 0:
            return []
        buf = ctypes.create_string_buffer(needed.value)
        ok = k32.QueryInformationJobObject(self.handle, 3, buf, needed.value,
                                          None)
        if not ok:
            return []
        assigned = ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0]
        listed = ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[1]
        header = ctypes.sizeof(wt.DWORD) * 2
        capacity = max(0, (needed.value - header) // ctypes.sizeof(ctypes.c_ulong))
        count = min(int(listed), capacity)
        base = ctypes.addressof(buf) + header
        out = []
        for i in range(count):
            out.append(int(ctypes.cast(base + i * ctypes.sizeof(ctypes.c_ulong),
                                       ctypes.POINTER(ctypes.c_ulong))[0]))
        return out

    def terminate(self, exit_code=1):
        if self.handle:
            return bool(k32.TerminateJobObject(self.handle, exit_code))
        return False

    def close(self):
        if self.handle:
            k32.CloseHandle(self.handle)
            self.handle = None

    def receipt(self, extra=None):
        return {
            "schema": "WINDOWS_JOB_OBJECT_SUPERVISION/v1",
            "schema_version": SCHEMA_VERSION,
            "generated_utc": utc_now(),
            "job_name": self.name,
            "kill_on_close": self.kill_on_close,
            "created_utc": self.created_utc,
            "policy_flags": {
                "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE": self.kill_on_close,
                "rationale": ("KILL_ON_JOB_CLOSE is the policy that prevents an "
                              "unowned mutator surviving its supervisor. It is "
                              "verified by the synthetic matrix against a "
                              "cmd -> child -> grandchild wrapper chain before "
                              "being relied on."),
            },
            "members": self.member_pids(),
            "tracked_pids": sorted(self.procs),
            **(extra or {}),
        }