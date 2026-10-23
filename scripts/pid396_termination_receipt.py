"""Phase 2 termination receipt + Phase 4/5/6/8 storage inventory.

Read-only with respect to all data: nothing is deleted. Only the explicitly
authorized PID 396 termination was performed in Phase 2.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess

OUT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"
REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"


def w(name, obj):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


def dir_size_gb(path, max_files=400000):
    total = 0
    count = 0
    newest = 0.0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            fp = os.path.join(root, f)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            total += st.st_size
            count += 1
            newest = max(newest, st.st_mtime)
            if count >= max_files:
                return total / 1e9, count, newest
    return total / 1e9, count, newest


# ---------------------------------------------------------- Phase 2 receipt
w("PID396_TERMINATION_RECEIPT.json", {
    "schema": "PID396_TERMINATION_RECEIPT/v1",
    "PID396_IDENTITY_MATCH": True,
    "identity_bound_to": {
        "pid": 396,
        "creation_time_utc": "2026-10-06T12:30:44.7613250Z",
        "verified_before_kill": True,
        "parent_pid": 31268,
        "parent_alive": False,
        "session_id": 1,
    },
    "PID396_CLASSIFICATION": "STALE_ORPHANED_EDITOR",
    "PID396_OPEN_PROJECT_HANDLES": {
        "files_probed": 40,
        "files_locked": 0,
        "method": "exclusive-open probe; Sysinternals handle.exe absent",
        "carla_modules_loaded": 562,
        "total_modules_loaded": 666,
    },
    "PID396_DESCENDANT_COUNT": 0,
    "PID396_TERMINATION_AUTHORIZED": True,
    "termination_mechanism":
        "Stop-Process -Id 396 -Force, executed ONLY after re-reading "
        "Win32_Process and confirming creation_time still equals "
        "2026-10-06T12:30:44.7613250Z. No image-name termination, no wildcard, "
        "no /IM switch.",
    "PID396_TERMINATED": True,
    "PID396_DESCENDANTS_ALIVE": 0,
    "termination_classification": "GOVERNED_OPERATOR_TERMINATION",
    "post_kill_verification": {
        "Get-Process": "absent",
        "Win32_Process": "absent after teardown settled (~5 s)",
        "note": "immediately after the kill, Win32_Process still listed PID "
                "396 while Get-Process already reported it absent; this is "
                "normal process-teardown residue and it cleared on re-query.",
    },
    "ACTIVE_CONFLICTING_MUTATORS": 0,
    "post_kill_census": {
        "UE4Editor": 0,
        "UE4Editor-Cmd": 0,
        "ShaderCompileWorker": 0,
        "CarlaUE4_server": 0,
        "CrashReportClient": 0,
        "python_non_mutator": [
            {"pid": 31632,
             "command": ".venv\\Scripts\\python.exe -m pytest -q",
             "classification": "NON_MUTATOR",
             "note": "unit test run; does not write Unreal Content. Also "
                     "independently reconfirms the documented venv "
                     "launcher -> base interpreter process topology "
                     "(31632 launcher, 23488 interpreter)."}
        ],
    },
    "CORRECTION_TO_PRIOR_BATCH_CLAIM": {
        "prior_claim": "PID 396 was actively writing to G: and consuming "
                       "4 GB of free space during observation",
        "corrected": "The 4 GB drop between two measurements was real, but a "
                     "20 s re-measurement showed G: stable at 28.71 GB and the "
                     "process not writing. The drop was NOT sustained and is "
                     "NOT attributed to PID 396. What is proven is CPU "
                     "spinning: 12.58 s CPU per 20 s wall, about 63% of one "
                     "core, sustained across three separate samples.",
        "impact_on_decision": "None. The process was orphaned, hung far past "
                              "its -executecmds=quit contract, and spinning, "
                              "which is sufficient grounds for termination on "
                              "its own.",
    },
    "relaunch_policy": "NOT_RELAUNCHED. No editor was started after "
                       "termination. Any future editor validation must be "
                       "launched under a single-writer lease and Job Object "
                       "with PID+creation_time identity, a bounded timeout and "
                       "a terminal receipt.",
})
print("PID396_TERMINATION_RECEIPT.json written")
