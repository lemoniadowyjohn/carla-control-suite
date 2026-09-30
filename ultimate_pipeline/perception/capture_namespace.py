"""Run-specific immutable capture namespaces (NEW-263).

A fresh capture must never inherit frames from a previous run.  Two concrete
defects are closed here:

1. ``SensorRecorder`` manifest arbitration used ``max(memory, disk)``; stale
   files on disk could inflate the current run's manifest.
2. ``--force-fresh-capture`` only bypassed a reuse *shortcut*; it did not give
   the run a new empty namespace, and it never deleted anything (so stale
   evidence survived silently).

Policy
------
* Every governed run gets a fresh, run-specific directory.
* If a target recording directory already contains sensor data, a fresh
  capture **refuses it** - we do not silently delete user evidence, we create a
  new namespace instead.
* ``--force-fresh-capture`` means *new empty capture namespace*.
* Manifest counts for a fresh run derive only from files created by the
  current run/session (tracked explicitly, never re-globbed over old files).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

SENSOR_DATA_SUFFIXES = (".png", ".jpg", ".jpeg", ".npz", ".ply", ".bin")

try:  # pragma: no cover - typing only
    from typing import Mapping as MappingLike  # noqa: F401
except Exception:  # pragma: no cover
    MappingLike = Dict[str, Any]  # type: ignore


def _looks_like_sensor_data(path: Path) -> bool:
    return path.suffix.lower() in SENSOR_DATA_SUFFIXES


def directory_contains_sensor_data(directory: Any, *, limit: int = 200) -> bool:
    root = Path(str(directory))
    if not root.exists():
        return False
    seen = 0
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        if _looks_like_sensor_data(item):
            return True
        seen += 1
        if seen > 5000:
            # Large non-sensor trees are not our concern; scan bounded.
            break
    return False


def existing_sensor_file_count(directory: Any) -> int:
    root = Path(str(directory))
    if not root.exists():
        return 0
    total = 0
    for item in root.rglob("*"):
        if item.is_file() and _looks_like_sensor_data(item):
            total += 1
    return total


def run_id() -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def allocate_capture_namespace(
    base_dir: Any,
    *,
    force_fresh: bool = True,
    allow_reuse: bool = False,
    reuse_receipt: Optional[MappingLike] = None,
    run_tag: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve an empty, run-specific recording directory.

    Never deletes anything.  If the preferred directory already holds sensor
    data and reuse is not explicitly authorised with a matching immutable
    receipt, a sibling ``recording_<run_id>`` namespace is allocated instead.
    """
    base = Path(str(base_dir))
    requested = base
    tag = str(run_tag or run_id())

    if allow_reuse and not force_fresh:
        if reuse_receipt and directory_contains_sensor_data(requested):
            return {
                "schema": "CAPTURE_NAMESPACE/v1",
                "mode": "REUSE_AUTHORISED",
                "directory": str(requested),
                "refused": False,
                "receipt": dict(reuse_receipt),
                "existing_sensor_files": existing_sensor_file_count(requested),
                "created": False,
                "run_id": tag,
            }

    if not directory_contains_sensor_data(requested):
        requested.mkdir(parents=True, exist_ok=True)
        return {
            "schema": "CAPTURE_NAMESPACE/v1",
            "mode": "FRESH_EMPTY",
            "directory": str(requested),
            "refused": False,
            "created": True,
            "run_id": tag,
        }

    if allow_reuse and not force_fresh and reuse_receipt is None:
        # Reuse requested but no receipt -> refuse rather than silently mix.
        pass

    # Preferred dir has data -> allocate a new namespace (no deletion).
    alternative = base.parent / f"{base.name}_{tag}"
    counter = 0
    while directory_contains_sensor_data(alternative):
        counter += 1
        alternative = base.parent / f"{base.name}_{tag}_{counter}"
        if counter > 50:
            raise RuntimeError(
                "capture_namespace_exhausted: could not allocate an empty "
                f"namespace under {base.parent}"
            )
    alternative.mkdir(parents=True, exist_ok=True)

    return {
        "schema": "CAPTURE_NAMESPACE/v1",
        "mode": "FRESH_ALLOCATED_AVOIDING_EXISTING_DATA",
        "directory": str(alternative),
        "refused_original": str(base),
        "refused_reason": "directory_already_contains_sensor_data",
        "refused": True,
        "created": True,
        "run_id": tag,
        "existing_sensor_files_in_refused_dir": existing_sensor_file_count(base),
        "deletion_performed": False,
        "note": (
            "User evidence is never deleted. A fresh capture with "
            "--force-fresh-capture allocates a NEW empty capture namespace."
        ),
    }


class RunScopedFileTracker:
    """Tracks files created by *this* run/session only.

    Replaces ``max(memory_count, disk_count)`` manifest arbitration: a fresh
    run's counts come exclusively from files this tracker observed being
    written after the run started.
    """

    def __init__(self, *, run_id_value: str, namespace: str) -> None:
        self.run_id = str(run_id_value)
        self.namespace = str(namespace)
        self._files: Dict[str, List[str]] = {}
        self._lock_note = "single-process tracker; recorder already serialises"

    def record(self, sensor_name: str, path: Any) -> None:
        key = str(sensor_name)
        self._files.setdefault(key, [])
        text = str(path)
        if text not in self._files[key]:
            self._files[key].append(text)

    def count(self, sensor_name: str) -> int:
        return len(self._files.get(str(sensor_name), []))

    def counts(self) -> Dict[str, int]:
        return {k: len(v) for k, v in sorted(self._files.items())}

    def files(self) -> Dict[str, List[str]]:
        return {k: list(v) for k, v in sorted(self._files.items())}

    def payload(self) -> Dict[str, Any]:
        return {
            "schema": "RUN_SCOPED_FILE_TRACKER/v1",
            "run_id": self.run_id,
            "namespace": self.namespace,
            "counts": self.counts(),
            "files": self.files(),
            "policy": (
                "Fresh-run manifest counts derive only from files created by the "
                "current run/session; pre-existing files are never counted."
            ),
        }
