"""Comprehensive crash bundle + exact failure classification (section 17).

On every governed capture failure a ``crash_bundle/`` directory is produced
with a fixed, complete file set.  Classification uses exactly the closed
vocabulary required by the campaign.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Closed classification vocabulary
# ---------------------------------------------------------------------------

STATIC_XODR_FAILURE = "STATIC_XODR_FAILURE"
LENGTH_ASSERT = "LENGTH_ASSERT"
MAP_LOAD_ENGINE_EXIT = "MAP_LOAD_ENGINE_EXIT"
MAP_LOAD_TIMEOUT = "MAP_LOAD_TIMEOUT"
WRONG_MAP = "WRONG_MAP"
RUNTIME_MAP_IDENTITY_MISMATCH = "RUNTIME_MAP_IDENTITY_MISMATCH"
POSTLOAD_STALL = "POSTLOAD_STALL"
GPU_OOM = "GPU_OOM"
HOST_OOM = "HOST_OOM"
EGO_SPAWN_FAILURE = "EGO_SPAWN_FAILURE"
SENSOR_SPAWN_TIMEOUT = "SENSOR_SPAWN_TIMEOUT"
LISTENER_FAILURE = "LISTENER_FAILURE"
FIRST_FRAME_TIMEOUT = "FIRST_FRAME_TIMEOUT"
STREAMING_COLLAPSE = "STREAMING_COLLAPSE"
TICK_STALL = "TICK_STALL"
WRITER_BACKLOG = "WRITER_BACKLOG"
FRAME_ALIGNMENT_FAILURE = "FRAME_ALIGNMENT_FAILURE"
ASENSOR_ENDPLAY_CRASH = "ASENSOR_ENDPLAY_CRASH"
TEARDOWN_FAILURE = "TEARDOWN_FAILURE"
UNKNOWN_ENGINE_FATAL = "UNKNOWN_ENGINE_FATAL"

FAILURE_CLASSES: tuple = (
    STATIC_XODR_FAILURE,
    LENGTH_ASSERT,
    MAP_LOAD_ENGINE_EXIT,
    MAP_LOAD_TIMEOUT,
    WRONG_MAP,
    RUNTIME_MAP_IDENTITY_MISMATCH,
    POSTLOAD_STALL,
    GPU_OOM,
    HOST_OOM,
    EGO_SPAWN_FAILURE,
    SENSOR_SPAWN_TIMEOUT,
    LISTENER_FAILURE,
    FIRST_FRAME_TIMEOUT,
    STREAMING_COLLAPSE,
    TICK_STALL,
    WRITER_BACKLOG,
    FRAME_ALIGNMENT_FAILURE,
    ASENSOR_ENDPLAY_CRASH,
    TEARDOWN_FAILURE,
    UNKNOWN_ENGINE_FATAL,
)

#: Bundle files that must exist for every crash bundle.
REQUIRED_BUNDLE_FILES: tuple = (
    "phase_journal.jsonl",
    "failure_classification.json",
    "map_identity.json",
    "runtime_xodr_identity.json",
    "CARLA_log_tail.txt",
    "client_stdout.txt",
    "client_stderr.txt",
    "resource_samples.jsonl",
    "world_settings.json",
    "actor_inventory.json",
    "sensor_inventory.json",
    "sensor_spawn_trace.jsonl",
    "frame_correspondence_partial.json",
    "writer_queue_status.json",
    "RPC_status.json",
)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_RULES: Sequence[tuple] = (
    (STATIC_XODR_FAILURE, ("static_xodr", "xodr_static", "opendrive_parse", "static validation")),
    (LENGTH_ASSERT, ("length_assert", "length assert", "check failed: .*length", "assertionfailed:length")),
    (GPU_OOM, ("out of video memory", "cuda out of memory", "d3d11: could not allocate", "vram", "oom_gpu", "gpumem")),
    (HOST_OOM, ("out of memory", "std::bad_alloc", "memory allocation failed", "oom_host", "pagefile")),
    (MAP_LOAD_TIMEOUT, ("map_load_timeout", "load timeout", "timed out.*load", "opendrive_load_timeout")),
    (MAP_LOAD_ENGINE_EXIT, ("engine exit", "process exited", "carla process died", "exit code", "engine crash")),
    (WRONG_MAP, ("wrong_map", "wrong map", "map mismatch", "unexpected map")),
    (RUNTIME_MAP_IDENTITY_MISMATCH, ("runtime_map_identity", "structural fingerprint", "layer2", "identity_mismatch")),
    (POSTLOAD_STALL, ("postload_stall", "post-load stall", "soak failed", "MAP_LOADED without soak")),
    (EGO_SPAWN_FAILURE, ("ego_spawn", "ego spawn", "spawn_failed", "failed to spawn ego")),
    (SENSOR_SPAWN_TIMEOUT, ("sensor_spawn_timeout", "thesis_rig_spawn_timeout", "spawn timeout")),
    (LISTENER_FAILURE, ("listen_failed", "listener", "pre_spawn_stream_unavailable")),
    (FIRST_FRAME_TIMEOUT, ("first_frame_timeout", "first frame timeout", "first_measurement", "no frames received")),
    (STREAMING_COLLAPSE, ("streaming_collapse", "streaming collapse", "stream port not open", "callbacks may not fire")),
    (TICK_STALL, ("tick_stall", "world not ticking", "non_advancing_tick", "tick_watchdog")),
    (WRITER_BACKLOG, ("writer_backlog", "writer_queue_full", "writer_submit_failed", "queue_depth")),
    (FRAME_ALIGNMENT_FAILURE, ("frame_alignment", "frame intersection", "complete_frames", "frame correspondence")),
    (ASENSOR_ENDPLAY_CRASH, ("asensor", "endplay", "on_sensor_end_play")),
    (TEARDOWN_FAILURE, ("teardown_failure", "destroy_timeout", "cleanup failed")),
)

#: Ordered fallback: longest/most specific textual hint wins.
_TEXTUAL_HINTS: Sequence[tuple] = (
    (STATIC_XODR_FAILURE, ("static_xodr", "xodr parse", "opendrive parse")),
    (LENGTH_ASSERT, ("lengthassert", "length assert")),
    (GPU_OOM, ("out of video memory", "cuda out of memory", "oom_gpu")),
    (HOST_OOM, ("std::bad_alloc", "out of memory", "oom_host")),
    (MAP_LOAD_TIMEOUT, ("map_load_timeout", "opendrive_load_timeout")),
    (MAP_LOAD_ENGINE_EXIT, ("map_load_engine_exit", "engine_exit", "engine exit")),
    (WRONG_MAP, ("wrong_map_loaded", "wrong_map")),
    (RUNTIME_MAP_IDENTITY_MISMATCH, ("runtime_map_identity_mismatch", "structural_mismatch")),
    (POSTLOAD_STALL, ("postload_stall", "postload_stability_gate_failed")),
    (EGO_SPAWN_FAILURE, ("ego_spawn_failure", "ego_spawn_failed")),
    (SENSOR_SPAWN_TIMEOUT, ("sensor_spawn_timeout", "thesis_rig_spawn_timeout")),
    (LISTENER_FAILURE, ("listener_failure", "listen_failed", "pre_spawn_stream_unavailable")),
    (FIRST_FRAME_TIMEOUT, ("first_frame_timeout", "first_measurement_no_callbacks")),
    (STREAMING_COLLAPSE, ("streaming_collapse", "streaming collapse")),
    (TICK_STALL, ("tick_stall", "world_not_ticking")),
    (WRITER_BACKLOG, ("writer_backlog", "writer_queue_full", "writer_submit_failed")),
    (FRAME_ALIGNMENT_FAILURE, ("frame_alignment_failure", "capture_incomplete", "frame_alignment")),
    (ASENSOR_ENDPLAY_CRASH, ("asensor_endplay_crash", "endplay")),
    (TEARDOWN_FAILURE, ("teardown_failure", "destroy_timeout")),
    (MAP_LOAD_ENGINE_EXIT, ("carla process", "exit code")),
    (UNKNOWN_ENGINE_FATAL, ()),
)


def classify_failure(
    *,
    reason: Optional[str] = None,
    text: Optional[str] = None,
    stage: Optional[str] = None,
    journal_tail: Optional[Iterable[Mapping[str, Any]]] = None,
    writer_errors: Optional[Sequence[str]] = None,
    explicit: Optional[str] = None,
) -> Dict[str, Any]:
    """Map an observed failure onto the closed classification vocabulary."""
    if explicit:
        label = str(explicit)
        if label in FAILURE_CLASSES:
            return {
                "schema": "FAILURE_CLASSIFICATION/v1",
                "classification": label,
                "matched_by": "explicit",
                "reason": reason,
                "stage": stage,
            }

    haystack_parts: List[str] = []
    for value in (reason, text, stage):
        if value:
            haystack_parts.append(str(value))
    for item in writer_errors or ():
        haystack_parts.append(str(item))
    for entry in journal_tail or ():
        if isinstance(entry, Mapping):
            haystack_parts.append(" ".join(f"{k}={v}" for k, v in entry.items()))
    haystack = "\n".join(haystack_parts).lower()

    for label, hints in _TEXTUAL_HINTS:
        for hint in hints:
            if hint and str(hint).lower() in haystack:
                return {
                    "schema": "FAILURE_CLASSIFICATION/v1",
                    "classification": label,
                    "matched_by": f"text:{hint}",
                    "reason": reason,
                    "stage": stage,
                }

    if stage:
        stage_map = {
            "MAP_LOAD": MAP_LOAD_ENGINE_EXIT,
            "EGO_SPAWN": EGO_SPAWN_FAILURE,
            "SENSOR_SPAWN": SENSOR_SPAWN_TIMEOUT,
            "LISTEN": LISTENER_FAILURE,
            "FIRST_SAMPLE": FIRST_FRAME_TIMEOUT,
            "CAPTURE": STREAMING_COLLAPSE,
            "FLUSH": WRITER_BACKLOG,
            "TEARDOWN": TEARDOWN_FAILURE,
        }
        for token, label in stage_map.items():
            if token.lower() in str(stage).lower():
                return {
                    "schema": "FAILURE_CLASSIFICATION/v1",
                    "classification": label,
                    "matched_by": f"stage:{stage}",
                    "reason": reason,
                    "stage": stage,
                }

    return {
        "schema": "FAILURE_CLASSIFICATION/v1",
        "classification": UNKNOWN_ENGINE_FATAL,
        "matched_by": "fallback",
        "reason": reason,
        "stage": stage,
        "note": "no rule matched; classified as UNKNOWN_ENGINE_FATAL rather than silently dropped",
    }


# ---------------------------------------------------------------------------
# Bundle writer
# ---------------------------------------------------------------------------


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", errors="replace")
    tmp.replace(path)


def _atomic_write_json(path: Path, payload: Any) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def _tail(path: Any, lines: int = 400) -> str:
    target = Path(str(path)) if path else None
    if target is None or not target.exists():
        return ""
    try:
        content = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    return "\n".join(content[-lines:])


def write_crash_bundle(
    out_dir: Any,
    *,
    reason: Optional[str] = None,
    stage: Optional[str] = None,
    explicit_classification: Optional[str] = None,
    phase_journal_path: Any = None,
    map_identity: Optional[Mapping[str, Any]] = None,
    runtime_xodr_identity: Optional[Mapping[str, Any]] = None,
    world_settings: Optional[Mapping[str, Any]] = None,
    actor_inventory: Optional[Mapping[str, Any]] = None,
    sensor_inventory: Optional[Mapping[str, Any]] = None,
    sensor_spawn_trace: Optional[Sequence[Mapping[str, Any]]] = None,
    frame_correspondence_partial: Optional[Mapping[str, Any]] = None,
    writer_queue_status: Optional[Mapping[str, Any]] = None,
    rpc_status: Optional[Mapping[str, Any]] = None,
    resource_samples: Optional[Sequence[Mapping[str, Any]]] = None,
    carla_log_path: Any = None,
    client_stdout_path: Any = None,
    client_stderr_path: Any = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Materialise ``<out_dir>/crash_bundle/`` with the required file set."""
    bundle = Path(str(out_dir)) / "crash_bundle"
    bundle.mkdir(parents=True, exist_ok=True)

    journal_text = ""
    journal_records: List[Any] = []
    if phase_journal_path and Path(str(phase_journal_path)).exists():
        journal_text = Path(str(phase_journal_path)).read_text(encoding="utf-8", errors="replace")
        journal_records = [ln for ln in journal_text.splitlines() if ln.strip()]
    _atomic_write_text(bundle / "phase_journal.jsonl", journal_text)

    classification = classify_failure(
        reason=reason,
        stage=stage,
        explicit=explicit_classification,
        journal_tail=[
            json.loads(ln) for ln in journal_records[-200:] if ln.startswith("{")
        ][:200],
        writer_errors=list((writer_queue_status or {}).get("errors", []) or []),
    )
    classification["reason"] = reason
    classification["stage"] = stage
    classification["bundle_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if extra:
        classification["extra"] = dict(extra)
    _atomic_write_json(bundle / "failure_classification.json", classification)

    _atomic_write_json(bundle / "map_identity.json", map_identity or {"status": "NOT_PROVIDED"})
    _atomic_write_json(
        bundle / "runtime_xodr_identity.json",
        runtime_xodr_identity or {"status": "NOT_PROVIDED"},
    )
    _atomic_write_text(bundle / "CARLA_log_tail.txt", _tail(carla_log_path))
    _atomic_write_text(bundle / "client_stdout.txt", _tail(client_stdout_path))
    _atomic_write_text(bundle / "client_stderr.txt", _tail(client_stderr_path))

    resource_lines = []
    for sample in resource_samples or ():
        resource_lines.append(json.dumps(sample, sort_keys=True, default=str))
    _atomic_write_text(bundle / "resource_samples.jsonl", "\n".join(resource_lines))

    _atomic_write_json(bundle / "world_settings.json", world_settings or {"status": "NOT_PROVIDED"})
    _atomic_write_json(bundle / "actor_inventory.json", actor_inventory or {"status": "NOT_PROVIDED"})
    _atomic_write_json(bundle / "sensor_inventory.json", sensor_inventory or {"status": "NOT_PROVIDED"})

    spawn_lines = [
        json.dumps(item, sort_keys=True, default=str) for item in sensor_spawn_trace or ()
    ]
    _atomic_write_text(bundle / "sensor_spawn_trace.jsonl", "\n".join(spawn_lines))

    _atomic_write_json(
        bundle / "frame_correspondence_partial.json",
        frame_correspondence_partial or {"status": "NOT_PROVIDED"},
    )
    _atomic_write_json(
        bundle / "writer_queue_status.json",
        writer_queue_status or {"status": "NOT_PROVIDED"},
    )
    _atomic_write_json(bundle / "RPC_status.json", rpc_status or {"status": "NOT_PROVIDED"})

    present = sorted(p.name for p in bundle.iterdir() if p.is_file())
    missing = sorted(set(REQUIRED_BUNDLE_FILES) - set(present))
    index = {
        "schema": "CRASH_BUNDLE_INDEX/v1",
        "bundle_dir": str(bundle),
        "classification": classification["classification"],
        "required_files": list(REQUIRED_BUNDLE_FILES),
        "present_files": present,
        "missing_files": missing,
        "complete": not missing,
        "utc": classification["bundle_utc"],
    }
    _atomic_write_json(bundle / "crash_bundle_index.json", index)
    return index


def iter_failure_classes() -> Sequence[str]:
    return FAILURE_CLASSES
