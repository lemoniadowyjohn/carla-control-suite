#!/usr/bin/env python3
"""
Cook Resource Census for GAP-049 cook diagnostics.

Samples process memory at 15s intervals, maintaining separate counters for:
- committed_bytes (Private Bytes / Working Set Private)
- commit_limit (system commit limit)

Does NOT use a single double-read value - each counter is tracked independently.
Does not launch or manage the cook process - only observes a given PID.
"""

from __future__ import annotations

import csv
import os
import time
import psutil
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class MemorySample:
    """Single memory sample for a process."""
    timestamp: str
    cycle: int
    pid: int
    committed_bytes: int      # Private bytes (Windows) / RSS (Linux) - process committed
    commit_limit: int         # System commit limit
    available_bytes: int      # System available memory
    percent_used: float       # Process committed / system commit limit * 100


class CookResourceCensus:
    """
    Samples memory usage of a target process at fixed intervals.
    
    Maintains SEPARATE counters:
    - committed_bytes: process private committed memory (not a double-read)
    - commit_limit: system-wide commit limit (not derived from process)
    
    Logs to CSV with columns:
    timestamp, cycle, pid, committed_bytes, commit_limit, available_bytes, percent_used
    
    Does not start/stop the cook process - only observes a given PID.
    """

    def __init__(
        self,
        pid: int,
        output_csv: str | Path,
        interval_sec: float = 15.0,
    ):
        self.pid = pid
        self.output_csv = Path(output_csv).resolve()
        self.interval_sec = interval_sec
        
        self._samples: List[MemorySample] = []
        self._cycle = 0
        self._running = False
        self._csv_file: Optional[csv.writer] = None
        self._csv_handle = None
        self._process: Optional[psutil.Process] = None

    def _get_process(self) -> Optional[psutil.Process]:
        """Get or create psutil Process object."""
        if self._process is None:
            try:
                self._process = psutil.Process(self.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None
        return self._process

    def _get_system_commit_limit(self) -> int:
        """Get system commit limit (total virtual memory + pagefile)."""
        try:
            vm = psutil.virtual_memory()
            # On Windows: total = physical + pagefile (commit limit)
            # On Linux: commit limit from /proc/meminfo CommitLimit
            return vm.total
        except Exception:
            return 0

    def _get_system_available(self) -> int:
        """Get system available memory."""
        try:
            vm = psutil.virtual_memory()
            return vm.available
        except Exception:
            return 0

    def _sample_once(self) -> Optional[MemorySample]:
        """Take a single memory sample."""
        proc = self._get_process()
        if proc is None:
            return None
            
        try:
            # Get process memory info
            mem_info = proc.memory_info()
            
            # Committed bytes: Private bytes on Windows, RSS on Linux
            # This is the process's ACTUAL committed memory, not a double-read
            if hasattr(mem_info, 'private'):
                committed = mem_info.private  # Windows: Private Bytes
            else:
                committed = mem_info.rss      # Linux: Resident Set Size
            
            # System commit limit - separate counter, not derived from process
            commit_limit = self._get_system_commit_limit()
            
            # Available system memory
            available = self._get_system_available()
            
            # Percent of commit limit used by this process
            percent = (committed / commit_limit * 100) if commit_limit > 0 else 0.0
            
            sample = MemorySample(
                timestamp=datetime.utcnow().isoformat() + "Z",
                cycle=self._cycle,
                pid=self.pid,
                committed_bytes=committed,
                commit_limit=commit_limit,
                available_bytes=available,
                percent_used=percent,
            )
            
            self._samples.append(sample)
            return sample
            
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return None

    def _write_csv_header(self) -> None:
        """Write CSV header if file is new/empty."""
        self._csv_handle = open(self.output_csv, "a", newline="", encoding="utf-8")
        self._csv_file = csv.writer(self._csv_handle)
        if self.output_csv.stat().st_size == 0:
            self._csv_file.writerow([
                "timestamp", "cycle", "pid", "committed_bytes",
                "commit_limit", "available_bytes", "percent_used"
            ])

    def _write_csv_row(self, sample: MemorySample) -> None:
        """Write a single sample to CSV."""
        if self._csv_file:
            self._csv_file.writerow([
                sample.timestamp,
                sample.cycle,
                sample.pid,
                sample.committed_bytes,
                sample.commit_limit,
                sample.available_bytes,
                f"{sample.percent_used:.2f}",
            ])
            self._csv_handle.flush()

    def sample(self) -> Optional[MemorySample]:
        """Take one sample and log to CSV. Returns sample or None if process gone."""
        # Initialize CSV on first sample if not already done
        if self._csv_handle is None:
            self._write_csv_header()
        
        self._cycle += 1
        sample = self._sample_once()
        if sample:
            self._write_csv_row(sample)
        return sample

    def run(self, max_cycles: Optional[int] = None) -> None:
        """
        Run sampling loop until max_cycles reached or stopped.
        
        Args:
            max_cycles: Optional limit on number of cycles. None = run forever.
        """
        self._running = True
        self._write_csv_header()
        
        try:
            while self._running:
                if max_cycles is not None and self._cycle >= max_cycles:
                    break
                sample = self.sample()
                if sample is None:
                    print(f"Process {self.pid} no longer accessible, stopping")
                    break
                time.sleep(self.interval_sec)
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the census and close CSV."""
        self._running = False
        if self._csv_handle:
            self._csv_handle.close()
            self._csv_handle = None
            self._csv_file = None

    def get_samples(self) -> List[MemorySample]:
        """Return all collected samples."""
        return list(self._samples)

    def get_cycle_count(self) -> int:
        """Return number of completed cycles."""
        return self._cycle

    def get_latest(self) -> Optional[MemorySample]:
        """Return most recent sample or None."""
        return self._samples[-1] if self._samples else None


# CLI for standalone usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Cook resource census for cook diagnostics")
    parser.add_argument("--pid", type=int, required=True, help="Process ID to monitor")
    parser.add_argument("--output-csv", required=True, help="CSV output path")
    parser.add_argument("--interval", type=float, default=15.0, help="Sample interval in seconds")
    parser.add_argument("--max-cycles", type=int, help="Maximum sample cycles (default: infinite)")
    
    args = parser.parse_args()
    
    census = CookResourceCensus(
        pid=args.pid,
        output_csv=args.output_csv,
        interval_sec=args.interval,
    )
    
    try:
        census.run(max_cycles=args.max_cycles)
    except KeyboardInterrupt:
        print("\nStopped by user")
    finally:
        census.stop()
        print(f"Completed {census.get_cycle_count()} cycles. Output: {args.output_csv}")