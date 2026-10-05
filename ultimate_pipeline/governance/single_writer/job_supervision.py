"""Windows Job Object supervision for governed operations.

A Job Object groups an owned process tree so that:
- normal exit / crash / timeout of any member is observable centrally,
- operator cancellation kills exactly the owned tree (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
  plus explicit TerminateJobObject), never same-name unrelated processes.

Only NEW governed operations are placed in jobs; nothing is retro-attached.
"""
from __future__ import annotations

import ctypes
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004
_JobObjectExtendedLimitInformation = 9


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_void_p),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in (
        "ReadOperationCount", "WriteOperationCount",
        "OtherOperationCount", "ReadTransferCount",
        "WriteTransferCount", "OtherTransferCount")]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JOBOBJECT_BASIC_PROCESS_ID_LIST(ctypes.Structure):
    _fields_ = [("NumberOfAssignedProcesses", ctypes.c_uint32),
                ("NumberOfProcessIdsInList", ctypes.c_uint32),
                ("ProcessIdList", ctypes.c_void_p * 256)]


def _check(result: bool, what: str) -> None:
    if not result:
        raise ctypes.WinError(ctypes.get_last_error(), what)


@dataclass
class OwnedJob:
    handle: int
    root_pid: int
    kill_on_close: bool = True

    def member_pids(self) -> List[int]:
        buf = _JOBOBJECT_BASIC_PROCESS_ID_LIST()
        size = ctypes.sizeof(buf)
        ret_len = ctypes.c_uint32()
        # JobObjectBasicProcessIdList = 3 (6 is BasicAccountingInformation).
        ok = _kernel32.QueryInformationJobObject(
            self.handle, 3, ctypes.byref(buf), size,
            ctypes.byref(ret_len))
        if not ok:
            return []
        return [int(buf.ProcessIdList[i])
                for i in range(buf.NumberOfProcessIdsInList)]

    def terminate_owned(self, exit_code: int = 1) -> None:
        _check(bool(_kernel32.TerminateJobObject(self.handle, exit_code)),
               "TerminateJobObject")

    def close(self) -> None:
        _kernel32.CloseHandle(self.handle)


def create_job(time_limit_100ns: int = 0,
               kill_on_close: bool = True) -> OwnedJob:
    handle = _kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error(), "CreateJobObjectW")
    if time_limit_100ns or kill_on_close:
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        if kill_on_close:
            info.BasicLimitInformation.LimitFlags |= \
                _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if time_limit_100ns:
            info.BasicLimitInformation.LimitFlags |= _JOB_OBJECT_LIMIT_JOB_TIME
            info.BasicLimitInformation.PerJobUserTimeLimit = time_limit_100ns
        _check(bool(_kernel32.SetInformationJobObject(
            handle, _JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info))),
            "SetInformationJobObject")
    return OwnedJob(handle=handle, root_pid=0)


class _THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ThreadID", ctypes.c_uint32),
        ("th32OwnerProcessID", ctypes.c_uint32),
        ("tpBasePri", ctypes.c_int32),
        ("tpDeltaPri", ctypes.c_int32),
        ("dwFlags", ctypes.c_uint32),
    ]


def _resume_primary_thread(pid: int) -> None:
    """Resume the first thread of a CREATE_SUSPENDED process.

    ResumeThread needs a THREAD handle; subprocess only exposes the process
    handle (passing it silently fails and leaves the child frozen -- this
    exact bug was observed: members listed the child but no grandchild ever
    spawned). Enumerate threads via Toolhelp and resume the owner's first.
    """
    TH32CS_SNAPTHREAD = 0x00000004
    THREAD_SUSPEND_RESUME = 0x0002
    INVALID = ctypes.c_void_p(-1).value
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == INVALID:
        raise ctypes.WinError(ctypes.get_last_error(), "ToolhelpSnapshot")
    try:
        entry = _THREADENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _kernel32.Thread32First(snap, ctypes.byref(entry))
        while ok:
            if entry.th32OwnerProcessID == pid:
                th = _kernel32.OpenThread(THREAD_SUSPEND_RESUME, False,
                                          entry.th32ThreadID)
                if th:
                    try:
                        if _kernel32.ResumeThread(th) != 0xFFFFFFFF:
                            return
                    finally:
                        _kernel32.CloseHandle(th)
                    raise ctypes.WinError(ctypes.get_last_error(),
                                          "ResumeThread")
                raise ctypes.WinError(ctypes.get_last_error(), "OpenThread")
            ok = _kernel32.Thread32Next(snap, ctypes.byref(entry))
        raise RuntimeError(f"no thread found for pid {pid}")
    finally:
        _kernel32.CloseHandle(snap)


def spawn_in_job(job: OwnedJob, cmd: List[str],
                 cwd: Optional[str] = None) -> "subprocess.Popen[str]":
    """Spawn a child constrained so ALL descendants join the job.

    Uses CREATE_BREAKAWAY_FROM_JOB (child leaves any ambient job, e.g. the
    agent harness job) + CREATE_SUSPENDED, assigns to OUR job, then resumes
    the primary thread via Toolhelp enumeration. Without the breakaway
    dance the assign would fail when the supervisor itself runs inside a
    job; without the proper resume the child stays frozen.
    """
    CREATE_SUSPENDED = 0x00000004
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, creationflags=CREATE_SUSPENDED | CREATE_BREAKAWAY_FROM_JOB)
    try:
        _check(bool(_kernel32.AssignProcessToJobObject(
            job.handle, proc._handle)), "AssignProcessToJobObject")
    except Exception:
        proc.kill()
        raise
    try:
        _resume_primary_thread(proc.pid)
    except Exception:
        proc.kill()
        raise
    job.root_pid = proc.pid
    return proc
