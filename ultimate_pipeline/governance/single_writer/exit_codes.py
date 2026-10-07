"""Windows exit-code contract for governed operations.

0 => SUCCESS. Nonzero small codes are program exits, NOT signals: POSIX
128+signal logic must never be applied on Windows. Known NTSTATUS codes
(CONTROL_C_EXIT, common exceptions) classify explicitly; supervisor kills
and timeouts have their own receipts.
"""
from __future__ import annotations

from typing import Any, Dict

CONTROL_C_EXIT = 0xC000013A

NTSTATUS_NAMES = {
    0xC0000005: "ACCESS_VIOLATION",
    0xC00000FD: "STACK_OVERFLOW",
    0xC0000409: "STACK_BUFFER_OVERRUN",
    0xC0000135: "DLL_NOT_FOUND",
    0xC0000142: "DLL_INIT_FAILED",
    0xC000013A: "CONTROL_C_EXIT",
    0xC000021A: "STATUS_SYSTEM_PROCESS_TERMINATED",
    0xC0000374: "HEAP_CORRUPTION",
}


def classify_exit(code: int, *, killed_by_supervisor: bool = False,
                  timed_out: bool = False) -> Dict[str, Any]:
    if timed_out:
        return {"class": "TIMEOUT", "success": False, "code": code}
    if killed_by_supervisor:
        return {"class": "TERMINATED_BY_SUPERVISOR", "success": False,
                "code": code}
    if code == 0:
        return {"class": "SUCCESS", "success": True, "code": 0}
    if code in (1, 2):
        return {"class": "PROGRAM_NONZERO_EXIT", "success": False,
                "code": code}
    if code < 0:
        # Negative codes on Windows are already NTSTATUS-as-signed.
        unsigned = code & 0xFFFFFFFF
        name = NTSTATUS_NAMES.get(unsigned, "UNKNOWN_WINDOWS_EXCEPTION")
        return {"class": name, "success": False, "code": code}
    if code >= 0xC0000000:
        name = NTSTATUS_NAMES.get(code, "UNKNOWN_WINDOWS_EXCEPTION")
        return {"class": name, "success": False, "code": code}
    return {"class": "UNKNOWN_WINDOWS_EXIT", "success": False, "code": code}
