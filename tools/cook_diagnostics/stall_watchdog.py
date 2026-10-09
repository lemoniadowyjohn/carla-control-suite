#!/usr/bin/env python3
"""
Stall Watchdog for GAP-049 cook diagnostics.

Monitors a package output directory for new files. If no new file appears
for 10 minutes (600 seconds), triggers a procdump of the target process
WITHOUT killing the cook process itself.

Logs watchdog events to CSV with columns:
timestamp, event_type, pid, package_dir, details
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Optional, Set, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class WatchdogEvent(Enum):
    STARTED = "started"
    FILE_DETECTED = "file_detected"
    STALL_DETECTED = "stall_detected"
    PROCDUMP_TRIGGERED = "procdump_triggered"
    PROCDUMP_SUCCESS = "procdump_success"
    PROCDUMP_FAILED = "procdump_failed"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class WatchdogLogEntry:
    """Log entry for watchdog events."""
    timestamp: str
    event_type: str
    pid: int
    package_dir: str
    details: str


class StallWatchdog:
    """
    Watches a directory for file creation. If no new file for stall_timeout_sec,
    triggers procdump on the target PID. Does NOT kill the process.
    
    Requires procdump (Windows) or gdb (Linux) to be available in PATH.
    """

    def __init__(
        self,
        pid: int,
        package_dir: str | Path,
        stall_timeout_sec: float = 600.0,  # 10 minutes default
        check_interval_sec: float = 5.0,
        procdump_path: str = "procdump",
        dump_dir: Optional[str | Path] = None,
        *,
        on_stall: Optional[Callable[[int, str], None]] = None,
    ):
        self.pid = pid
        self.package_dir = Path(package_dir).resolve()
        self.stall_timeout_sec = stall_timeout_sec
        self.check_interval_sec = check_interval_sec
        self.procdump_path = procdump_path
        self.dump_dir = Path(dump_dir).resolve() if dump_dir else self.package_dir.parent / "dumps"
        self.on_stall = on_stall
        
        self._known_files: Set[str] = set()
        self._last_file_time: Optional[float] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._csv_file: Optional[csv.writer] = None
        self._csv_handle = None
        self._log_csv = self.dump_dir / "stall_watchdog_log.csv"
        self._lock = threading.Lock()
        self._stall_handling = False  # Prevent duplicate stall handling

    def _log_event(self, event: WatchdogEvent, details: str = "") -> None:
        """Log an event to CSV."""
        entry = WatchdogLogEntry(
            timestamp=datetime.utcnow().isoformat() + "Z",
            event_type=event.value,
            pid=self.pid,
            package_dir=str(self.package_dir),
            details=details,
        )
        with self._lock:
            if self._csv_file:
                self._csv_file.writerow([
                    entry.timestamp,
                    entry.event_type,
                    entry.pid,
                    entry.package_dir,
                    entry.details,
                ])
                self._csv_handle.flush()

    def _scan_files(self) -> Set[str]:
        """Scan directory for files, return set of relative paths."""
        files = set()
        if self.package_dir.exists():
            for path in self.package_dir.rglob("*"):
                if path.is_file():
                    try:
                        # Use forward slashes for consistency across platforms
                        rel_path = str(path.relative_to(self.package_dir)).replace("\\", "/")
                        files.add(rel_path)
                    except ValueError:
                        pass
        return files

    def _check_for_new_files(self) -> bool:
        """Check for new files since last scan. Returns True if any found."""
        current = self._scan_files()
        new_files = current - self._known_files
        
        if new_files:
            self._known_files = current
            self._last_file_time = time.time()
            for f in new_files:
                self._log_event(WatchdogEvent.FILE_DETECTED, f"New file: {f}")
            return True
        
        self._known_files = current
        return False

    def _trigger_procdump(self) -> bool:
        """Trigger procdump on the target PID. Returns True on success."""
        self.dump_dir.mkdir(parents=True, exist_ok=True)
        dump_file = self.dump_dir / f"cook_stall_pid{self.pid}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.dmp"
        
        self._log_event(WatchdogEvent.PROCDUMP_TRIGGERED, f"Target dump: {dump_file}")
        
        try:
            if sys.platform == "win32":
                # Windows: use procdump (Sysinternals)
                # procdump -ma <pid> <dumpfile>
                cmd = [self.procdump_path, "-ma", str(self.pid), str(dump_file)]
            else:
                # Linux: use gdb to generate core dump
                # gdb -batch -ex "generate-core-file" -ex "quit" -p <pid>
                cmd = ["gdb", "-batch", "-ex", "generate-core-file", "-ex", "quit", "-p", str(self.pid)]
                # gdb writes to current dir, so we need to move it
                # Actually gdb writes to cwd, let's specify output
                cmd = ["gdb", "-batch", "-ex", f"generate-core-file {dump_file}", "-ex", "quit", "-p", str(self.pid)]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout for dump
            )
            
            if result.returncode == 0:
                self._log_event(WatchdogEvent.PROCDUMP_SUCCESS, f"Dump written: {dump_file}")
                return True
            else:
                self._log_event(WatchdogEvent.PROCDUMP_FAILED, f"Exit code {result.returncode}: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            self._log_event(WatchdogEvent.PROCDUMP_FAILED, "procdump timed out after 120s")
            return False
        except FileNotFoundError:
            self._log_event(WatchdogEvent.PROCDUMP_FAILED, f"{self.procdump_path} not found in PATH")
            return False
        except Exception as e:
            self._log_event(WatchdogEvent.PROCDUMP_FAILED, f"Exception: {e}")
            return False

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        self._log_event(WatchdogEvent.STARTED, f"Stall timeout: {self.stall_timeout_sec}s")
        
        # Initial scan
        self._known_files = self._scan_files()
        self._last_file_time = time.time()
        
        while self._running:
            time.sleep(self.check_interval_sec)
            
            if not self._running:
                break
                
            # Check for new files
            has_new = self._check_for_new_files()
            
            # Check for stall
            if self._last_file_time is not None:
                elapsed = time.time() - self._last_file_time
                if elapsed >= self.stall_timeout_sec and not self._stall_handling:
                    self._stall_handling = True
                    self._log_event(WatchdogEvent.STALL_DETECTED, 
                        f"No new files for {elapsed:.0f}s (timeout: {self.stall_timeout_sec}s)")
                    
                    # Call optional callback
                    if self.on_stall:
                        try:
                            self.on_stall(self.pid, str(self.package_dir))
                        except Exception as e:
                            self._log_event(WatchdogEvent.ERROR, f"on_stall callback failed: {e}")
                    
                    # Trigger procdump (does NOT kill process)
                    success = self._trigger_procdump()
                    
                    if success:
                        # Reset timer after successful dump to avoid spam
                        self._last_file_time = time.time()
                    else:
                        # If dump failed, wait longer before retry
                        self._last_file_time = time.time() + 60  # Add 60s grace
                    
                    self._stall_handling = False

    def start(self) -> None:
        """Start the watchdog in a background thread."""
        if self._running:
            return
            
        self._running = True
        # Ensure dump directory exists before opening log file
        self.dump_dir.mkdir(parents=True, exist_ok=True)
        self._csv_handle = open(self._log_csv, "a", newline="", encoding="utf-8")
        self._csv_file = csv.writer(self._csv_handle)
        if self._log_csv.stat().st_size == 0:
            self._csv_file.writerow([
                "timestamp", "event_type", "pid", "package_dir", "details"
            ])
        
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the watchdog."""
        self._running = False
        # Log STOPPED event before closing CSV
        self._log_event(WatchdogEvent.STOPPED, "Watchdog stopped")
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        if self._csv_handle:
            self._csv_handle.close()
            self._csv_handle = None
            self._csv_file = None

    def is_running(self) -> bool:
        """Return True if watchdog is running."""
        return self._running

    def get_log_path(self) -> Path:
        """Return path to log CSV."""
        return self._log_csv

    def force_check(self) -> bool:
        """Force an immediate check for new files. Returns True if any found."""
        return self._check_for_new_files()

    def get_time_since_last_file(self) -> Optional[float]:
        """Return seconds since last new file, or None if never."""
        if self._last_file_time is None:
            return None
        return time.time() - self._last_file_time


# CLI for standalone usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Stall watchdog for cook diagnostics")
    parser.add_argument("--pid", type=int, required=True, help="Process ID to monitor")
    parser.add_argument("--package-dir", required=True, help="Package output directory to watch")
    parser.add_argument("--stall-timeout", type=float, default=600.0, help="Stall timeout in seconds (default: 600)")
    parser.add_argument("--check-interval", type=float, default=5.0, help="Check interval in seconds (default: 5)")
    parser.add_argument("--procdump", default="procdump", help="Path to procdump/gdb executable")
    parser.add_argument("--dump-dir", help="Directory for dump files (default: package_dir/../dumps)")
    
    args = parser.parse_args()
    
    watchdog = StallWatchdog(
        pid=args.pid,
        package_dir=args.package_dir,
        stall_timeout_sec=args.stall_timeout,
        check_interval_sec=args.check_interval,
        procdump_path=args.procdump,
        dump_dir=args.dump_dir,
    )
    
    try:
        watchdog.start()
        print(f"Stall watchdog started for PID {args.pid}, watching {args.package_dir}")
        print(f"Stall timeout: {args.stall_timeout}s, check interval: {args.check_interval}s")
        print(f"Log: {watchdog.get_log_path()}")
        print("Press Ctrl+C to stop...")
        
        while watchdog.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        watchdog.stop()
        print("Watchdog stopped.")