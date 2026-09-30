"""Frame synchronisation and capture completeness (NEW-261 / NEW-262).

Scientific frame count is **not** the number of files on disk.

    6 cameras x 4 frames = 24 PNG files  ->  4 complete frames

``complete_frames`` is the size of the intersection of the frame-ID sets of
every *required* sensor.  A capture is complete only when
``complete_frames >= requested_frames`` (and preferably exactly the governed
requested set).

This module is pure stdlib and side-effect-light so it can be unit-tested and
reused by the recorder, the contract engine and the dataset verifier.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
LIDAR_EXTS = {".npz", ".ply", ".bin"}

DEFAULT_FRAME_ID_RE = r"(\d{4,})"


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def extract_frame_id(path: Any, pattern: str = DEFAULT_FRAME_ID_RE) -> Optional[int]:
    """Pull the frame id out of a recorded filename.

    Recorder output uses ``<name>/<frame>.png`` style names; the last
    digit-run in the stem is the frame id.
    """
    stem = Path(str(path)).stem
    matches = re.findall(pattern, stem)
    if not matches:
        return _as_int(stem)
    return _as_int(matches[-1])


def collect_frame_ids(
    directory: Any,
    *,
    recursive: bool = True,
    exts: Optional[Iterable[str]] = None,
    pattern: str = DEFAULT_FRAME_ID_RE,
) -> Tuple[Set[int], List[str]]:
    """Return ``(frame_ids, files)`` for files under ``directory``."""
    root = Path(str(directory))
    allowed = {str(e).lower() if str(e).startswith(".") else f".{str(e).lower()}" for e in (exts or set())}
    if not allowed:
        allowed = set(IMAGE_EXTS) | set(LIDAR_EXTS)
    files: List[str] = []
    frame_ids: Set[int] = set()
    if not root.exists():
        return frame_ids, files
    iterator = root.rglob("*") if recursive else root.glob("*")
    for item in sorted(iterator):
        if not item.is_file():
            continue
        if item.suffix.lower() not in allowed:
            continue
        files.append(str(item))
        fid = extract_frame_id(item, pattern)
        if fid is not None:
            frame_ids.add(fid)
    return frame_ids, files


def build_required_frame_sets(
    sensor_frame_ids: Mapping[str, Iterable[int]],
    required_sensors: Optional[Sequence[str]] = None,
) -> Dict[str, Set[int]]:
    """Normalise to ``required_frame_sets`` restricted to required sensors."""
    if required_sensors is None:
        keys = list(sensor_frame_ids.keys())
    else:
        keys = [str(k) for k in required_sensors]
    return {name: set(int(f) for f in (sensor_frame_ids.get(name) or set())) for name in keys}


def common_frame_ids(required_frame_sets: Mapping[str, Set[int]]) -> Set[int]:
    """Intersection over every required sensor's frame-id set."""
    sets = [set(v) for v in required_frame_sets.values()]
    if not sets:
        return set()
    result = set(sets[0])
    for other in sets[1:]:
        result &= other
    return result


def evaluate_capture_completeness(
    sensor_frame_ids: Mapping[str, Iterable[int]],
    *,
    required_sensors: Optional[Sequence[str]] = None,
    requested_frames: int,
    exact_set_required: bool = False,
    expected_frame_ids: Optional[Iterable[int]] = None,
) -> Dict[str, Any]:
    """Compute the scientific completeness verdict for a capture."""
    required = build_required_frame_sets(sensor_frame_ids, required_sensors)
    requested = int(requested_frames)

    empty_required = sorted(name for name, ids in required.items() if not ids)
    common = common_frame_ids(required)
    complete_frames = len(common)

    missing_sensors = sorted(name for name in required if name not in sensor_frame_ids)

    reasons: List[str] = []
    if not required:
        reasons.append("no_required_sensors_declared")
    if missing_sensors:
        reasons.append(f"required_sensors_absent:{','.join(missing_sensors)}")
    if empty_required:
        reasons.append(f"required_sensor_zero_frames:{','.join(empty_required)}")
    if complete_frames < requested:
        reasons.append(f"complete_frames_below_requested:{complete_frames}<{requested}")

    expected_sorted: Optional[List[int]] = None
    if expected_frame_ids is not None:
        expected_sorted = sorted(int(f) for f in expected_frame_ids)
        if complete_frames != len(expected_sorted):
            reasons.append(f"complete_frames_not_exact:{complete_frames}!={len(expected_sorted)}")
        elif sorted(common) != expected_sorted:
            reasons.append("complete_frame_set_differs_from_governed_set")
    elif exact_set_required and complete_frames != requested:
        reasons.append(f"complete_frames_not_exact:{complete_frames}!={requested}")

    total_files = sum(len(set(int(f) for f in ids)) for ids in required.values())
    verdict = "PASS" if not reasons else "FAIL"

    return {
        "schema": "CAPTURE_COMPLETENESS/v1",
        "verdict": verdict,
        "complete_frames": complete_frames,
        "requested_frames": requested,
        "total_sensor_frames_sum": total_files,
        "required_sensors": sorted(required.keys()),
        "required_frame_sets": {k: sorted(v) for k, v in sorted(required.items())},
        "common_frame_ids": sorted(common),
        "empty_required_sensors": empty_required,
        "missing_required_sensors": missing_sensors,
        "per_sensor_counts": {k: len(v) for k, v in sorted(required.items())},
        "reasons": reasons,
        "counting_policy": (
            "complete_frames = |intersection of frame-id sets of every required sensor|; "
            "file totals are never used as the scientific frame count."
        ),
        "adversarial_note": (
            "6 cameras x 4 frames = 24 files must remain 4 complete frames; "
            "equal counts with disjoint frame ids intersect to 0 and FAIL."
        ),
    }


def build_frame_correspondence(
    sensor_paths: Mapping[str, Mapping[int, Any]],
    *,
    required_sensors: Optional[Sequence[str]] = None,
    complete_only: bool = True,
) -> Dict[str, Any]:
    """Build ``frame_correspondence.json`` content.

    ``sensor_paths`` maps sensor name -> {frame_id: relative path}.
    """
    sensors = [str(s) for s in (required_sensors or sensor_frame_ids_keys(sensor_paths))]
    required_sets = {
        name: set(sensor_paths.get(name, {}).keys()) for name in sensors if name in sensor_paths
    }
    common = common_frame_ids(required_sets) if required_sets else set()

    rows: List[Dict[str, Any]] = []
    frames = sorted(common) if complete_only else sorted(
        set().union(*required_sets.values()) if required_sets else set()
    )
    for frame in frames:
        row: Dict[str, Any] = {"frame": int(frame), "complete": int(frame) in common}
        for name in sensors:
            path = sensor_paths.get(name, {}).get(frame)
            row[name] = str(path) if path is not None else None
        rows.append(row)

    incomplete = [r for r in rows if not r.get("complete")]
    return {
        "schema": "FRAME_CORRESPONDENCE/v1",
        "sensors": sensors,
        "complete_frames": len(common),
        "rows": rows,
        "incomplete_rows": incomplete,
        "rejections": {
            "same_file_count_different_frame_ids": True,
            "note": (
                "Equal file counts with disjoint frame IDs are rejected: only the "
                "frame-id intersection defines a complete frame."
            ),
        },
    }


def sensor_frame_ids_keys(sensor_paths: Mapping[str, Mapping[int, Any]]) -> List[str]:
    return list(sensor_paths.keys())


def scan_recording_directory(
    recording_dir: Any,
    *,
    sensor_dirs: Optional[Mapping[str, Any]] = None,
    required_sensors: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[int, str]]:
    """Discover ``{sensor: {frame_id: path}}`` for a recording directory.

    When ``sensor_dirs`` is provided it maps sensor name -> directory; otherwise
    the two-level layout ``<recording>/<kind>/<sensor>/<file>`` is walked.
    """
    root = Path(str(recording_dir))
    result: Dict[str, Dict[int, str]] = {}

    if sensor_dirs:
        for name, directory in sensor_dirs.items():
            ids, files = collect_frame_ids(directory)
            mapping: Dict[int, str] = {}
            for file in files:
                fid = extract_frame_id(file)
                if fid is not None:
                    mapping[fid] = str(Path(file).relative_to(root)) if Path(file).is_relative_to(root) else str(file)
            result[str(name)] = mapping
        return result

    if not root.exists():
        return result

    # Layout: <root>/<kind>/<sensor_name>/<file>
    for kind_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for sensor_dir in sorted(p for p in kind_dir.iterdir() if p.is_dir()):
            ids, files = collect_frame_ids(sensor_dir, recursive=False)
            mapping = {}
            for file in files:
                fid = extract_frame_id(file)
                if fid is not None:
                    mapping[fid] = str(Path(file).relative_to(root))
            if mapping:
                result[sensor_dir.name] = mapping
    if required_sensors:
        for name in required_sensors:
            result.setdefault(str(name), {})
    return result


def write_frame_correspondence(payload: Mapping[str, Any], path: Any) -> Path:
    target = Path(str(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def assert_capture_complete(report: Mapping[str, Any]) -> None:
    if str(report.get("verdict")) != "PASS":
        raise RuntimeError(
            "capture_incomplete:"
            f"complete_frames={report.get('complete_frames')}:"
            f"requested_frames={report.get('requested_frames')}:"
            f"reasons={report.get('reasons')}"
        )
