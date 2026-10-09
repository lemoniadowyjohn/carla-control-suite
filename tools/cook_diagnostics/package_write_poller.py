#!/usr/bin/env python3
"""
Package Write Poller for GAP-049 cook diagnostics.

Polls a package output directory at 5s intervals, logs new/changed files to CSV.
Does not launch or manage the cook process itself.
"""

from __future__ import annotations

import csv
import os
import time
import hashlib
from pathlib import Path
from typing import Dict, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FileRecord:
    """Record of a file's state."""
    path: str
    size: int
    mtime: float
    sha256: str
    first_seen: str
    last_seen: str
    status: str  # "new", "changed", "unchanged"


class PackageWritePoller:
    """
    Polls a directory for file writes/changes at a fixed interval.
    
    Logs each polling cycle's findings to a CSV with columns:
    timestamp, cycle, file_path, size_bytes, mtime, sha256, status
    
    Does not start/stop the cook process - only observes the output directory.
    """

    def __init__(
        self,
        package_dir: str | Path,
        output_csv: str | Path,
        interval_sec: float = 5.0,
        *,
        follow_symlinks: bool = False,
    ):
        self.package_dir = Path(package_dir).resolve()
        self.output_csv = Path(output_csv).resolve()
        self.interval_sec = interval_sec
        self.follow_symlinks = follow_symlinks
        
        self._known_files: Dict[str, FileRecord] = {}
        self._cycle = 0
        self._running = False
        self._csv_file: Optional[csv.writer] = None
        self._csv_handle = None

    def _compute_sha256(self, path: Path) -> str:
        """Compute SHA256 of a file."""
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
        except (OSError, IOError):
            return "ERROR"
        return h.hexdigest()

    def _scan_directory(self) -> Dict[str, FileRecord]:
        """Scan directory and return current file states."""
        current: Dict[str, FileRecord] = {}
        now = datetime.utcnow().isoformat() + "Z"
        
        if not self.package_dir.exists():
            return current
            
        for path in self.package_dir.rglob("*"):
            if path.is_file():
                if not self.follow_symlinks and path.is_symlink():
                    continue
                try:
                    stat = path.stat()
                    # Use forward slashes for consistency across platforms
                    rel_path = str(path.relative_to(self.package_dir)).replace("\\", "/")
                    sha = self._compute_sha256(path)
                    
                    if rel_path in self._known_files:
                        prev = self._known_files[rel_path]
                        if sha == prev.sha256:
                            status = "unchanged"
                        else:
                            status = "changed"
                        current[rel_path] = FileRecord(
                            path=rel_path,
                            size=stat.st_size,
                            mtime=stat.st_mtime,
                            sha256=sha,
                            first_seen=prev.first_seen,
                            last_seen=now,
                            status=status,
                        )
                    else:
                        current[rel_path] = FileRecord(
                            path=rel_path,
                            size=stat.st_size,
                            mtime=stat.st_mtime,
                            sha256=sha,
                            first_seen=now,
                            last_seen=now,
                            status="new",
                        )
                except (OSError, IOError):
                    pass
        return current

    def _write_csv_header(self) -> None:
        """Write CSV header if file is new/empty."""
        self._csv_handle = open(self.output_csv, "a", newline="", encoding="utf-8")
        self._csv_file = csv.writer(self._csv_handle)
        if self.output_csv.stat().st_size == 0:
            self._csv_file.writerow([
                "timestamp", "cycle", "file_path", "size_bytes",
                "mtime", "sha256", "status"
            ])

    def _write_csv_row(self, record: FileRecord) -> None:
        """Write a single record to CSV."""
        if self._csv_file:
            self._csv_file.writerow([
                datetime.utcnow().isoformat() + "Z",
                self._cycle,
                record.path,
                record.size,
                record.mtime,
                record.sha256,
                record.status,
            ])
            self._csv_handle.flush()

    def poll_once(self) -> Dict[str, FileRecord]:
        """Perform one polling cycle. Returns current file states."""
        # Initialize CSV on first poll if not already done
        if self._csv_handle is None:
            self._write_csv_header()
        
        self._cycle += 1
        current = self._scan_directory()
        
        # Write all current records to CSV
        for record in current.values():
            self._write_csv_row(record)
        
        # Update known files
        self._known_files = current
        return current

    def run(self, max_cycles: Optional[int] = None) -> None:
        """
        Run polling loop until max_cycles reached or stopped.
        
        Args:
            max_cycles: Optional limit on number of cycles. None = run forever.
        """
        self._running = True
        self._write_csv_header()
        
        try:
            while self._running:
                if max_cycles is not None and self._cycle >= max_cycles:
                    break
                self.poll_once()
                time.sleep(self.interval_sec)
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the poller and close CSV."""
        self._running = False
        if self._csv_handle:
            self._csv_handle.close()
            self._csv_handle = None
            self._csv_file = None

    def get_known_files(self) -> Dict[str, FileRecord]:
        """Return current known file states."""
        return dict(self._known_files)

    def get_cycle_count(self) -> int:
        """Return number of completed cycles."""
        return self._cycle


# CLI for standalone usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Package write poller for cook diagnostics")
    parser.add_argument("--package-dir", required=True, help="Package output directory to watch")
    parser.add_argument("--output-csv", required=True, help="CSV output path")
    parser.add_argument("--interval", type=float, default=5.0, help="Poll interval in seconds")
    parser.add_argument("--max-cycles", type=int, help="Maximum poll cycles (default: infinite)")
    parser.add_argument("--follow-symlinks", action="store_true", help="Follow symlinks")
    
    args = parser.parse_args()
    
    poller = PackageWritePoller(
        package_dir=args.package_dir,
        output_csv=args.output_csv,
        interval_sec=args.interval,
        follow_symlinks=args.follow_symlinks,
    )
    
    try:
        poller.run(max_cycles=args.max_cycles)
    except KeyboardInterrupt:
        print("\nStopped by user")
    finally:
        poller.stop()
        print(f"Completed {poller.get_cycle_count()} cycles. Output: {args.output_csv}")