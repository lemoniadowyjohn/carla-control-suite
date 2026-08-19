#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Verification (PowerShell):
# python -m ultimate_pipeline.perception.record_route --xodr <PATH> --out-dir .\datasets\smoke\xodr --duration 10 --fps 10 --low-mem

# ultimate_pipeline/perception/record_route.py
"""
Record a short CARLA run on an OpenDRIVE (.xodr) map using Dominik-calibrated sensors,
synchronized capture, and per-frame metadata.

Key properties:
- Import-safe (no CARLA import at module import time)
- Strict CLI validation (placeholder paths rejected; calib/xodr existence checked)
- Deterministic sync mode options
- TrafficManager configured via carla.Client(host, port) (no world.get-client)
- Supports manual towns (Grid0821/Grid0828) OR generated XODR (mutually exclusive)
- Optional low-mem mode to reduce resolution for VRAM-limited GPUs
"""

from __future__ import annotations

import argparse
import json
import os
import random
import socket
import threading
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
# NOTE: No top-level import carla (must be import-safe for pytest and offline tools)

from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup, _sanitize_transform_dict
from ultimate_pipeline.sensors.recorder import RecorderConfig, SensorRecorder

LOW_MEM_DEFAULT_RES = (960, 540)

# Sensor sanity gate thresholds (configurable via env vars)
SENSOR_SANITY_MIN_DIST_M = float(os.environ.get("UP_SENSOR_MIN_DIST_M", "0.2"))
SENSOR_SANITY_MIN_Z_M = float(os.environ.get("UP_SENSOR_MIN_Z_M", "0.3"))
SENSOR_SANITY_FORWARD_DOT_MIN = float(os.environ.get("UP_SENSOR_FORWARD_DOT_MIN", "0.2"))



_CARLA_TIMEOUT_S = 2.0
_CARLA_EXE_HINT = "Start CARLA (CarlaUE4) and ensure RPC port is reachable (default 2000)."

_WARN_ONCE: set[str] = set()


def _warn_once(msg: str) -> None:
    if msg in _WARN_ONCE:
        return
    _WARN_ONCE.add(msg)
    print(f"[WARN] {msg}")


def record_route_stage_plan(*, include_seg: bool) -> list[str]:
    """Pure stage ordering helper for tests/diagnostics (no CARLA needed)."""
    stages = [
        "carla_import",
        "preflight_rpc",
        "world_load",
        "world_tick_ready",
        "traffic_manager",
        "spawn_vehicle",
        "spawn_sensors",
        "attach_recorder",
        "run_loop",
        "teardown",
    ]
    if include_seg:
        return stages
    return stages


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None:
        return int(default)
    try:
        return int(str(v).strip())
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None:
        return float(default)
    try:
        return float(str(v).strip())
    except Exception:
        return float(default)


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return bool(default)
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _write_json(path: Path, payload: Dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_run_status(out_dir: Path, payload: Dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "run_status.json", payload)


def _status_payload(
    *,
    stage: str,
    success: bool,
    error: Optional[str] = None,
    exception: Optional[str] = None,
    traceback_text: Optional[str] = None,
    last_snapshot: Optional[Dict[str, Optional[float]]] = None,
    extra: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "stage": str(stage),
        "success": bool(success),
        "error": error,
        "exception": exception,
        "traceback": traceback_text,
    }
    if last_snapshot is not None:
        payload["last_frame_id"] = last_snapshot.get("frame")
        payload["last_elapsed_seconds"] = last_snapshot.get("elapsed_seconds")
    if extra:
        payload.update(extra)
    return payload


def _try_import_carla():
    try:
        import carla  # type: ignore
    except Exception as exc:
        return None, str(exc)
    return carla, None


def _update_run_info(path: Path, run_info: Dict[str, Any], updates: Dict[str, Any]) -> None:
    run_info.update(updates)
    _write_json(path, run_info)


def _snapshot_info(world) -> Dict[str, Optional[float]]:
    try:
        snap = world.get_snapshot()
    except Exception:
        return {"frame": None, "elapsed_seconds": None}
    frame = getattr(snap, "frame", None)
    ts = getattr(snap, "timestamp", None)
    elapsed = getattr(ts, "elapsed_seconds", None) if ts is not None else None
    return {"frame": int(frame) if frame is not None else None, "elapsed_seconds": float(elapsed) if elapsed is not None else None}


def _tick_with_timeout(world, timeout_s: float) -> Dict[str, object]:
    """Execute a world tick with timeout protection.

    Returns a dict with:
        ok: bool - whether tick succeeded
        snapshot: WorldSnapshot or None - the actual snapshot object
        frame_id: int or None - frame number (from tick() return or snapshot.frame)
        elapsed_seconds: float or None - simulation time
        sync_mode: bool - whether sync mode was used
        error: str or None - error message if failed

    IMPORTANT: In CARLA 0.9.16 synchronous mode, world.tick() returns an INT (frame_id),
    not a WorldSnapshot. We must call world.get_snapshot() separately to get the snapshot.
    In async mode, world.wait_for_tick() returns a WorldSnapshot directly.
    """
    result: Dict[str, object] = {
        "ok": False,
        "snapshot": None,
        "frame_id": None,
        "elapsed_seconds": None,
        "sync_mode": None,
        "error": None,
    }

    try:
        settings = world.get_settings()
        sync = bool(getattr(settings, "synchronous_mode", False))
        result["sync_mode"] = sync
    except Exception:
        sync = True
        result["sync_mode"] = True

    def _do_tick():
        try:
            if sync:
                # CARLA 0.9.16: world.tick() returns INT frame_id in sync mode, not WorldSnapshot
                frame_id = world.tick()
                result["frame_id"] = int(frame_id) if frame_id is not None else None
                # Get actual snapshot for timestamp info
                snap = world.get_snapshot()
                result["snapshot"] = snap
                # Extract elapsed_seconds from snapshot
                if snap is not None:
                    ts = getattr(snap, "timestamp", None)
                    if ts is not None:
                        result["elapsed_seconds"] = float(getattr(ts, "elapsed_seconds", -1.0))
                    # Verify frame_id matches snapshot (for diagnostics)
                    snap_frame = int(getattr(snap, "frame", -1))
                    if result["frame_id"] is None:
                        result["frame_id"] = snap_frame
            else:
                # CARLA 0.9.16: must use positional float, not keyword arg.
                # wait_for_tick() returns WorldSnapshot directly
                snap = world.wait_for_tick(float(timeout_s))
                result["snapshot"] = snap
                if snap is not None:
                    result["frame_id"] = int(getattr(snap, "frame", -1))
                    ts = getattr(snap, "timestamp", None)
                    if ts is not None:
                        result["elapsed_seconds"] = float(getattr(ts, "elapsed_seconds", -1.0))
            result["ok"] = True
        except Exception as exc:
            result["error"] = str(exc)

    t = threading.Thread(target=_do_tick, daemon=True)
    t.start()
    t.join(timeout=float(timeout_s))
    if t.is_alive():
        result["ok"] = False
        result["error"] = f"tick_timeout_after_{timeout_s}s"
    return result


def _tick_watchdog(
    world,
    out_dir: Path,
    *,
    timeout_s: float,
    n_ticks: int = 5,
    per_tick_s: Optional[float] = None,
    town_name: str = "",
    retries: int = 2,
) -> Dict[str, Any]:
    """Run tick watchdog with robust timeout handling for cooked towns.

    Args:
        world: CARLA world object
        out_dir: Directory to write tick_watchdog.json
        timeout_s: Total watchdog timeout (default from UP_TICK_WATCHDOG_S)
        n_ticks: Number of ticks to attempt (default 5)
        per_tick_s: Per-tick timeout (default from UP_TICK_WATCHDOG_PER_TICK_S, 15.0)
        town_name: Town/map name for diagnostics
        retries: Number of retry attempts if first pass fails

    Returns:
        Dict with watchdog results (always written to tick_watchdog.json)

    Raises:
        RuntimeError if ticks don't advance after all retries
    """
    timeout_s = float(max(1.0, timeout_s))
    n_ticks = int(max(1, n_ticks))

    # Per-tick timeout: configurable, no hard cap to 2s
    # Default 15s - cooked towns (Grid0828/0821) can need 10-15s for first sync ticks
    if per_tick_s is None:
        per_tick_s = float(os.environ.get("UP_TICK_WATCHDOG_PER_TICK_S", "15.0"))
    per_tick_s = float(max(1.0, per_tick_s))

    # Get world settings for diagnostics
    try:
        settings = world.get_settings()
        sync_mode = bool(getattr(settings, "synchronous_mode", False))
        fixed_delta = float(getattr(settings, "fixed_delta_seconds", 0.0))
    except Exception:
        sync_mode = None
        fixed_delta = None

    # Try map name from world if not provided
    if not town_name:
        try:
            town_name = world.get_map().name
        except Exception:
            town_name = "unknown"

    payload: Dict[str, Any] = {
        "schema_version": 2,
        "timeout_s": float(timeout_s),
        "per_tick_s": float(per_tick_s),
        "ticks_requested": int(n_ticks),
        "retries_allowed": int(retries),
        "town_name": str(town_name),
        "synchronous_mode": sync_mode,
        "fixed_delta_seconds": fixed_delta,
        "attempts": [],
        "final_result": "pending",
    }

    advanced = False
    last_error = None

    for attempt in range(retries + 1):
        attempt_data: Dict[str, Any] = {
            "attempt": attempt + 1,
            "frames": [],
            "elapsed_seconds": [],
            "tick_durations_s": [],
            "errors": [],
        }
        start = time.time()

        for tick_idx in range(n_ticks):
            remaining = max(1.0, timeout_s - (time.time() - start))
            tick_timeout = min(per_tick_s, remaining)

            tick_start = time.time()
            tick_result = _tick_with_timeout(world, timeout_s=tick_timeout)
            tick_duration = time.time() - tick_start
            attempt_data["tick_durations_s"].append(round(tick_duration, 3))

            if not tick_result.get("ok", False):
                err = tick_result.get("error") or "tick_failed"
                attempt_data["errors"].append(f"tick_{tick_idx}:{err}")
                last_error = str(err)
                break

            # Extract frame_id and elapsed_seconds from tick result
            # frame_id is now directly available (handles sync mode where tick() returns int)
            frame = tick_result.get("frame_id")
            if frame is None:
                frame = -1
            else:
                frame = int(frame)
            elapsed = tick_result.get("elapsed_seconds")
            if elapsed is None:
                elapsed = -1.0
            else:
                elapsed = float(elapsed)
            attempt_data["frames"].append(frame)
            attempt_data["elapsed_seconds"].append(elapsed)

        # Check if frames advanced
        frames = attempt_data["frames"]
        elapsed_list = attempt_data["elapsed_seconds"]
        if len(frames) >= 2:
            advanced = any(b > a for a, b in zip(frames, frames[1:])) or any(
                b > a for a, b in zip(elapsed_list, elapsed_list[1:])
            )

        attempt_data["advanced"] = advanced
        payload["attempts"].append(attempt_data)

        if advanced:
            break

        # Brief pause before retry
        if attempt < retries:
            time.sleep(0.5)

    payload["final_result"] = "success" if advanced else "failed"
    payload["snapshot"] = _snapshot_info(world)

    # Always write diagnostics
    try:
        _write_json(out_dir / "tick_watchdog.json", payload)
    except Exception:
        pass

    if not advanced:
        payload["session_compromised"] = True
        hint = (
            "HINT: For cooked towns (Grid0828/0821), first sync ticks can be slow. "
            "Try increasing UP_TICK_WATCHDOG_PER_TICK_S (e.g., 20) or restart CARLA. "
            "IMPORTANT: The CARLA session may be compromised. Please restart CARLA before the next run."
        )
        payload["hint"] = hint
        raise RuntimeError(f"CARLA tick did not advance (sync deadlock). {hint}")

    return payload


def _load_world_with_timeout(load_fn, *, timeout_s: float) -> Tuple[Optional[object], Optional[str]]:
    result: Dict[str, object] = {"world": None, "error": None}

    def _runner():
        try:
            result["world"] = load_fn()
        except Exception as exc:
            result["error"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=float(timeout_s))
    if t.is_alive():
        return None, f"load_world_timeout_after_{timeout_s}s"
    if result["error"] is not None:
        raise result["error"]  # type: ignore[misc]
    return result["world"], None


def _async_warmup_ticks(world, *, n_ticks: int = 5, tick_timeout_s: float = 5.0) -> Dict[str, Any]:
    """Run async warmup ticks BEFORE switching to synchronous mode.

    This helps avoid sync deadlocks on cooked towns where the first sync tick
    can hang if CARLA hasn't finished internal initialization.

    Args:
        world: CARLA world object (should be in async mode)
        n_ticks: Number of async ticks to run
        tick_timeout_s: Timeout per wait_for_tick call

    Returns:
        Dict with warmup results
    """
    result: Dict[str, Any] = {
        "ok": False,
        "ticks_completed": 0,
        "frames": [],
        "errors": [],
    }

    for i in range(n_ticks):
        try:
            # Use wait_for_tick for async mode (positional arg for CARLA 0.9.16)
            snap = world.wait_for_tick(float(tick_timeout_s))
            frame = int(getattr(snap, "frame", -1)) if snap is not None else -1
            result["frames"].append(frame)
            result["ticks_completed"] += 1
        except Exception as exc:
            result["errors"].append(f"tick_{i}:{exc}")
            break

    # Success if we got at least 2 ticks with advancing frames
    frames = result["frames"]
    if len(frames) >= 2:
        result["ok"] = any(b > a for a, b in zip(frames, frames[1:]))
    elif len(frames) == n_ticks:
        result["ok"] = True  # All ticks completed even if we can't verify advancement

    return result


def _restore_world_settings_safe(world, original_settings) -> bool:
    """Safely restore world settings, ignoring errors."""
    try:
        if original_settings is not None:
            world.apply_settings(original_settings)
        return True
    except Exception:
        return False


def _warmup_ticks(world, *, n_ticks: int, timeout_s: float) -> Dict[str, object]:
    n_ticks = int(max(1, n_ticks))
    frames: list[int] = []
    elapsed_list: list[float] = []
    errors: list[str] = []
    for _ in range(n_ticks):
        tick_result = _tick_with_timeout(world, timeout_s=timeout_s)
        if not tick_result.get("ok", False):
            errors.append(str(tick_result.get("error") or "tick_failed"))
            break
        # Use frame_id and elapsed_seconds directly from tick result
        frame = tick_result.get("frame_id")
        frame = int(frame) if frame is not None else -1
        elapsed = tick_result.get("elapsed_seconds")
        elapsed = float(elapsed) if elapsed is not None else -1.0
        frames.append(frame)
        elapsed_list.append(elapsed)
    advancing = False
    if len(frames) >= 2:
        advancing = any(b > a for a, b in zip(frames, frames[1:])) or any(
            b > a for a, b in zip(elapsed_list, elapsed_list[1:])
        )
    return {"ok": advancing, "frames": frames, "elapsed_seconds": elapsed_list, "errors": errors}


def _check_town_available(client, town: str) -> Dict[str, object]:
    result: Dict[str, object] = {"town": town, "available_maps_checked": False, "town_found": None, "error": None}
    try:
        maps = list(client.get_available_maps())
        result["available_maps_checked"] = True
        result["town_found"] = any(str(town).lower() in str(m).lower() for m in maps)
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _probe_streaming_port_warn_only(*, host: str, rpc_port: int, timeout_s: float) -> Dict[str, object]:
    disabled = _env_bool("UP_DISABLE_STREAMING", False)
    stream_port = int(rpc_port) + 1
    result: Dict[str, object] = {"disabled": bool(disabled), "port": int(stream_port), "tcp_reachable": None, "warning": None}
    if disabled:
        return result
    try:
        with socket.create_connection((str(host), int(stream_port)), timeout=float(min(2.0, float(timeout_s)))):
            result["tcp_reachable"] = True
            return result
    except Exception as exc:
        result["tcp_reachable"] = False
        result["warning"] = f"streaming_port_not_reachable: {exc}"
        _warn_once(str(result["warning"]))
        return result


def build_spawn_candidate_indices(
    requested_index: int,
    num_spawn_points: int,
    *,
    seed: int = 0,
    extra_candidates: Optional[list[int]] = None,
    random_samples: int = 4,
) -> list[int]:
    """
    Deterministic spawn selection strategy (pure function).

    Rules:
      - Always try requested index first (if in range), else try 0.
      - Then try a few stable fallbacks (e.g. 50/100/500) and 0.
      - Then add a small set of deterministic random indices.
    """
    n = max(0, int(num_spawn_points))
    if n <= 0:
        return []

    requested = int(requested_index)
    extra = extra_candidates if extra_candidates is not None else [50, 100, 500, 0, 1, 2, 5, 10]
    candidates: list[int] = []

    def _push(i: int) -> None:
        if 0 <= int(i) < n and int(i) not in candidates:
            candidates.append(int(i))

    if 0 <= requested < n:
        _push(requested)
    else:
        _push(0)

    for i in extra:
        _push(int(i))

    rng = random.Random(int(seed))
    for _ in range(max(0, int(random_samples))):
        _push(rng.randrange(0, n))

    return candidates


def plan_soft_teardown_steps(*, skip_destroy: bool) -> list[str]:
    steps = [
        "stop_recorder",
        "stop_sensors",
        "disable_autopilot",
        "disable_physics",
        "tick_between_steps",
    ]
    if not skip_destroy:
        steps.extend(
            [
                "destroy_sensors",
                "tick_after_destroy_sensors",
                "destroy_vehicle",
                "tick_after_destroy_vehicle",
            ]
        )
    steps.append("restore_world_settings")
    return steps


def _safe_tick(world, *, n: int, timeout_s: float = 1.0) -> Dict[str, object]:
    n = max(0, int(n))
    if n == 0:
        return {"ok": True, "n": 0}
    try:
        settings = world.get_settings()
        sync = bool(getattr(settings, "synchronous_mode", False))
    except Exception:
        sync = True

    frames: list[int] = []
    for _ in range(n):
        try:
            if sync:
                # CARLA 0.9.16: world.tick() returns INT frame_id in sync mode
                frame_id = world.tick()
                frame = int(frame_id) if frame_id is not None else -1
            else:
                # CARLA 0.9.16: must use positional float, not keyword arg.
                snap = world.wait_for_tick(float(timeout_s))
                frame = int(getattr(snap, "frame", -1)) if snap is not None else -1
            frames.append(frame)
        except Exception as exc:
            return {"ok": False, "n": n, "frames": frames, "error": str(exc)}
    return {"ok": True, "n": n, "frames": frames}


def _apply_spawn_z_offset(carla, transform, dz_m: float):
    try:
        dz = float(dz_m)
    except Exception:
        dz = 0.0
    if dz == 0.0:
        return transform
    try:
        loc = transform.location
        rot = transform.rotation
        return carla.Transform(
            carla.Location(x=float(loc.x), y=float(loc.y), z=float(loc.z) + dz),
            carla.Rotation(pitch=float(rot.pitch), yaw=float(rot.yaw), roll=float(rot.roll)),
        )
    except Exception:
        return transform


def _ticks_advancing(world, *, n: int, timeout_s: float) -> Dict[str, object]:
    frames: list[int] = []
    elapsed_list: list[float] = []
    errors: list[str] = []
    for _ in range(int(max(1, n))):
        tick_result = _tick_with_timeout(world, timeout_s=timeout_s)
        if not tick_result.get("ok", False):
            errors.append(str(tick_result.get("error") or "tick_failed"))
            break
        # Use frame_id and elapsed_seconds directly from tick result
        frame = tick_result.get("frame_id")
        frame = int(frame) if frame is not None else -1
        elapsed = tick_result.get("elapsed_seconds")
        elapsed = float(elapsed) if elapsed is not None else -1.0
        frames.append(frame)
        elapsed_list.append(elapsed)
    advancing = False
    if len(frames) >= 2:
        advancing = any(b > a for a, b in zip(frames, frames[1:])) or any(
            b > a for a, b in zip(elapsed_list, elapsed_list[1:])
        )
    return {"ok": advancing, "frames": frames, "elapsed_seconds": elapsed_list, "errors": errors}


def _spawn_sensors_smoke(
    *,
    setup: DominikSensorSetup,
    world,
    ego,
    out_dir: Path,
    include_segmentation: bool,
    low_mem: bool,
) -> Dict[str, Any]:
    import carla  # lazy import

    specs = setup._make_specs(bool(include_segmentation), low_mem=bool(low_mem))
    bp_lib = world.get_blueprint_library()
    actors: Dict[str, Any] = {}
    report: Dict[str, Any] = {
        "schema_version": 1,
        "low_mem": bool(low_mem),
        "include_segmentation": bool(include_segmentation),
        "tick_checks": {"ticks": 3, "timeout_s": 2.0},
        "sensors": [],
    }
    failed = False
    for spec in specs:
        entry: Dict[str, Any] = {
            "name": spec.name,
            "type": spec.type,
            "attributes_requested": dict(spec.attributes),
            "success": False,
            "exception": None,
            "tick_ok": None,
        }
        try:
            bp = bp_lib.find(spec.type)
            entry["blueprint_id"] = getattr(bp, "id", spec.type)
            applied: Dict[str, str] = {}
            unsupported: list[str] = []
            for k, v in spec.attributes.items():
                if not bp.has_attribute(k):
                    unsupported.append(k)
                    continue
                try:
                    bp.set_attribute(k, str(v))
                    applied[k] = str(v)
                except Exception as attr_exc:
                    entry.setdefault("attribute_errors", []).append(
                        {"key": k, "value": str(v), "error": str(attr_exc)}
                    )
            entry["attributes_applied"] = applied
            entry["attributes_unsupported"] = unsupported

            tf_dict, clamped_keys = _sanitize_transform_dict(spec.transform)
            entry["transform"] = {
                "location": {"x": tf_dict["x"], "y": tf_dict["y"], "z": tf_dict["z"]},
                "rotation": {"roll": tf_dict["roll"], "pitch": tf_dict["pitch"], "yaw": tf_dict["yaw"]},
            }
            if clamped_keys:
                entry["transform_clamped_keys"] = list(clamped_keys)

            tf = carla.Transform(
                carla.Location(x=tf_dict["x"], y=tf_dict["y"], z=tf_dict["z"]),
                carla.Rotation(roll=tf_dict["roll"], pitch=tf_dict["pitch"], yaw=tf_dict["yaw"]),
            )
            actor = world.try_spawn_actor(bp, tf, attach_to=ego)
            entry["try_spawn_actor_returned"] = actor is not None
            if actor is not None:
                actors[spec.name] = actor
                entry["actor_id"] = getattr(actor, "id", None)
                tick_check = _ticks_advancing(world, n=3, timeout_s=2.0)
                entry["tick_ok"] = bool(tick_check.get("ok", False))
                entry["tick_frames"] = tick_check.get("frames")
                entry["tick_elapsed_seconds"] = tick_check.get("elapsed_seconds")
                entry["tick_errors"] = tick_check.get("errors")
                if not entry["tick_ok"]:
                    failed = True
                    entry["exception"] = "tick_not_advancing_after_attach"
                    break
                entry["success"] = True
            else:
                failed = True
                entry["exception"] = "try_spawn_actor_returned_none"
                break
        except Exception as exc:
            failed = True
            entry["exception"] = str(exc)
            break
        finally:
            report["sensors"].append(entry)

        if failed:
            break

    report["summary"] = {
        "attempted": len(specs),
        "spawned": len(actors),
        "missing": sorted([s.name for s in specs if s.name not in actors]),
        "failed": bool(failed),
    }
    try:
        _write_json(out_dir / "sensor_attach_report.json", report)
    except Exception:
        pass

    if report["summary"]["missing"] or report["summary"]["failed"]:
        raise RuntimeError(f"Sensor smoke failed: {report['summary']}")
    return actors


def _spawn_sanity_objects_near_ego(
    *,
    carla,
    world,
    ego,
    out_dir: Path,
    marker_life: float = 12.0,
) -> Dict[str, Any]:
    """Spawn a small deterministic set of props near the ego for visual QA.

    This is intentionally simple and non-random so screenshots are comparable.
    Returns a report dict; also writes spawn_sanity_objects_log.json.
    """
    report: Dict[str, Any] = {"ok": False, "spawned": [], "errors": []}
    actors = []
    try:
        lib = world.get_blueprint_library()
        base_tf = ego.get_transform()

        # (forward_m, right_m, up_m)
        offsets = [
            (8.0, 3.5, 0.0, "barrier_left", "static.prop.streetbarrier"),
            (8.0, -3.5, 0.0, "barrier_right", "static.prop.streetbarrier"),
            (4.0, 1.5, 0.0, "cone_front", "static.prop.constructioncone"),
            (-4.0, -1.5, 0.0, "cone_rear", "static.prop.constructioncone"),
        ]

        for fwd, right, up, name, bp_id in offsets:
            bp = lib.find(bp_id)
            if bp is None:
                report["errors"].append(f"blueprint_not_found:{bp_id}")
                continue

            # Convert (forward,right,up) into CARLA (x forward, y right, z up) in ego frame.
            loc = base_tf.transform(carla.Location(x=float(fwd), y=float(right), z=float(up)))
            tf = carla.Transform(loc, base_tf.rotation)
            actor = world.try_spawn_actor(bp, tf)
            if actor is None:
                report["errors"].append(f"spawn_failed:{name}:{bp_id}")
                continue
            actors.append(actor)
            report["spawned"].append(
                {
                    "name": name,
                    "blueprint": bp_id,
                    "actor_id": getattr(actor, "id", None),
                    "location": {"x": loc.x, "y": loc.y, "z": loc.z},
                    "rotation": {"roll": base_tf.rotation.roll, "pitch": base_tf.rotation.pitch, "yaw": base_tf.rotation.yaw},
                }
            )
            try:
                world.debug.draw_string(loc, name, life_time=float(marker_life))
            except Exception:
                pass

        report["ok"] = len(report["spawned"]) > 0
    except Exception as exc:
        report["errors"].append(f"exception:{type(exc).__name__}:{exc}")

    report["_actors"] = actors
    try:
        _write_json(out_dir / "spawn_sanity_objects_log.json", {k: v for k, v in report.items() if k != "_actors"})
    except Exception:
        pass
    return report


def _soft_teardown(
    *,
    world,
    ego,
    sensors: Optional[Dict],
    extra_actors: Optional[list] = None,
    recorder: Optional[SensorRecorder],
    out_dir: Path,
    original_settings,
) -> Dict[str, object]:
    """
    Best-effort teardown to reduce Windows fatal crashes during script exit.
    Never raises.
    """
    skip_destroy = _env_bool("UP_SKIP_DESTROY", False)
    tick_between = max(0, min(10, _env_int("UP_TEARDOWN_TICKS", 2)))
    tick_after = max(0, min(20, _env_int("UP_TEARDOWN_FINAL_TICKS", 3)))
    log: list[Dict[str, object]] = []

    def _log(step: str, ok: bool, err: Optional[str] = None) -> None:
        entry: Dict[str, object] = {"step": step, "ok": bool(ok)}
        if err:
            entry["error"] = str(err)
        log.append(entry)

    steps = plan_soft_teardown_steps(skip_destroy=skip_destroy)
    # Do not overwrite run_status.json (it may already record success/failure).
    try:
        (out_dir / "teardown_log.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "skip_destroy": bool(skip_destroy),
                    "teardown_steps": steps,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    try:
        if recorder is not None:
            recorder.close()
        _log("stop_recorder", True)
    except Exception as exc:
        _log("stop_recorder", False, str(exc))

    try:
        if sensors:
            for _name, sensor in sensors.items():
                try:
                    if hasattr(sensor, "stop"):
                        sensor.stop()
                except Exception as exc:
                    _log("stop_sensor", False, str(exc))
        _log("stop_sensors", True)
    except Exception as exc:
        _log("stop_sensors", False, str(exc))

    try:
        if ego is not None:
            try:
                ego.set_autopilot(False)
            except Exception:
                pass
        _log("disable_autopilot", True)
    except Exception as exc:
        _log("disable_autopilot", False, str(exc))

    try:
        if ego is not None:
            try:
                if hasattr(ego, "set_simulate_physics"):
                    ego.set_simulate_physics(False)
            except Exception:
                pass
        _log("disable_physics", True)
    except Exception as exc:
        _log("disable_physics", False, str(exc))

    _log("tick_between_steps", bool(_safe_tick(world, n=tick_between).get("ok", False)))

    if not skip_destroy:
        # Destroy auxiliary actors (e.g., sanity props) before sensors/ego.
        try:
            if extra_actors:
                for a in list(extra_actors):
                    try:
                        a.destroy()
                    except Exception as exc:
                        _log("destroy_extra_actor", False, str(exc))
                _log("destroy_extra_actors", True)
        except Exception as exc:
            _log("destroy_extra_actors", False, str(exc))

        try:
            if sensors:
                for _name, sensor in sensors.items():
                    try:
                        sensor.destroy()
                    except Exception as exc:
                        _log("destroy_sensor", False, str(exc))
            _log("destroy_sensors", True)
        except Exception as exc:
            _log("destroy_sensors", False, str(exc))

        _log("tick_after_destroy_sensors", bool(_safe_tick(world, n=tick_between).get("ok", False)))

        try:
            if ego is not None:
                try:
                    ego.destroy()
                except Exception as exc:
                    _log("destroy_vehicle", False, str(exc))
                else:
                    _log("destroy_vehicle", True)
            else:
                _log("destroy_vehicle", True)
        except Exception as exc:
            _log("destroy_vehicle", False, str(exc))

        _log("tick_after_destroy_vehicle", bool(_safe_tick(world, n=tick_after).get("ok", False)))

    try:
        try:
            world.apply_settings(original_settings)
        except Exception:
            pass
        _log("restore_world_settings", True)
    except Exception as exc:
        _log("restore_world_settings", False, str(exc))

    return {"skip_destroy": bool(skip_destroy), "log": log}


def _die(parser: argparse.ArgumentParser, msg: str) -> "None":
    parser.error(msg)


def _validate_placeholder_path(parser: argparse.ArgumentParser, p: str, label: str) -> None:
    if "..." in p:
        _die(parser, f"placeholder path detected: '...' is not allowed in {label}: {p}")


def _validate_exists(parser: argparse.ArgumentParser, p: str, label: str) -> None:
    if not os.path.exists(p):
        _die(parser, f"{label} not found: {p}")


def _setup_tm(host: str, port: int, tm_port: int, seed: int):
    """
    Configure TrafficManager deterministically by creating carla.Client(host, port)
    before requesting the TM. We do NOT use world.get-client (not a CARLA API).
    """
    import carla  # lazy import

    client = carla.Client(host, port)
    # Windows-safe: allow slow RPC responses during initial world load/settling.
    client.set_timeout(30.0)
    tm = client.get_trafficmanager(tm_port)
    tm.set_synchronous_mode(True)
    tm.set_random_device_seed(seed)
    tm.set_global_distance_to_leading_vehicle(2.0)
    return tm


def _transform_to_dict(transform) -> Dict[str, Dict[str, float]]:
    """Serialize a CARLA transform for metadata output."""
    location = transform.location
    rotation = transform.rotation
    return {
        "location": {"x": location.x, "y": location.y, "z": location.z},
        "rotation": {"pitch": rotation.pitch, "yaw": rotation.yaw, "roll": rotation.roll},
    }


def _sensor_sanity_check(
    world,
    ego,
    sensors: Dict[str, Any],
    out_dir: Path,
    *,
    min_dist_m: float = SENSOR_SANITY_MIN_DIST_M,
    min_z_m: float = SENSOR_SANITY_MIN_Z_M,
    forward_dot_min: float = SENSOR_SANITY_FORWARD_DOT_MIN,
) -> Dict[str, Any]:
    """Check sensor transforms relative to vehicle for sanity.

    Gates:
    - Camera not inside vehicle bbox (distance from vehicle origin > min_dist_m and z > min_z_m)
    - Front cameras face roughly forward (dot(vehicle_forward, camera_forward) > forward_dot_min)

    Returns a dict with 'ok' bool and 'issues' list.
    """
    import math as _math

    report: Dict[str, Any] = {
        "ok": True,
        "issues": [],
        "sensors_checked": [],
        "thresholds": {
            "min_dist_m": float(min_dist_m),
            "min_z_m": float(min_z_m),
            "forward_dot_min": float(forward_dot_min),
        },
    }

    ego_tf = ego.get_transform()
    ego_fwd = ego_tf.rotation.get_forward_vector()

    for name, sensor_actor in sensors.items():
        entry: Dict[str, Any] = {"name": name, "ok": True, "checks": {}}

        try:
            sensor_tf = sensor_actor.get_transform()
            rel_loc = sensor_tf.location - ego_tf.location
            dist = _math.sqrt(rel_loc.x**2 + rel_loc.y**2 + rel_loc.z**2)
            z_rel = rel_loc.z

            entry["location_relative"] = {"x": rel_loc.x, "y": rel_loc.y, "z": rel_loc.z}
            entry["distance_from_origin_m"] = float(dist)

            # Distance check
            if dist < float(min_dist_m):
                entry["checks"]["distance"] = {"ok": False, "value": dist, "min": min_dist_m}
                entry["ok"] = False
                report["issues"].append(f"{name}: distance={dist:.3f}m < {min_dist_m}m (inside vehicle?)")
            else:
                entry["checks"]["distance"] = {"ok": True, "value": dist, "min": min_dist_m}

            # Z check
            if z_rel < float(min_z_m):
                entry["checks"]["z_height"] = {"ok": False, "value": z_rel, "min": min_z_m}
                entry["ok"] = False
                report["issues"].append(f"{name}: z={z_rel:.3f}m < {min_z_m}m (below vehicle center?)")
            else:
                entry["checks"]["z_height"] = {"ok": True, "value": z_rel, "min": min_z_m}

            # Forward dot check for cameras (if 'front' in name)
            is_camera = "camera" in str(getattr(sensor_actor, "type_id", "")).lower()
            is_front = "front" in name.lower()
            if is_camera and is_front:
                sensor_fwd = sensor_tf.rotation.get_forward_vector()
                dot = ego_fwd.x * sensor_fwd.x + ego_fwd.y * sensor_fwd.y + ego_fwd.z * sensor_fwd.z
                entry["checks"]["forward_dot"] = {"value": float(dot), "min": forward_dot_min}
                if dot < float(forward_dot_min):
                    entry["checks"]["forward_dot"]["ok"] = False
                    entry["ok"] = False
                    report["issues"].append(f"{name}: forward_dot={dot:.3f} < {forward_dot_min} (not facing forward?)")
                else:
                    entry["checks"]["forward_dot"]["ok"] = True
            else:
                entry["checks"]["forward_dot"] = {"skipped": True, "reason": "not front camera"}

        except Exception as exc:
            entry["ok"] = False
            entry["error"] = str(exc)
            report["issues"].append(f"{name}: exception during check: {exc}")

        if not entry["ok"]:
            report["ok"] = False
        report["sensors_checked"].append(entry)

    # Write sanity report
    try:
        _write_json(out_dir / "sensor_pose_sanity.json", report)
    except Exception:
        pass

    return report


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()

    map_group = ap.add_mutually_exclusive_group(required=True)
    map_group.add_argument("--xodr", help="Path to XODR map (OpenDRIVE .xodr)")
    map_group.add_argument("--town", help="Manual CARLA town name (e.g., Grid0821, Grid0828)")

    # Sensor rig selection
    ap.add_argument(
        "--rig",
        choices=["dominik", "thesis"],
        default="dominik",
        help="Sensor rig to use: 'dominik' (DominikSensorSetup) or 'thesis' (ThesisSensorRig). Default: dominik",
    )
    ap.add_argument(
        "--strict-sensor-sanity",
        action="store_true",
        help="Abort if sensor pose sanity checks fail (cameras inside vehicle, wrong facing, etc.)",
    )

    # Default calib path: repo-relative ultimate_pipeline/sensors/calib_data.json
    _default_calib = str(
        Path(__file__).resolve().parent.parent / "sensors" / "calib_data.json"
    )
    ap.add_argument(
        "--calib",
        required=False,
        default=_default_calib,
        help=(
            "Path to Dominik calibration JSON (calib_data.json). "
            f"Default: {_default_calib}"
        ),
    )
    ap.add_argument("--out-dir", required=True, help="Output directory for recording artifacts")
    ap.add_argument(
        "--spawn-index",
        type=int,
        default=0,
        help="Index of the spawn point to use for the ego vehicle (default: 0)",
    )
    ap.add_argument(
        "--vehicle",
        default="vehicle.audi.a2",
        help="CARLA vehicle blueprint id for the ego vehicle (default: vehicle.audi.a2)",
    )

    ap.add_argument("--host", default="127.0.0.1", help="CARLA host")
    ap.add_argument("--port", type=int, default=2000, help="CARLA RPC port")
    ap.add_argument("--tm-port", type=int, default=8000, help="TrafficManager port")
    ap.add_argument("--seed", type=int, default=0, help="TrafficManager seed")

    ap.add_argument("--duration", type=float, default=60.0, help="Recording duration (seconds)")
    ap.add_argument("--fps", type=int, default=20, help="Target FPS for synchronous capture")

    ap.add_argument("--lidar-format", choices=["npz", "ply"], default="npz", help="LiDAR storage format")
    ap.add_argument("--seg", action="store_true", help="Also record semantic segmentation cameras")
    ap.add_argument("--seg-converter", choices=["raw", "cityscapes"], default="cityscapes")

    ap.add_argument("--flip-vehicle-y", action="store_true", default=True,
                    help="Flip vehicle Y (robotics +Y left -> CARLA +Y right). Default: True")
    ap.add_argument("--no-flip-vehicle-y", action="store_false", dest="flip_vehicle_y",
                    help="Disable vehicle Y flip")

    ap.add_argument("--opencv-camera-axes", action="store_true", default=True,
                    help="Assume OpenCV camera axes in calibration and convert to CARLA. Default: True")
    ap.add_argument("--no-opencv-camera-axes", action="store_false", dest="opencv_camera_axes",
                    help="Disable OpenCV camera axes conversion")

    ap.add_argument("--low-mem", action="store_true",
                    help="Reduce sensor resolution (helps avoid VRAM/OOM on small GPUs).")
    ap.add_argument(
        "--sensor-smoke",
        action="store_true",
        help="Attach sensors one-by-one with tick checks and write sensor_attach_report.json.",
    )

    ap.add_argument(
        "--spawn-sanity-objects",
        action="store_true",
        help="Spawn a small deterministic set of props near ego for visual QA (logged to spawn_sanity_objects_log.json).",
    )
    ap.add_argument(
        "--sanity-marker-life",
        type=float,
        default=float(os.environ.get("UP_SANITY_MARKER_LIFE", "12.0")),
        help="Lifetime for debug markers for sanity objects (seconds).",
    )

    # Multi-spawn segment recording for training data collection
    ap.add_argument(
        "--spawn-policy",
        choices=["fixed", "random", "cycle"],
        default="fixed",
        help="Spawn point selection policy: fixed (use --spawn-index), random, or cycle through available points.",
    )
    ap.add_argument(
        "--spawn-count",
        type=int,
        default=1,
        help="Number of spawn point segments to record (default: 1). Each segment uses a different spawn point.",
    )
    ap.add_argument(
        "--segment-frames",
        type=int,
        default=0,
        help="Frames per segment (0=use --duration for total). If >0, each segment records this many frames.",
    )
    ap.add_argument(
        "--respawn-on-stuck",
        action="store_true",
        help="Respawn to next segment if vehicle gets stuck (low velocity for extended time).",
    )
    ap.add_argument(
        "--stuck-velocity-threshold",
        type=float,
        default=0.5,
        help="Velocity (m/s) below which vehicle is considered potentially stuck.",
    )
    ap.add_argument(
        "--stuck-frames-threshold",
        type=int,
        default=100,
        help="Number of consecutive low-velocity frames before respawning.",
    )

    # CARLA load/tick timeout options (important for cooked towns)
    ap.add_argument(
        "--load-timeout-s",
        type=float,
        default=float(os.environ.get("UP_CARLA_LOAD_TIMEOUT_S", "180.0")),
        help="Timeout for loading CARLA world/map (seconds). Cooked towns may need 180+s. Default: 180",
    )
    ap.add_argument(
        "--tick-watchdog-s",
        type=float,
        default=float(os.environ.get("UP_TICK_WATCHDOG_S", "30.0")),
        help="Total watchdog timeout for sync mode verification (seconds). Default: 30",
    )
    ap.add_argument(
        "--tick-watchdog-per-tick-s",
        type=float,
        default=float(os.environ.get("UP_TICK_WATCHDOG_PER_TICK_S", "15.0")),
        help="Per-tick timeout during watchdog (seconds). Cooked towns may need 10-15s. Default: 15",
    )
    ap.add_argument(
        "--async-warmup-ticks",
        type=int,
        default=int(os.environ.get("UP_ASYNC_WARMUP_TICKS", "5")),
        help="Number of async warmup ticks before switching to sync mode. Helps avoid deadlocks. Default: 5",
    )
    ap.add_argument(
        "--sync-fallback",
        action="store_true",
        default=_env_bool("UP_SYNC_FALLBACK", False),
        help="If sync mode watchdog fails, fall back to async recording (experimental).",
    )

    args = ap.parse_args(argv)

    # Validate paths AFTER parsing so tests see meaningful errors, not argparse missing-arg noise.
    _validate_placeholder_path(ap, args.out_dir, "out-dir")
    _validate_exists(ap, args.calib, "calib")

    if args.xodr:
        _validate_exists(ap, args.xodr, "xodr")

    return args


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stage = "carla_ready"
    last_snapshot: Optional[Dict[str, Optional[float]]] = None
    _write_run_status(
        out_dir,
        _status_payload(stage=stage, success=False, extra={"exit_code": None}),
    )

    # Build recorder config
    cfg_kwargs = {
        "fps": int(args.fps),
        "synchronous": True,
        "fixed_delta_seconds": 1.0 / float(args.fps),
        "lidar_format": str(args.lidar_format),
        "image_format": "png",
        # seg_converter maps to RecorderConfig.segmentation_mode: semseg_raw/
        # always holds raw class-id labels; "cityscapes" additionally writes
        # a human-viewable palette copy to semseg_viz/ (C8).
        "segmentation_mode": str(args.seg_converter),
        "flip_vehicle_y": bool(args.flip_vehicle_y),
        "opencv_camera_axes": bool(args.opencv_camera_axes),
        "write_sensor_transforms": True,
        "write_world_snapshot": True,
    }

    # Filter kwargs to RecorderConfig fields to prevent schema-drift crashes
    try:
        from dataclasses import fields as _dc_fields
        _allowed = {f.name for f in _dc_fields(RecorderConfig)}
        _filtered = {k: v for k, v in cfg_kwargs.items() if k in _allowed}
        _dropped = sorted(set(cfg_kwargs) - set(_filtered))
        if _dropped:
            print(f"[WARN] RecorderConfig dropped unsupported keys: {_dropped}")
        cfg = RecorderConfig(**_filtered)
    except Exception:
        # If RecorderConfig isn't a dataclass, fall back to a safe subset
        _filtered = {k: v for k, v in cfg_kwargs.items() if k != "seg_converter"}
        cfg = RecorderConfig(**_filtered)
    # Apply low-mem resolution override (both recorder + sensor setup consume this)
    resolution_override: Optional[Tuple[int, int]] = None
    if bool(args.low_mem):
        resolution_override = cfg.low_mem_resolution if cfg.low_mem_resolution is not None else LOW_MEM_DEFAULT_RES

    # Seed run_info early for phase tracking
    run_info = {
        "host": args.host,
        "port": int(args.port),
        "tm_port": int(args.tm_port),
        "seed": int(args.seed),
        "town": args.town,
        "xodr": args.xodr,
        "duration": float(args.duration),
        "fps": int(args.fps),
        "low_mem": bool(args.low_mem),
        "sensor_smoke": bool(args.sensor_smoke),
        "recorder_config": asdict(cfg),
        "spawn_index": int(args.spawn_index),
        "vehicle_blueprint_id": args.vehicle,
        "spawn_transform": None,
        "stage_plan": record_route_stage_plan(include_seg=bool(args.seg)),
        "traffic_manager": {"ok": None, "error": None},
        "phase": stage,
    }
    run_info_path = out_dir / "run_info.json"
    _write_json(run_info_path, run_info)

    # Lazy import CARLA only when actually running
    carla, carla_err = _try_import_carla()
    if carla is None:
        print(f"[ERROR] CARLA python API not available: {carla_err}")
        print(f"[HINT] {_CARLA_EXE_HINT}")
        _update_run_info(
            run_info_path,
            run_info,
            {
                "exception_type": "ImportError",
                "exception_message": str(carla_err),
                "phase": stage,
            },
        )
        _write_run_status(
            out_dir,
            _status_payload(
                stage=stage,
                success=False,
                error=f"carla_import_failed: {carla_err}",
                exception="ImportError",
                traceback_text=None,
                extra={"exit_code": 2},
            ),
        )
        return 2

    client = carla.Client(args.host, int(args.port))
    # Use load_timeout_s for client timeout - cooked towns (Grid0828/0821) can take 60-180s
    load_timeout_s = float(getattr(args, "load_timeout_s", 180.0))
    client.set_timeout(load_timeout_s)

    # Preflight: RPC + town availability before attempting world load
    run_status: Dict[str, object] = {"stage": stage, "success": False, "error": None, "exit_code": None}
    try:
        run_status["rpc_ok"] = True
        try:
            run_status["server_version"] = client.get_server_version()
        except Exception as exc:
            # Some builds may throw here due to streaming port issues; warn-only.
            run_status["server_version"] = None
            run_status["server_version_error"] = str(exc)
            _warn_once(f"get_server_version failed (ignored): {exc}")
    except Exception as exc:
        run_status["rpc_ok"] = False
        run_status["error"] = f"rpc_not_responsive: {exc}"
        run_status["exit_code"] = 2
        _write_run_status(
            out_dir,
            _status_payload(
                stage=stage,
                success=False,
                error=run_status["error"],
                exception=type(exc).__name__,
                traceback_text=traceback.format_exc(),
                extra=run_status,
            ),
        )
        print(f"[ERROR] {run_status['error']}")
        print(f"[HINT] {_CARLA_EXE_HINT}")
        return 2

    # Optional streaming port probe (warn-only; never blocks preflight).
    run_status["streaming"] = _probe_streaming_port_warn_only(
        host=str(args.host),
        rpc_port=int(args.port),
        timeout_s=float(os.environ.get("UP_CARLA_READY_TICK_TIMEOUT_S", "2.0")),
    )

    if args.town:
        town_check = _check_town_available(client, str(args.town))
        run_status["town_check"] = town_check
        if town_check.get("town_found") is False:
            run_status["error"] = f"manual_town_not_available: {args.town}"
            run_status["exit_code"] = 2
            _write_run_status(out_dir, _status_payload(stage=stage, success=False, error=run_status["error"], extra=run_status))
            print(f"[ERROR] {run_status['error']}")
            print(f"[HINT] {_CARLA_EXE_HINT}")
            return 2

    run_status["exit_code"] = None
    _write_run_status(out_dir, _status_payload(stage=stage, success=True, extra=run_status))

    # World selection: town OR xodr
    stage = "world_load"
    _update_run_info(run_info_path, run_info, {"phase": stage})
    # load_timeout_s already set above from args
    run_info["load_timeout_s"] = load_timeout_s
    try:
        if args.town:
            world, load_error = _load_world_with_timeout(
                lambda: _reload_ready_for_sensors(client, map_name=args.town, tm_port=8000),
                timeout_s=load_timeout_s,
            )
        else:
            xodr_text = Path(args.xodr).read_text(encoding="utf-8", errors="replace")
            from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

            world, load_error = _load_world_with_timeout(
                lambda: load_opendrive_world(client, xodr_text, timeout_s=load_timeout_s, retries=1, do_reload=True),
                timeout_s=load_timeout_s,
            )
        if load_error is not None or world is None:
            _write_run_status(
                out_dir,
                _status_payload(stage=stage, success=False, error=str(load_error), extra={"exit_code": 2}),
            )
            print(f"[ERROR] load_map failed: {load_error}")
            print(f"[HINT] {_CARLA_EXE_HINT}")
            return 2
    except Exception as exc:
        _write_run_status(
            out_dir,
            _status_payload(
                stage=stage,
                success=False,
                error=str(exc),
                exception=type(exc).__name__,
                traceback_text=traceback.format_exc(),
                extra={"exit_code": 2},
            ),
        )
        print(f"[ERROR] load_map failed: {exc}")
        print(f"[HINT] {_CARLA_EXE_HINT}")
        return 2

    warmup = _warmup_ticks(world, n_ticks=10, timeout_s=_env_float("UP_CARLA_READY_TICK_TIMEOUT_S", 5.0))
    if not warmup.get("ok", False):
        _write_run_status(
            out_dir,
            _status_payload(
                stage=stage,
                success=False,
                error="warmup_ticks_not_advancing",
                extra={
                    "exit_code": 2,
                    "warmup": warmup,
                },
            ),
        )
        print("[ERROR] CARLA warmup ticks did not advance.")
        print(f"[HINT] {_CARLA_EXE_HINT}")
        return 2
    _write_run_status(out_dir, _status_payload(stage=stage, success=True, extra={"exit_code": None}))

    # TrafficManager (warn-only fallback if TM fails)
    tm = None
    tm_error = None
    try:
        tm = _setup_tm(args.host, int(args.port), int(args.tm_port), int(args.seed))
    except Exception as exc:
        tm = None
        tm_error = str(exc)
        _warn_once(f"TrafficManager setup failed (continuing without TM): {exc}")

    # Sensor setup + recorder
    # Select sensor rig based on --rig flag
    rig_mode = getattr(args, "rig", "dominik")
    ctv_attach_mode = os.environ.get("UP_CAMERA_CTV_ATTACH", "direct")
    run_info["sensor_rig"] = {
        "mode": rig_mode,
        "ctv_attach_mode": ctv_attach_mode,
        "calib_path": str(args.calib),
    }

    setup = None
    thesis_rig = None
    if rig_mode == "thesis":
        try:
            from ultimate_pipeline.carla_tools.thesis_sensor_rig import ThesisSensorRig
            thesis_rig = ThesisSensorRig(args.calib)
            print(f"[OK] Using ThesisSensorRig (cTv attach mode: {ctv_attach_mode})")
        except Exception as rig_exc:
            print(f"[WARN] ThesisSensorRig init failed, falling back to DominikSensorSetup: {rig_exc}")
            rig_mode = "dominik"
            run_info["sensor_rig"]["fallback_reason"] = str(rig_exc)

    if rig_mode == "dominik" or thesis_rig is None:
        setup = DominikSensorSetup(
            args.calib,
            flip_vehicle_y=bool(args.flip_vehicle_y),
            opencv_camera_axes=bool(args.opencv_camera_axes),
            lidar_axes_mode="auto",
            verbose=False,
            resolution_override=resolution_override,
        )

    recorder = SensorRecorder(output_dir=str(out_dir), config=cfg)
    _update_run_info(
        run_info_path,
        run_info,
        {"traffic_manager": {"ok": tm is not None, "error": tm_error}, "sensor_rig": run_info["sensor_rig"]},
    )

    # Deterministic sync mode with robust warmup for cooked towns
    stage = "sync_settings"
    _update_run_info(run_info_path, run_info, {"phase": stage})
    _write_run_status(out_dir, _status_payload(stage=stage, success=False, extra={"exit_code": None}))
    original_settings = world.get_settings()
    sync_fallback_used = False
    town_name = str(args.town) if args.town else (args.xodr or "unknown")

    # Async warmup BEFORE switching to sync mode (helps avoid deadlocks on cooked towns)
    async_warmup_ticks = int(getattr(args, "async_warmup_ticks", 5))
    if async_warmup_ticks > 0:
        print(f"[INFO] Running {async_warmup_ticks} async warmup ticks before sync mode...")
        async_warmup_result = _async_warmup_ticks(world, n_ticks=async_warmup_ticks, tick_timeout_s=10.0)
        run_info["async_warmup"] = async_warmup_result
        _write_json(run_info_path, run_info)
        if not async_warmup_result.get("ok", False):
            print(f"[WARN] Async warmup incomplete: {async_warmup_result.get('errors', [])}")
        else:
            print(f"[OK] Async warmup completed: {async_warmup_result.get('ticks_completed', 0)} ticks")
        # Brief pause after warmup
        time.sleep(0.3)

    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 1.0 / float(args.fps)

    # Make runs stable across sessions: explicitly disable substepping.
    # Otherwise CARLA may keep substepping=True from a previous run and the inequality can break.
    if hasattr(settings, "substepping"):
        settings.substepping = False

    world.apply_settings(settings)

    # Brief pause after applying sync settings (helps CARLA stabilize)
    time.sleep(0.2)

    # Tick watchdog with configurable parameters
    tick_watchdog_s = float(getattr(args, "tick_watchdog_s", 30.0))
    tick_watchdog_per_tick_s = float(getattr(args, "tick_watchdog_per_tick_s", 15.0))
    sync_fallback = bool(getattr(args, "sync_fallback", False))

    run_info["tick_watchdog_config"] = {
        "timeout_s": tick_watchdog_s,
        "per_tick_s": tick_watchdog_per_tick_s,
        "sync_fallback_enabled": sync_fallback,
    }

    try:
        watchdog_result = _tick_watchdog(
            world,
            out_dir,
            timeout_s=tick_watchdog_s,
            n_ticks=5,
            per_tick_s=tick_watchdog_per_tick_s,
            town_name=town_name,
            retries=2,
        )
        run_info["tick_watchdog_result"] = watchdog_result.get("final_result", "unknown")
    except Exception as exc:
        last_snapshot = _snapshot_info(world)

        # Sync fallback mode: revert to async if enabled
        if sync_fallback:
            print("[WARN] Sync watchdog failed, attempting async fallback...")
            _restore_world_settings_safe(world, original_settings)
            sync_fallback_used = True
            run_info["sync_fallback_used"] = True
            run_info["sync_fallback_reason"] = str(exc)
            _write_json(run_info_path, run_info)
            print("[OK] Reverted to async mode for fallback recording")
        else:
            _update_run_info(
                run_info_path,
                run_info,
                {
                    "phase": stage,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "last_snapshot": last_snapshot,
                    "hint": "CARLA session may be compromised. Restart CARLA before next run. Try increasing UP_TICK_WATCHDOG_PER_TICK_S (e.g., 20)",
                },
            )
            _write_run_status(
                out_dir,
                _status_payload(
                    stage=stage,
                    success=False,
                    error=str(exc),
                    exception=type(exc).__name__,
                    traceback_text=traceback.format_exc(),
                    last_snapshot=last_snapshot,
                    extra={
                        "exit_code": 2,
                        "hint": "CARLA session may be compromised. Restart CARLA before next run. If this persists, increase --tick-watchdog-per-tick-s (e.g., 20) or set UP_SYNC_FALLBACK=1",
                    },
                ),
            )
            # Attempt to restore settings before raising
            _restore_world_settings_safe(world, original_settings)
            raise

    run_info["sync_fallback_used"] = sync_fallback_used
    _write_json(run_info_path, run_info)
    _write_run_status(out_dir, _status_payload(stage=stage, success=True, extra={"exit_code": None, "sync_fallback_used": sync_fallback_used}))
    stage = "world_ready"
    _update_run_info(run_info_path, run_info, {"phase": stage})

    ego = None
    sensors = None
    sanity_report: Optional[Dict[str, Any]] = None
    sanity_actors: Optional[list] = None
    spawn_transform = None
    chosen_spawn_index = None
    spawn_selection: Dict[str, object] = {
        "requested_index": int(args.spawn_index),
        "candidates": [],
        "attempts": [],
        "chosen_index": None,
        "z_offset_used_m": 0.0,
        "early_tick_n": 2,
    }

    try:
        stage = "spawn_ego"
        _update_run_info(run_info_path, run_info, {"phase": stage})
        _write_run_status(out_dir, _status_payload(stage=stage, success=False, extra={"exit_code": None}))
        # Preflight: spawnpoints + blueprint existence (before attempting vehicle spawn)
        blueprint_library = world.get_blueprint_library()
        vehicle_candidates = blueprint_library.filter(args.vehicle)
        if not vehicle_candidates:
            raise RuntimeError(f"Vehicle blueprint '{args.vehicle}' not found in blueprint library")
        vehicle_bp = vehicle_candidates[0]

        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            raise RuntimeError("No spawn points found in map")

        # Spawn selection strategy:
        # try requested index first; then stable fallbacks; then deterministic random samples.
        candidates = build_spawn_candidate_indices(
            int(args.spawn_index),
            len(spawn_points),
            seed=int(args.seed),
            extra_candidates=[50, 100, 500],
            random_samples=0,
        )
        spawn_selection["candidates"] = list(candidates)
        z_offset_m = float(max(-5.0, min(5.0, _env_float("UP_SPAWN_Z_OFFSET_M", 1.0))))
        early_tick_n = int(max(0, min(10, _env_int("UP_SPAWN_EARLY_TICKS", 2))))
        spawn_selection["early_tick_n"] = early_tick_n

        for idx in candidates:
            attempt: Dict[str, object] = {"index": int(idx), "ok": False, "error": None, "z_offset_used_m": 0.0}
            tf0 = spawn_points[int(idx)]
            for dz in (0.0, z_offset_m):
                if dz != 0.0 and z_offset_m == 0.0:
                    continue
                tf = _apply_spawn_z_offset(carla, tf0, dz)
                try:
                    ego_try = world.try_spawn_actor(vehicle_bp, tf)
                except Exception as exc:
                    ego_try = None
                    attempt["error"] = f"try_spawn_actor_exception: {exc}"

                if ego_try is None:
                    attempt["error"] = attempt["error"] or "try_spawn_actor_returned_none"
                    continue

                # Early tick check after spawn (may fail if vehicle intersects / sim unstable).
                tick_result = _safe_tick(world, n=early_tick_n, timeout_s=float(os.environ.get("UP_CARLA_READY_TICK_TIMEOUT_S", "2.0")))
                if not tick_result.get("ok", False):
                    attempt["error"] = f"early_tick_failed: {tick_result.get('error')}"
                    try:
                        # Best-effort cleanup of this attempt (vehicle only) before retrying.
                        try:
                            ego_try.set_autopilot(False)
                        except Exception:
                            pass
                        try:
                            if hasattr(ego_try, "set_simulate_physics"):
                                ego_try.set_simulate_physics(False)
                        except Exception:
                            pass
                        if not _env_bool("UP_SKIP_DESTROY", False):
                            try:
                                ego_try.destroy()
                            except Exception:
                                pass
                        _safe_tick(world, n=1, timeout_s=1.0)
                    except Exception:
                        pass
                    continue

                ego = ego_try
                spawn_transform = tf
                chosen_spawn_index = int(idx)
                attempt["ok"] = True
                attempt["z_offset_used_m"] = float(dz)
                spawn_selection["chosen_index"] = chosen_spawn_index
                spawn_selection["z_offset_used_m"] = float(dz)
                break

            spawn_selection["attempts"].append(attempt)
            if ego is not None:
                break

        if ego is None or spawn_transform is None or chosen_spawn_index is None:
            raise RuntimeError(
                f"Failed to spawn vehicle '{vehicle_bp.id}' using candidates={candidates}"
            )

        # Optional: spawn a few deterministic props for visual QA
        if bool(getattr(args, "spawn_sanity_objects", False)):
            try:
                sanity_report = _spawn_sanity_objects_near_ego(
                    carla=carla,
                    world=world,
                    ego=ego,
                    out_dir=out_dir,
                    marker_life=float(getattr(args, "sanity_marker_life", 12.0)),
                )
                sanity_actors = list(sanity_report.get("_actors") or [])
                run_info["sanity_objects"] = {k: v for k, v in sanity_report.items() if k != "_actors"}
                _write_json(run_info_path, run_info)
            except Exception as exc:
                _warn_once(f"sanity_objects_spawn_failed: {exc}")

        run_info.update(
            {
                "vehicle_blueprint_id": vehicle_bp.id,
                "spawn_transform": _transform_to_dict(spawn_transform),
                "spawn_index_selected": int(chosen_spawn_index),
                "spawn_selection": spawn_selection,
            }
        )
        _write_json(run_info_path, run_info)
        _write_run_status(
            out_dir,
            _status_payload(
                stage=stage,
                success=True,
                extra={
                    "exit_code": None,
                    "spawn_index_selected": int(chosen_spawn_index),
                    "spawn_transform": _transform_to_dict(spawn_transform),
                    "spawn_selection": spawn_selection,
                    "skip_destroy": _env_bool("UP_SKIP_DESTROY", False),
                    "traffic_manager": {"ok": tm is not None, "error": tm_error},
                },
            ),
        )

        stage = "attach_sensors"
        _update_run_info(run_info_path, run_info, {"phase": stage})
        _write_run_status(out_dir, _status_payload(stage=stage, success=False, extra={"exit_code": None}))

        # Setup sensors (robust spawn logging written under out_dir)
        # Use ThesisSensorRig if --rig thesis was specified, otherwise DominikSensorSetup
        if thesis_rig is not None:
            # ThesisSensorRig path
            spawned = thesis_rig.spawn_rig(world, ego)
            sensors = {name: sp.actor for name, sp in spawned.items()}
            # Write rig report
            rig_report = {name: sp.report for name, sp in spawned.items()}
            _write_json(out_dir / "thesis_rig_report.json", rig_report)
            print(f"[OK] ThesisSensorRig spawned {len(sensors)} sensors")
        elif args.sensor_smoke:
            sensors = _spawn_sensors_smoke(
                setup=setup,
                world=world,
                ego=ego,
                out_dir=out_dir,
                include_segmentation=bool(args.seg),
                low_mem=bool(args.low_mem),
            )
        else:
            sensors = setup.spawn_on_vehicle(
                world,
                ego,
                include_segmentation=bool(args.seg),
                out_dir=out_dir,
                low_mem=bool(args.low_mem),
            )
        recorder.attach(world, ego, sensors)

        # Sensor sanity gate: check that cameras are not inside vehicle
        sanity_check = _sensor_sanity_check(world, ego, sensors, out_dir)
        run_info["sensor_sanity"] = {k: v for k, v in sanity_check.items() if k != "sensors_checked"}
        _write_json(run_info_path, run_info)

        if not sanity_check.get("ok", True):
            issues_str = "; ".join(sanity_check.get("issues", [])[:3])
            if getattr(args, "strict_sensor_sanity", False):
                raise RuntimeError(f"Sensor sanity check failed: {issues_str}")
            else:
                print(f"[WARN] Sensor sanity issues (non-fatal): {issues_str}")

        # Minimal sensor geometry validation (non-blocking, log-only)
        if setup is not None:
            try:
                validation = setup.validate_sensor_geometry(world, ego, sensors)
                run_info["sensor_validation"] = validation
                _write_json(run_info_path, run_info)
                if validation.get("valid"):
                    print(f"[OK] Sensor geometry validated: {validation.get('camera_name')}")
                else:
                    print(f"[WARN] Sensor geometry validation issues: {validation.get('errors', [])}")
            except Exception as val_exc:
                print(f"[WARN] Sensor validation skipped: {val_exc}")

        _write_run_status(out_dir, _status_payload(stage=stage, success=True, extra={"exit_code": None}))

        # Autopilot (TM optional)
        if tm is not None:
            ego.set_autopilot(True, tm.get_port())
        else:
            ego.set_autopilot(True)

        stage = "capture_loop"
        _update_run_info(run_info_path, run_info, {"phase": stage})
        _write_run_status(out_dir, _status_payload(stage=stage, success=False, extra={"exit_code": None}))

        # Run loop
        t0 = time.time()
        while (time.time() - t0) < float(args.duration):
            world.tick()
            recorder.tick()
            last_snapshot = _snapshot_info(world)

        recorder.close()
        print(f"[OK] Recording complete: {out_dir}")
        _write_run_status(
            out_dir,
            _status_payload(
                stage=stage,
                success=True,
                last_snapshot=last_snapshot,
                extra={
                    "exit_code": 0,
                    "spawn_index_selected": int(chosen_spawn_index) if chosen_spawn_index is not None else None,
                    "spawn_transform": _transform_to_dict(spawn_transform) if spawn_transform is not None else None,
                    "skip_destroy": _env_bool("UP_SKIP_DESTROY", False),
                    "traffic_manager": {"ok": tm is not None, "error": tm_error},
                },
            ),
        )
        return 0

    except Exception as e:
        last_snapshot = _snapshot_info(world) if "world" in locals() else last_snapshot
        _update_run_info(
            run_info_path,
            run_info,
            {
                "phase": stage,
                "exception_type": type(e).__name__,
                "exception_message": str(e),
                "last_snapshot": last_snapshot,
            },
        )
        print(f"[ERROR] {e}")
        print(f"[HINT] {_CARLA_EXE_HINT}")
        _write_run_status(
            out_dir,
            _status_payload(
                stage=stage,
                success=False,
                error=str(e),
                exception=type(e).__name__,
                traceback_text=traceback.format_exc(),
                last_snapshot=last_snapshot,
                extra={
                    "exit_code": 2,
                    "spawn_index_selected": int(chosen_spawn_index) if chosen_spawn_index is not None else None,
                    "skip_destroy": _env_bool("UP_SKIP_DESTROY", False),
                    "traffic_manager": {"ok": tm is not None, "error": tm_error},
                },
            ),
        )
        return 2

    finally:
        try:
            stage = "teardown"
            _update_run_info(run_info_path, run_info, {"phase": stage})
            _soft_teardown(
                world=world,
                ego=ego,
                sensors=sensors,
                extra_actors=sanity_actors,
                recorder=recorder,
                out_dir=out_dir,
                original_settings=original_settings,
            )
        except Exception:
            # Never raise during teardown.
            pass


if __name__ == "__main__":
    raise SystemExit(main())
