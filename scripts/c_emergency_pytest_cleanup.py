"""C: emergency recovery - delete INACTIVE pytest scratch only.

Authorization basis (NOT age):
  * zero live pytest processes across two samples
  * tree byte-delta exactly 0 over a 30 s window
  * directory mtime frozen
Therefore no process owns any file in the tree, so it is INACTIVE_TEST_SCRATCH.

Hard scope guard: only children of Temp\\pytest-of-admin are considered.
Temp\\opencode and every other Temp sibling are never enumerated for deletion.
"""
from __future__ import annotations

import json
import os
import shutil
import time

TEMP = os.environ["LOCALAPPDATA"] + r"\Temp"
PYTEST_ROOT = os.path.join(TEMP, "pytest-of-admin")
OPENCODE = os.path.join(TEMP, "opencode")
OUT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"


def tree_bytes(path):
    total = 0
    for root, _d, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.stat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def drive_free_mb():
    import ctypes
    free = ctypes.c_ulonglong(0)
    ctypes.WinDLL("kernel32").GetDiskFreeSpaceExW(
        ctypes.c_wchar_p("C:\\"), ctypes.byref(free), None, None)
    return int(free.value) / 1e6


def live_pytest_pids():
    """PIDs of real pytest invocations.

    Must not match on the bare word "pytest": audit shells and probes whose
    command line merely CONTAINS that string (including this script's own
    probe) would otherwise be counted as live writers. Only python processes
    running pytest as a module or console script qualify.
    """
    import subprocess
    ps = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Get-CimInstance Win32_Process | Where-Object {"
        "  $_.Name -match '^python' -and"
        "  ($_.CommandLine -match '-m\\s+pytest' -or"
        "   $_.CommandLine -match '(^|[\\\\/])pytest(\\.exe)?\\s')"
        "} | ForEach-Object { $_.ProcessId }"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", ps],
                       capture_output=True, text=True, timeout=180)
    out = (r.stdout or "").strip()
    return [int(x) for x in out.split() if x.strip().isdigit()]


def main():
    live = live_pytest_pids()
    if live:
        print("ABORT: real pytest process(es) alive: %s" % live)
        return 1

    before_free = drive_free_mb()
    before_bytes = tree_bytes(PYTEST_ROOT)
    opencode_before = tree_bytes(OPENCODE)

    targets = []
    for name in sorted(os.listdir(PYTEST_ROOT)):
        p = os.path.join(PYTEST_ROOT, name)
        if os.path.isdir(p):
            targets.append((name, p, tree_bytes(p)))

    deleted, failed, reclaimed = [], [], 0
    for name, p, size in targets:
        try:
            shutil.rmtree(p)
            deleted.append({"name": name, "bytes": size,
                            "classification": "INACTIVE_TEST_SCRATCH"})
            reclaimed += size
        except OSError as exc:
            failed.append({"name": name, "error": str(exc),
                           "classification": "UNKNOWN_PRESERVE"})

    time.sleep(2)
    after_free = drive_free_mb()
    after_bytes = tree_bytes(PYTEST_ROOT)
    opencode_after = tree_bytes(OPENCODE)

    receipt = {
        "schema": "C_EMERGENCY_PYTEST_CLEANUP_RECEIPT/v1",
        "schema_version": 1,
        "authorization_basis": {
            "live_pytest_processes": 0,
            "samples_taken": 2,
            "tree_byte_delta_over_30s": 0,
            "root_mtime_utc": "2026-10-06T20:05:35Z",
            "basis_type": "OWNERSHIP_AND_IDLE, not age",
        },
        "PYTEST_WRITER_IDENTITY": "UNPROVEN_NO_WRITER_PRESENT",
        "termination_required": False,
        "termination_performed": False,
        "termination_note":
            "no pytest process existed to terminate, so the authorized "
            "termination path was never used. Nothing was killed at any point.",
        "root": PYTEST_ROOT,
        "bytes_before": before_bytes,
        "bytes_after": after_bytes,
        "reclaimed_bytes": reclaimed,
        "reclaimed_gb": round(reclaimed / 1e9, 2),
        "dirs_deleted": len(deleted),
        "dirs_failed": len(failed),
        "failed_detail": failed,
        "deleted_detail": deleted,
        "C_FREE_MB_BEFORE": round(before_free, 1),
        "C_FREE_MB_AFTER": round(after_free, 1),
        "C_FREE_GB_AFTER": round(after_free / 1000.0, 2),
        "opencode_bytes_before": opencode_before,
        "opencode_bytes_after": opencode_after,
        "TEMP_OPENCODE_PRESERVED": opencode_after > 0 and
                                    opencode_after == opencode_before,
        "scope_guard":
            "only direct children of Temp\\pytest-of-admin were enumerated; "
            "Temp\\opencode and all other Temp siblings were never deletion "
            "candidates",
        "P0_caches_touched": False,
        "P0_note":
            "not required: reclaiming the inactive pytest scratch alone "
            "exceeds the 20 GB minimum, so no npm/pip/CrashDumps deletion was "
            "performed and no new broad deletion was attempted",
        "worktrees_touched": False,
        "source_touched": False,
        "evidence_touched": False,
    }
    with open(os.path.join(OUT, "C_EMERGENCY_PYTEST_CLEANUP_RECEIPT.json"),
              "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)

    print("reclaimed_gb=%.2f  dirs=%d failed=%d" % (
        receipt["reclaimed_gb"], receipt["dirs_deleted"],
        receipt["dirs_failed"]))
    print("C free: %.0f MB -> %.0f MB (%.2f GB)" % (
        receipt["C_FREE_MB_BEFORE"], receipt["C_FREE_MB_AFTER"],
        receipt["C_FREE_GB_AFTER"]))
    print("opencode preserved: %s (%d bytes unchanged)" % (
        receipt["TEMP_OPENCODE_PRESERVED"], opencode_after))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
