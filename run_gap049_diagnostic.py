#!/usr/bin/env python3
"""
GAP-049 Full Cook Diagnostic Runner.

Orchestrates the full production cook with all three diagnostics attached:
- package_write_poller.py (5s interval, CSV output)
- cook_resource_census.py (15s interval, separate committed_bytes/commit_limit)
- stall_watchdog.py (10 min stall timeout, procdump on stall, NO kill)

Also tracks ShaderCompileWorker processes.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO_ROOT))

from tools.cook_diagnostics.package_write_poller import PackageWritePoller
from tools.cook_diagnostics.cook_resource_census import CookResourceCensus
from tools.cook_diagnostics.stall_watchdog import StallWatchdog


class ShaderWorkerTracker:
    """Tracks ShaderCompileWorker processes throughout the cook."""

    def __init__(self, output_csv: Path):
        self.output_csv = output_csv
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._csv_handle = None
        self._csv_writer = None
        self._lock = threading.Lock()
        self._known_workers: Dict[int, Dict] = {}

    def _get_worker_processes(self) -> List[Dict]:
        """Get all ShaderCompileWorker processes using psutil."""
        import psutil
        workers = []
        for proc in psutil.process_iter(['pid', 'ppid', 'name', 'cmdline', 'create_time', 'cpu_percent']):
            try:
                if proc.info['name'] and 'ShaderCompileWorker' in proc.info['name']:
                    workers.append({
                        'pid': proc.info['pid'],
                        'ppid': proc.info['ppid'],
                        'name': proc.info['name'],
                        'cmdline': ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else '',
                        'create_time': datetime.fromtimestamp(proc.info['create_time']).isoformat() + 'Z' if proc.info['create_time'] else '',
                        'cpu_percent': proc.info['cpu_percent'] or 0.0,
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return workers

    def _write_csv_header(self):
        self._csv_handle = open(self.output_csv, "a", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._csv_handle)
        if self.output_csv.stat().st_size == 0:
            self._csv_writer.writerow([
                "timestamp", "event", "pid", "ppid", "name", "cmdline",
                "create_time", "exit_time", "cpu_percent", "status"
            ])

    def _write_row(self, row: List):
        with self._lock:
            if self._csv_writer:
                self._csv_writer.writerow(row)
                self._csv_handle.flush()

    def _monitor_loop(self):
        self._write_csv_header()
        self._write_row([datetime.utcnow().isoformat() + "Z", "STARTED", "", "", "", "", "", "", "", ""])

        while self._running:
            time.sleep(5)  # Check every 5 seconds
            if not self._running:
                break

            current_workers = {w['pid']: w for w in self._get_worker_processes()}
            current_pids = set(current_workers.keys())
            known_pids = set(self._known_workers.keys())

            # New workers
            for pid in current_pids - known_pids:
                w = current_workers[pid]
                self._write_row([
                    datetime.utcnow().isoformat() + "Z", "WORKER_STARTED",
                    w['pid'], w['ppid'], w['name'], w['cmdline'],
                    w['create_time'], "", w['cpu_percent'], "running"
                ])
                self._known_workers[pid] = w

            # Exited workers
            for pid in known_pids - current_pids:
                w = self._known_workers[pid]
                self._write_row([
                    datetime.utcnow().isoformat() + "Z", "WORKER_EXITED",
                    w['pid'], w.get('ppid', ''), w.get('name', ''), w.get('cmdline', ''),
                    w.get('create_time', ''), datetime.utcnow().isoformat() + "Z", 0, "exited"
                ])
                del self._known_workers[pid]

            # Update existing workers (CPU)
            for pid in current_pids & known_pids:
                w = current_workers[pid]
                self._known_workers[pid] = w

        self._write_row([datetime.utcnow().isoformat() + "Z", "STOPPED", "", "", "", "", "", "", "", ""])
        if self._csv_handle:
            self._csv_handle.close()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)


def main():
    # Configuration
    out_root = Path(r"F:\CARLA\cook_diag_GAP049_20261009T155750Z")
    diag_dir = out_root / "diagnostics"
    cook_out_dir = out_root / "cook_output"
    dump_dir = out_root / "dumps"
    log_dir = out_root / "logs"

    # Ensure directories exist
    for d in [diag_dir, cook_out_dir, dump_dir, log_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Cook command - FULL PRODUCTION COOK (no -cooksinglepackage, use main Ingolstadt map)
    uproject = r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\CarlaUE4.uproject"
    ue4editor = r"G:\UnrealEngine_4.26_CARLA\Engine\Binaries\Win64\UE4Editor.exe"

    cook_cmd = [
        ue4editor,
        uproject,
        "-run=cook",
        "-map=/Game/Ingolstadt/Maps/Ingolstadt/Ingolstadt",
        "-targetplatform=WindowsNoEditor",
        f"-OutputDir={cook_out_dir}",
        "-iterate",
        "-unattended",
        "-NoLogTimes",
        "-UTF8Output",
        "-stdout",
        f"-abslog={log_dir / 'cook_log.txt'}",
        "-LogCmds=LogShaderCompilers Verbose",
    ]

    # Environment with DDC override
    env = os.environ.copy()
    env["UE-LocalDataCachePath"] = r"F:\UnrealEngine_DDC"

    print("=" * 80)
    print("GAP-049 FULL PRODUCTION COOK DIAGNOSTIC")
    print("=" * 80)
    print(f"Output root: {out_root}")
    print(f"Cook output: {cook_out_dir}")
    print(f"Log dir: {log_dir}")
    print(f"Dump dir: {dump_dir}")
    print(f"Command: {' '.join(cook_cmd)}")
    print("=" * 80)

    # Start the cook process
    print("\n[1/5] Starting UE4Editor cook process...")
    proc = subprocess.Popen(
        cook_cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    cook_pid = proc.pid
    print(f"    Cook PID: {cook_pid}")

    # Give it a moment to spawn
    time.sleep(3)

    # Start diagnostics
    print("\n[2/5] Starting Package Write Poller (5s interval)...")
    poller = PackageWritePoller(
        package_dir=cook_out_dir,
        output_csv=diag_dir / "GAP049_PACKAGE_WRITES.csv",
        interval_sec=5.0,
    )
    poller_thread = threading.Thread(target=poller.run, daemon=True)
    poller_thread.start()

    print("[3/5] Starting Cook Resource Census (15s interval)...")
    census = CookResourceCensus(
        pid=cook_pid,
        output_csv=diag_dir / "GAP049_RESOURCE_CENSUS.csv",
        interval_sec=15.0,
    )
    census_thread = threading.Thread(target=census.run, daemon=True)
    census_thread.start()

    print("[4/5] Starting Stall Watchdog (10 min timeout, procdump only)...")
    watchdog = StallWatchdog(
        pid=cook_pid,
        package_dir=cook_out_dir,
        stall_timeout_sec=600.0,  # 10 minutes
        check_interval_sec=5.0,
        procdump_path="procdump",  # Will fail gracefully if not found
        dump_dir=dump_dir,
    )
    watchdog.start()

    print("[5/5] Starting Shader Worker Tracker...")
    worker_tracker = ShaderWorkerTracker(diag_dir / "GAP049_SHADER_WORKERS.csv")
    worker_tracker.start()

    print("\n" + "=" * 80)
    print("ALL DIAGNOSTICS ATTACHED - COOK RUNNING")
    print("=" * 80)
    print("Monitoring cook process... Press Ctrl+C to stop diagnostics (cook continues)")
    print("=" * 80 + "\n")

    # Monitor cook process and stream output
    try:
        # Stream stdout/stderr
        for line in proc.stdout:
            print(line.rstrip())
    except KeyboardInterrupt:
        print("\n\nKeyboardInterrupt received - stopping diagnostics...")
    finally:
        # Stop diagnostics
        print("\nStopping diagnostics...")
        poller.stop()
        census.stop()
        watchdog.stop()
        worker_tracker.stop()

        # Wait for cook to finish (with timeout)
        print("Waiting for cook process to terminate...")
        try:
            exit_code = proc.wait(timeout=300)  # 5 min grace period
            print(f"Cook process exited with code: {exit_code}")
        except subprocess.TimeoutExpired:
            print("Cook process still running after 5 min grace - leaving it running")
            exit_code = None

    # Collect final diagnostics data
    print("\nCollecting final data...")
    time.sleep(2)  # Let final writes flush

    # Write watchdog log location
    watchdog_log = watchdog.get_log_path()
    print(f"Watchdog log: {watchdog_log}")

    # Generate receipt
    receipt = {
        "schema": "GAP049_FULL_COOK_RUN_RECEIPT/v1",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "base_sha": "68868f763d22a630fc9ba8d818ed1919a7b8414d",
        "diagnostics_sha": "c859cd831c5b5a50d76cb513bc4e287493f326c4",
        "run_id": "e200091978c14bb1bea1b85485c24755",
        "cook_pid": cook_pid,
        "cook_exit_code": exit_code,
        "output_root": str(out_root),
        "cook_output_dir": str(cook_out_dir),
        "diagnostics_dir": str(diag_dir),
        "ddc_path": r"F:\UnrealEngine_DDC",
        "iterative_baseline": "EMPTY_FRESH",
        "effective_es31_count": 0,
        "gap043_effective": True,  # Hair/groom exclusion via ES31 removal
        "artifacts": {
            "package_writes": str(diag_dir / "GAP049_PACKAGE_WRITES.csv"),
            "resource_census": str(diag_dir / "GAP049_RESOURCE_CENSUS.csv"),
            "shader_workers": str(diag_dir / "GAP049_SHADER_WORKERS.csv"),
            "stall_watchdog": str(watchdog_log),
        }
    }

    receipt_path = out_root / "GAP049_FULL_COOK_RUN_RECEIPT.json"
    with open(receipt_path, "w") as f:
        json.dump(receipt, f, indent=2)
    print(f"Receipt written: {receipt_path}")

    print("\n" + "=" * 80)
    print("DIAGNOSTIC RUN COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()