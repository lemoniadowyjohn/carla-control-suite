"""Atomic crash-phase diagnostics (NEW-268).

Spawn-phase evidence written with best-effort JSON rewrites silently loses the
one record you need when the engine dies.  This journal is append-only JSONL
with an explicit ``flush`` + ``os.fsync`` after every record, so it survives a
CARLA engine death, a process kill and an OS-level crash.

Usage::

    journal = PhaseJournal(path)
    journal.record("MAP_LOAD_BEGIN", map="Grid0828")
    ...
    journal.record("CAPTURE_END", frames=4)
    journal.close()

Optional environment probes (CARLA PID, VRAM, RSS, world frame, RPC state) are
attached automatically to every record when a probe callable is supplied.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

#: The phases the campaign requires to be journalled.
REQUIRED_PHASES: tuple = (
    "MAP_LOAD_BEGIN",
    "MAP_LOAD_RETURN",
    "POSTLOAD_STABILITY",
    "EGO_SPAWN_BEGIN",
    "EGO_SPAWN_RETURN",
    "RGB_CANARY_BEGIN",
    "RGB_CANARY_CALLBACK",
    "RIG_CAMERA_N_BEGIN",
    "RIG_CAMERA_N_RETURN",
    "RIG_LIDAR_N_BEGIN",
    "RIG_LIDAR_N_RETURN",
    "LISTEN_BEGIN",
    "FIRST_SAMPLE",
    "CAPTURE_BEGIN",
    "CAPTURE_END",
    "FLUSH_BEGIN",
    "FLUSH_END",
    "TEARDOWN_BEGIN",
    "COMPLETE",
)


def _fsync_dir(path: Path) -> None:
    """Best-effort directory fsync so the rename is durable too."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except Exception:
        return
    try:
        os.fsync(fd)
    except Exception:
        pass
    finally:
        try:
            os.close(fd)
        except Exception:
            pass


class PhaseJournal:
    """Append-only JSONL phase journal with flush/fsync per record."""

    def __init__(
        self,
        path: Any,
        *,
        probe: Optional[Callable[[], Dict[str, Any]]] = None,
        carla_pid: Optional[int] = None,
        fsync: bool = True,
        max_records: int = 100_000,
    ) -> None:
        self.path = Path(str(path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._probe = probe
        self._carla_pid = carla_pid
        self._fsync = bool(fsync)
        self._lock = threading.RLock()
        self._closed = False
        self._count = 0
        self._max_records = int(max_records)
        self._phases_seen: List[str] = []
        # Open in append mode; 'a' creates the file if missing and never
        # truncates, which is exactly the durability property we want.
        self._fh = open(self.path, "a", encoding="utf-8", buffering=1)

    # -- context manager ------------------------------------------------
    def __enter__(self) -> "PhaseJournal":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            try:
                self.record("EXCEPTION", error=f"{exc_type.__name__}:{exc}")
            except Exception:
                pass
        self.close()
        return False

    # -- probes ---------------------------------------------------------
    def _environment(self) -> Dict[str, Any]:
        env: Dict[str, Any] = {
            "carla_pid": self._carla_pid,
            "pid": os.getpid(),
        }
        if self._probe is not None:
            try:
                custom = self._probe() or {}
                for key, value in custom.items():
                    env[str(key)] = value
            except Exception as exc:
                env["probe_error"] = f"{type(exc).__name__}:{exc}"
        return env

    # -- recording ------------------------------------------------------
    def record(self, phase: str, **fields: Any) -> Dict[str, Any]:
        phase = str(phase)
        with self._lock:
            if self._closed:
                # Re-open rather than drop: a journal that refuses to write is
                # worse than one that briefly re-opens after close.
                self._fh = open(self.path, "a", encoding="utf-8", buffering=1)
                self._closed = False
            if self._count >= self._max_records:
                record = {
                    "phase": "JOURNAL_TRUNCATED",
                    "t": time.time(),
                    "t_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "dropped": self._count,
                }
                line = json.dumps(record, sort_keys=True, default=str)
                self._fh.write(line + "\n")
                self._flush()
                self.close()
                return record

            record = {
                "phase": phase,
                "seq": self._count,
                "t": time.time(),
                "t_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            record.update(self._environment())
            for key, value in fields.items():
                record[str(key)] = value

            line = json.dumps(record, sort_keys=True, default=str)
            self._fh.write(line + "\n")
            self._flush()
            self._count += 1
            self._phases_seen.append(phase)
            return record

    def _flush(self) -> None:
        try:
            self._fh.flush()
        except Exception:
            pass
        if self._fsync:
            try:
                os.fsync(self._fh.fileno())
            except Exception:
                pass

    def flush(self) -> None:
        with self._lock:
            if not self._closed:
                self._flush()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._flush()
            except Exception:
                pass
            try:
                self._fh.close()
            except Exception:
                pass
            self._closed = True

    # -- introspection --------------------------------------------------
    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def phases_seen(self) -> List[str]:
        with self._lock:
            return list(self._phases_seen)

    def missing_required_phases(self) -> List[str]:
        seen = set(self.phases_seen())
        return [p for p in REQUIRED_PHASES if p not in seen]


def read_journal(path: Any) -> List[Dict[str, Any]]:
    target = Path(str(path))
    if not target.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            records.append(json.loads(text))
        except Exception:
            records.append({"phase": "UNPARSEABLE", "raw": text[:500]})
    return records


def last_phase(path: Any) -> Optional[str]:
    records = read_journal(path)
    for record in reversed(records):
        phase = record.get("phase")
        if phase:
            return str(phase)
    return None


class NullPhaseJournal:
    """No-op stand-in so callers never need ``if journal is not None``."""

    def record(self, phase: str, **fields: Any) -> Dict[str, Any]:
        return {"phase": str(phase)}

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    def phases_seen(self) -> List[str]:
        return []

    @property
    def count(self) -> int:
        return 0

    def __enter__(self) -> "NullPhaseJournal":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False
