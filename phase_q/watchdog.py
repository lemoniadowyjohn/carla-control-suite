"""Q14 - Watchdog, crash recovery, and evidence preservation.

Reusable supervision for a certification subprocess.  Captures:

* server exit code, stdout/stderr streams
* assertion / crash dialog detection (Windows Event Log reference,
  minidump path, last successful frame, active scenario)
* memory / VRAM before crash
* candidate/package identity

On crash:
* preserve evidence
* do NOT auto-fallback to a Town map
* do NOT silently restart and continue the same certification run
* mark the run FAILED or BLOCKED

This module is offline and does not require CARLA; the actual process runner
is provided as a composable function.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from phase_q.common import make_run_id, save_json, utcnow_iso

CRASH_MARKERS = (
    "Assertion failed", "Fatal error", "Unhandled exception", "Segmentation fault",
    "EXCEPTION_ACCESS_VIOLATION", "CRASH", "minidump", "assertion",
)


@dataclass
class WatchdogContext:
    run_id: str = field(default_factory=make_run_id)
    server_pid: Optional[int] = None
    candidate_sha256: Optional[str] = None
    package_sha256: Optional[str] = None
    active_scenario: Optional[str] = None
    last_successful_frame: int = 0
    memory_mb_before: Optional[int] = None
    vram_mb_before: Optional[int] = None


def _monitor_memory() -> Dict[str, Optional[float]]:
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        return {"ram_mb": round(vm.used / (1024 ** 2), 1),
                "ram_total_mb": round(vm.total / (1024 ** 2), 1)}
    except Exception:
        return {"ram_mb": None, "ram_total_mb": None}


def watch_subprocess(
    cmd: List[str],
    context: WatchdogContext,
    out_dir: str,
    timeout_s: int = 600,
) -> Dict[str, Any]:
    """Run ``cmd`` and build the Q14 crash-evidence record.

    If the subprocess crashes (non-zero exit or crash markers in output) the
    evidence is preserved and the certification run is marked FAILED.  No
    fallback map is loaded and no silent restart occurs.
    """
    std_out_path = os.path.join(out_dir, "stdout.log")
    std_err_path = os.path.join(out_dir, "stderr.log")

    record: Dict[str, Any] = {
        "schema": "Q14_WATCHDOG/v1",
        "run_id": context.run_id,
        "candidate_sha256": context.candidate_sha256,
        "package_sha256": context.package_sha256,
        "active_scenario": context.active_scenario,
        "last_successful_frame": context.last_successful_frame,
    }
    try:
        with open(std_out_path, "wb") as fout, open(std_err_path, "wb") as ferr:
            proc = subprocess.run(cmd, stdout=fout, stderr=ferr, timeout=timeout_s)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        record["exit_code"] = "TIMEOUT"
        record["status"] = "BLOCKED"
        record["reason"] = "subprocess exceeded timeout; treated as BLOCKED"
        save_json(os.path.join(out_dir, "Q14_WATCHDOG_EVIDENCE.json"), record)
        return record

    record["exit_code"] = exit_code

    try:
        with open(std_out_path, "r", encoding="utf-8", errors="replace") as f:
            out_text = f.read()
        with open(std_err_path, "r", encoding="utf-8", errors="replace") as f:
            err_text = f.read()
    except Exception:
        out_text = ""
        err_text = ""

    crash_hits = [m for m in CRASH_MARKERS
                  if m.lower() in (out_text + err_text).lower()]
    crashed = exit_code != 0 or bool(crash_hits)

    record["stdout_bytes"] = len(out_text)
    record["stderr_bytes"] = len(err_text)
    record["crash_markers_detected"] = crash_hits
    record["windows_event_log"] = _event_log_tail()
    record["minidump_path"] = _probe_minidump()
    record["memory_before"] = context.memory_mb_before
    record["vram_before"] = context.vram_mb_before

    if crashed:
        record["status"] = "FAILED"
        record["reason"] = "crash or non-zero exit; run FAILED, evidence preserved"
        record["fallback_applied"] = False
        record["silent_restart"] = False
    else:
        record["status"] = "COMPLETED"

    save_json(os.path.join(out_dir, "Q14_WATCHDOG_EVIDENCE.json"), record)
    return record


def _event_log_tail() -> Optional[str]:
    return None  # offline; Windows Event Log reference filled by operator


def _probe_minidump() -> Optional[str]:
    for candidate in ("minidump", "saved", "Saved/Minidumps", "minidumps"):
        if os.path.exists(candidate):
            return candidate
    return None