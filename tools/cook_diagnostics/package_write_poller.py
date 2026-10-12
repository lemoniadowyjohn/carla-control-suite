#!/usr/bin/env python3
"""
Package Write Poller for GAP-049 cook diagnostics.

Polls a package output directory at 5s intervals, logs deltas to CSV.
Does not launch or manage the cook process itself.

Disk-safety contract (GAP-049 lesson: the 2026-10-11 city-scale run emitted
~1.43M rows / 273 MB to C: and died ENOSPC next to a cook that then failed
its own G: write):
  * metadata-first: size + mtime_ns decide; SHA-256 runs only for files that
    are new or whose metadata changed. An unchanged tree hashes 0 files.
  * emit-only deltas: new / changed / deleted / error rows plus exactly one
    heartbeat row per cycle. Unchanged files are never emitted.
  * single writerows + single flush per cycle.
  * --min-free-gb and --max-output-mb guards stop the poller gracefully
    (reason row, no traceback, controlled exit code) instead of filling the
    diagnostic disk. A diagnostic must not be able to exhaust the disk it
    is measuring.
"""

from __future__ import annotations

import csv
import hashlib
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

HEARTBEAT_PATH = "<heartbeat>"
POLLER_PATH = "<poller>"

CSV_COLUMNS = [
    "timestamp", "cycle", "file_path", "size_bytes",
    "mtime", "sha256", "status",
]

# Controlled CLI exit code for a guard stop (low space / size cap / I/O
# error). Distinct from 0 (clean) and 1 (unexpected traceback).
EXIT_GUARD_STOP = 3


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class FileRecord:
    """Record of a file's state."""
    path: str
    size: int
    mtime: float
    sha256: str
    first_seen: str
    last_seen: str
    status: str  # "new", "changed", "unchanged", "deleted", "error"
    mtime_ns: int = 0


class PackageWritePoller:
    """
    Polls a directory for file writes/changes at a fixed interval.

    Logs each polling cycle's delta findings to a CSV with columns:
    timestamp, cycle, file_path, size_bytes, mtime, sha256, status

    Status values: new, changed, deleted, error, heartbeat, stop:<reason>.
    "unchanged" appears only in the in-memory snapshot, never in the CSV.

    Does not start/stop the cook process - only observes the output directory.
    """

    def __init__(
        self,
        package_dir: str | Path,
        output_csv: str | Path,
        interval_sec: float = 5.0,
        *,
        follow_symlinks: bool = False,
        heartbeat: bool = True,
        min_free_gb: float = 1.0,
        max_output_mb: float = 100.0,
    ):
        self.package_dir = Path(package_dir).resolve()
        self.output_csv = Path(output_csv).resolve()
        self.interval_sec = interval_sec
        self.follow_symlinks = follow_symlinks
        self.heartbeat = heartbeat
        self.min_free_gb = float(min_free_gb)
        self.max_output_mb = float(max_output_mb)

        self._known_files: Dict[str, FileRecord] = {}
        self._cycle = 0
        self._running = False
        self._csv_file: Optional[csv.writer] = None
        self._csv_handle = None
        self.stop_reason: str = ""
        # (path, error-signature) pairs already emitted: repeat errors stay
        # in the snapshot but are not re-emitted every cycle.
        self._emitted_errors: set = set()
        # Diagnostic counters (also used by tests).
        self.stats: Dict[str, int] = {
            "hash_calls": 0,
            "rows_written": 0,
            "flush_calls": 0,
            "cycles": 0,
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _compute_sha256(self, path: Path) -> str:
        """Compute SHA256 of a file. Counts calls for diagnostics."""
        self.stats["hash_calls"] += 1
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
        except (OSError, IOError) as exc:
            return f"ERROR:{type(exc).__name__}"
        return h.hexdigest()

    def _free_gb(self) -> Optional[float]:
        """Free GiB on the CSV volume. None when undeterminable."""
        try:
            anchor = self.output_csv.parent
            anchor.mkdir(parents=True, exist_ok=True)
            return shutil.disk_usage(anchor).free / (1024 ** 3)
        except OSError:
            return None

    def _output_mb(self) -> float:
        try:
            return self.output_csv.stat().st_size / (1024 ** 2)
        except OSError:
            return 0.0

    def _scan_directory(self) -> Dict[str, FileRecord]:
        """Metadata-first scan. Hashes only new or metadata-changed files."""
        current: Dict[str, FileRecord] = {}
        now = _utc_now()

        if not self.package_dir.exists():
            return current

        for path in self.package_dir.rglob("*"):
            if not path.is_file():
                continue
            if not self.follow_symlinks and path.is_symlink():
                continue
            try:
                stat = path.stat()
            except (OSError, IOError):
                continue
            # Use forward slashes for consistency across platforms
            rel_path = str(path.relative_to(self.package_dir)).replace("\\", "/")
            prev = self._known_files.get(rel_path)
            size = stat.st_size
            mtime_ns = stat.st_mtime_ns
            mtime = stat.st_mtime
            if prev is not None and prev.size == size and prev.mtime_ns == mtime_ns:
                # Metadata identical: reuse stored hash, no re-hash.
                current[rel_path] = FileRecord(
                    path=rel_path, size=size, mtime=mtime,
                    sha256=prev.sha256, first_seen=prev.first_seen,
                    last_seen=now, status="unchanged", mtime_ns=mtime_ns,
                )
                continue
            sha = self._compute_sha256(path)
            if sha.startswith("ERROR:"):
                # Repeat errors stay in the snapshot; poll_once() emits each
                # distinct (path, error) only once via _emitted_errors.
                current[rel_path] = FileRecord(
                    path=rel_path, size=size, mtime=mtime,
                    sha256=sha, first_seen=(prev.first_seen if prev else now),
                    last_seen=now, status="error", mtime_ns=mtime_ns,
                )
            elif prev is None:
                current[rel_path] = FileRecord(
                    path=rel_path, size=size, mtime=mtime,
                    sha256=sha, first_seen=now,
                    last_seen=now, status="new", mtime_ns=mtime_ns,
                )
            else:
                current[rel_path] = FileRecord(
                    path=rel_path, size=size, mtime=mtime,
                    sha256=sha, first_seen=prev.first_seen,
                    last_seen=now, status="changed", mtime_ns=mtime_ns,
                )
        return current

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------
    def _write_csv_header(self) -> None:
        """Write CSV header if file is new/empty."""
        self.output_csv.parent.mkdir(parents=True, exist_ok=True)
        self._csv_handle = open(self.output_csv, "a", newline="", encoding="utf-8")
        self._csv_file = csv.writer(self._csv_handle)
        if self.output_csv.stat().st_size == 0:
            self._csv_file.writerow(CSV_COLUMNS)

    def _flush(self) -> None:
        if self._csv_handle:
            try:
                self._csv_handle.flush()
                self.stats["flush_calls"] += 1
            except OSError:
                pass

    def _row(self, record: FileRecord, cycle: int, now: str) -> List[str]:
        return [now, str(cycle), record.path, str(record.size),
                repr(record.mtime), record.sha256, record.status]

    # ------------------------------------------------------------------
    # cycle
    # ------------------------------------------------------------------
    def _guard_stop(self, reason: str, rows: List[List[str]], now: str) -> bool:
        """Append a stop row. Returns False (no further writes this cycle)."""
        self.stop_reason = reason
        rows.append([now, str(self._cycle), POLLER_PATH, "0",
                     repr(time.time()), "", f"stop:{reason}"])
        return False

    def poll_once(self) -> Dict[str, FileRecord]:
        """Perform one polling cycle. Returns current file states."""
        if self._csv_handle is None:
            self._write_csv_header()

        self._cycle += 1
        now = _utc_now()
        try:
            current = self._scan_directory()
        except OSError:
            # Scan itself failed (e.g. volume vanished): stop gracefully.
            self.stop_reason = "scan_error"
            self.stop()
            return {}

        rows: List[List[str]] = []
        new_n = changed_n = deleted_n = error_n = 0
        for rel_path, record in current.items():
            if record.status == "unchanged":
                continue
            if record.status == "error":
                ekey = (rel_path, record.sha256)
                if ekey in self._emitted_errors:
                    continue
                self._emitted_errors.add(ekey)
            rows.append(self._row(record, self._cycle, now))
            if record.status == "new":
                new_n += 1
            elif record.status == "changed":
                changed_n += 1
            elif record.status == "error":
                error_n += 1

        # Deleted: in snapshot, absent now. Emit once, then forget.
        for rel_path, prev in self._known_files.items():
            if rel_path not in current:
                rows.append([now, str(self._cycle), rel_path, str(prev.size),
                             repr(prev.mtime), prev.sha256, "deleted"])
                deleted_n += 1

        keep_writing = True
        if self.heartbeat:
            rows.append([now, str(self._cycle), HEARTBEAT_PATH,
                         str(len(current)), repr(time.time()), "",
                         "heartbeat"])

        # Disk guards BEFORE the single write.
        free_gb = self._free_gb()
        if free_gb is not None and free_gb < self.min_free_gb:
            keep_writing = self._guard_stop("low_space", rows, now)
            rows = rows[-1:]
        elif self._output_mb() >= self.max_output_mb:
            keep_writing = self._guard_stop("size_cap", rows, now)

        try:
            if rows and self._csv_file:
                self._csv_file.writerows(rows)
                self.stats["rows_written"] += len(rows)
            self._flush()
        except OSError:
            self.stop_reason = self.stop_reason or "write_error"
            self.stop()
            return current

        self.stats["cycles"] += 1
        if not keep_writing:
            self.stop()
        else:
            # Forget deleted files only after their row was attempted.
            self._known_files = current
        return current

    def run(self, max_cycles: Optional[int] = None) -> int:
        """
        Run polling loop until max_cycles reached or stopped.

        Returns 0 on clean completion, EXIT_GUARD_STOP (3) on a guard stop.
        Never raises OSError from guard conditions: a diagnostic must not
        crash its parent on storage pressure.
        """
        self._running = True
        try:
            self._write_csv_header()
        except OSError as exc:
            print(f"poller: cannot open output csv: {exc}")
            return EXIT_GUARD_STOP

        try:
            while self._running:
                if max_cycles is not None and self._cycle >= max_cycles:
                    self.stop_reason = self.stop_reason or "max_cycles"
                    break
                try:
                    self.poll_once()
                except OSError as exc:
                    self.stop_reason = self.stop_reason or f"cycle_error:{type(exc).__name__}"
                    break
                if self.stop_reason in ("low_space", "size_cap", "write_error", "scan_error"):
                    break
                if self.interval_sec > 0:
                    time.sleep(self.interval_sec)
        except KeyboardInterrupt:
            self.stop_reason = self.stop_reason or "interrupted"
            print("\nStopped by user")
        finally:
            self.stop()
        if self.stop_reason in ("low_space", "size_cap", "write_error", "scan_error") or \
                self.stop_reason.startswith("cycle_error"):
            print(f"poller: guard stop ({self.stop_reason})")
            return EXIT_GUARD_STOP
        return 0

    def stop(self) -> None:
        """Stop the poller and close CSV."""
        self._running = False
        if self._csv_handle:
            try:
                self._csv_handle.close()
            except OSError:
                pass
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
    import sys

    parser = argparse.ArgumentParser(description="Package write poller for cook diagnostics")
    parser.add_argument("--package-dir", required=True, help="Package output directory to watch")
    parser.add_argument("--output-csv", required=True, help="CSV output path")
    parser.add_argument("--interval", type=float, default=5.0, help="Poll interval in seconds")
    parser.add_argument("--max-cycles", type=int, help="Maximum poll cycles (default: infinite)")
    parser.add_argument("--follow-symlinks", action="store_true", help="Follow symlinks")
    parser.add_argument("--no-heartbeat", action="store_true", help="Disable per-cycle heartbeat row")
    parser.add_argument("--min-free-gb", type=float, default=1.0,
                        help="Stop gracefully below this free GiB on the CSV volume")
    parser.add_argument("--max-output-mb", type=float, default=100.0,
                        help="Stop gracefully once the CSV reaches this size in MiB")

    args = parser.parse_args()

    poller = PackageWritePoller(
        package_dir=args.package_dir,
        output_csv=args.output_csv,
        interval_sec=args.interval,
        follow_symlinks=args.follow_symlinks,
        heartbeat=not args.no_heartbeat,
        min_free_gb=args.min_free_gb,
        max_output_mb=args.max_output_mb,
    )

    code = poller.run(max_cycles=args.max_cycles)
    print(f"Completed {poller.get_cycle_count()} cycles "
          f"(reason={poller.stop_reason or 'ok'}). Output: {args.output_csv}")
    sys.exit(code)
