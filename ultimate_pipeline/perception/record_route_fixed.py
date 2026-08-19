#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
record_route_fixed.py

A minimal, Windows-stable perception capture runner for CARLA 0.9.16 that fixes the
sync tick frame-id pitfall:

- In synchronous mode, CARLA 0.9.16 typically returns an INT frame id from world.tick().
  This module also tolerates snapshot-like return objects from test doubles and wrappers.

This module is intended to be used by ultimate_pipeline.tools.run_perception_safe
to avoid fragile thread-based tick timeouts and false "sync deadlock" watchdogs.

It supports:
- --town (cooked towns like Grid0828/Grid0821)
- --xodr (generated maps)
- --rig {dominik, thesis} (thesis uses ThesisSensorRig)
- --low-mem downscaling (via DominikSensorSetup resolution_override, and ThesisSensorRig's pixel budget)
- RGB + LiDAR capture via SensorRecorder

Thesis constraints:
- Cameras: use K_undistortion only (pinhole), ignore K and D
- Camera extrinsics: cTv vehicle->camera; attachment uses cTv directly (no inversion)
- LiDAR extrinsics: vTl lidar->vehicle; attachment uses inverse(vTl)
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.sensors.recorder import RecorderConfig, SensorRecorder
from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup

LOW_MEM_DEFAULT_RES = (960, 540)
_LAST_CAPTURE_CONTEXT: Dict[str, Any] = {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _extract_thesis_spawn_phase_report(rig: Any) -> Dict[str, Any]:
    if rig is None or not hasattr(rig, "get_last_spawn_phase_report"):
        return {}
    try:
        payload = rig.get_last_spawn_phase_report()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return bool(default)
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None:
        return int(default)
    try:
        return int(str(v).strip())
    except Exception:
        return int(default)


def _tcp_port_open(host: str, port: int, timeout_s: float = 1.0) -> bool:
    try:
        with socket.create_connection((str(host), int(port)), timeout=float(timeout_s)):
            return True
    except Exception:
        return False


def _wait_for_stream_port_stable(
    host: str,
    port: int,
    *,
    wait_s: float,
    probe_timeout_s: float = 0.5,
    poll_interval_s: float = 1.0,
    required_successes: int = 5,
) -> bool:
    deadline = time.monotonic() + max(0.0, float(wait_s))
    required_successes = max(1, int(required_successes))
    consecutive_successes = 0
    while True:
        if _tcp_port_open(str(host), int(port), timeout_s=float(probe_timeout_s)):
            consecutive_successes += 1
            if consecutive_successes >= required_successes:
                return True
        else:
            consecutive_successes = 0
        if time.monotonic() >= deadline:
            return False
        remaining = max(0.05, deadline - time.monotonic())
        time.sleep(min(float(poll_interval_s), float(remaining)))


def _repo_root_dir() -> Path:
    cwd = Path.cwd()
    for parent in (cwd, *cwd.parents):
        if (parent / "AGENT_SYNC.md").is_file():
            return parent
    here = Path(__file__)
    for parent in (here.parent, *here.parents):
        if (parent / "AGENT_SYNC.md").is_file():
            return parent
    return cwd


def _portable_path_for_metadata(
    path_value: Any, *, repo_root: Optional[Path] = None
) -> str:
    text = str(path_value or "").strip()
    if not text:
        return ""
    p = Path(text)
    if not p.is_absolute():
        return p.as_posix()

    bases: List[Path] = []
    if repo_root is not None:
        bases.append(repo_root)
    try:
        bases.append(Path.cwd())
    except Exception:
        pass

    for base in bases:
        try:
            rel = p.relative_to(base)
            return rel.as_posix()
        except Exception:
            pass
        try:
            rel_text = os.path.relpath(str(p), str(base))
            if rel_text and (not rel_text.startswith("..")):
                return Path(rel_text).as_posix()
        except Exception:
            pass
    return p.as_posix()


def _thesis_capture_gate_state(rig: str) -> Dict[str, Any]:
    from ultimate_pipeline.config.settings import SETTINGS

    env_raw = os.environ.get("UP_ENABLE_THESIS_PERCEPTION_CAPTURE")
    env_present = env_raw is not None
    env_enabled = (
        _env_bool("UP_ENABLE_THESIS_PERCEPTION_CAPTURE", False)
        if env_present
        else None
    )
    settings_enabled = bool(getattr(SETTINGS, "ENABLE_THESIS_PERCEPTION_CAPTURE", False))
    gate_enabled = bool(env_enabled) if env_present else bool(settings_enabled)
    gate_required = str(rig).strip().lower() == "thesis"
    return {
        "gate_required": bool(gate_required),
        "enabled": bool(gate_enabled),
        "env_present": bool(env_present),
        "env_raw": str(env_raw) if env_raw is not None else "",
        "env_enabled": (
            bool(env_enabled) if isinstance(env_enabled, bool) else None
        ),
        "settings_enabled": bool(settings_enabled),
    }


def _safe_destroy(
    actor,
    *,
    timeout_s: float = 3.0,
    pre_destroy: Optional[Any] = None,
) -> bool:
    try:
        if actor is None:
            return False
        if hasattr(actor, "is_alive"):
            try:
                if not actor.is_alive:
                    return False
            except RuntimeError:
                return False
        if callable(pre_destroy):
            try:
                pre_destroy()
            except Exception as exc:
                print(
                    f"[SAFE-DESTROY] pre_destroy hook failed: {exc!r}; continuing",
                    flush=True,
                )
        if hasattr(actor, "stop"):
            try:
                actor.stop()
            except Exception as exc:
                print(
                    f"[SAFE-DESTROY] actor.stop() raised {exc!r}; continuing",
                    flush=True,
                )
        destroy_done = threading.Event()
        destroy_error: Dict[str, Any] = {"exc": None}

        def _do_destroy() -> None:
            try:
                actor.destroy()
            except Exception as exc:
                destroy_error["exc"] = exc
            finally:
                destroy_done.set()

        t = threading.Thread(
            target=_do_destroy,
            daemon=True,
            name="carla-safe-destroy",
        )
        t.start()
        if not destroy_done.wait(timeout=max(0.1, float(timeout_s))):
            print("[SAFE-DESTROY] actor.destroy() timed out; moving on", flush=True)
            return False
        if destroy_error["exc"] is not None:
            print(
                f"[SAFE-DESTROY] actor.destroy() raised {destroy_error['exc']!r}; ignoring",
                flush=True,
            )
            return False
        return True
    except RuntimeError as exc:
        print(f"[SAFE-DESTROY] runtime error during destroy: {exc!r}", flush=True)
        return False
    except Exception as exc:
        print(f"[SAFE-DESTROY] unexpected destroy failure: {exc!r}", flush=True)
        return False


def _prepare_world_for_destroy(world, *, timeout_s: float) -> None:
    try:
        settings = world.get_settings()
        sync_enabled = bool(getattr(settings, "synchronous_mode", False))
    except Exception:
        sync_enabled = False
    try:
        for _ in range(3):
            if sync_enabled and hasattr(world, "tick"):
                world.tick(float(timeout_s))
            elif hasattr(world, "wait_for_tick"):
                world.wait_for_tick(float(timeout_s))
            elif hasattr(world, "tick"):
                world.tick(float(timeout_s))
    except Exception:
        pass


def _spawn_points_with_waypoint_fallback(
    world,
    *,
    waypoint_distance_m: float = 2.0,
    z_offset_m: float = 0.5,
) -> List[Any]:
    try:
        spawn_points = list(world.get_map().get_spawn_points())
    except Exception:
        spawn_points = []
    if spawn_points:
        return spawn_points
    print(
        "[record_route] WARNING: no spawn points from map - generating from waypoints",
        flush=True,
    )
    try:
        waypoints = list(world.get_map().generate_waypoints(float(waypoint_distance_m)))
        if waypoints:
            transform = waypoints[max(0, len(waypoints) // 2)].transform
            try:
                transform.location.z += float(z_offset_m)
            except Exception:
                pass
            return [transform]
    except Exception as exc:
        print(f"[record_route] waypoint fallback failed: {exc}", flush=True)
    return []


def _run_stream_precheck(
    *,
    host: str,
    stream_port: int,
    pre_spawn_stream_wait_s: float,
    stream_required_successes: int,
    sensor_rig_report: Dict[str, Any],
) -> bool:
    effective_wait_s = max(
        float(pre_spawn_stream_wait_s),
        float(os.environ.get("UP_STREAM_READY_WAIT_S", "10")),
    )
    stream_precheck_ok = _wait_for_stream_port_stable(
        str(host),
        int(stream_port),
        wait_s=float(effective_wait_s),
        required_successes=int(stream_required_successes),
    )
    sensor_rig_report["stream_precheck"] = {
        "ok": bool(stream_precheck_ok),
        "host": str(host),
        "stream_port": int(stream_port),
        "wait_s": float(effective_wait_s),
        "required_successes": int(stream_required_successes),
    }
    if not stream_precheck_ok:
        sensor_rig_report["stream_precheck_warning"] = (
            "stream_port_not_ready_continuing_anyway"
        )
        print(
            f"[record_route] WARNING: stream port {int(stream_port)} not ready after "
            f"{float(effective_wait_s):.0f}s - continuing spawn attempt; callbacks may not fire",
            flush=True,
        )
    return bool(stream_precheck_ok)


def _record_post_spawn_stream_health(
    *,
    host: str,
    stream_port: int,
    sensor_rig_report: Dict[str, Any],
) -> bool:
    post_spawn_stream_ok = _tcp_port_open(
        str(host), int(stream_port), timeout_s=0.5
    )
    sensor_rig_report["post_spawn_stream_ok"] = bool(post_spawn_stream_ok)
    if not post_spawn_stream_ok:
        sensor_rig_report["post_spawn_stream_warning"] = (
            "stream_port_not_open_after_sensor_spawn"
        )
        print(
            f"[record_route] WARNING: stream port {int(stream_port)} not open after "
            "sensor spawn - callbacks may not fire. Consider restarting CARLA with "
            "-carla-streaming-port=2001",
            flush=True,
        )
    return bool(post_spawn_stream_ok)


def _maybe_reload_world_for_stream_flush(
    *,
    client: Any,
    world: Any,
    fps: float,
) -> Any:
    if not _env_bool("UP_FORCE_WORLD_RELOAD", True):
        print(
            "[STREAM-FLUSH] WARNING: world reload disabled via UP_FORCE_WORLD_RELOAD=0",
            flush=True,
        )
        return world

    try:
        current_map = str(world.get_map().name)
    except Exception as exc:
        print(
            f"[STREAM-FLUSH] WARNING: current map unavailable; skipping reload ({exc})",
            flush=True,
        )
        return world

    if not current_map:
        print(
            "[STREAM-FLUSH] WARNING: current map name empty; skipping reload",
            flush=True,
        )
        return world

    print(
        f"[STREAM-FLUSH] Reloading world {current_map} to clear stale stream registry",
        flush=True,
    )
    candidate_names: List[str] = []
    for candidate in (
        current_map,
        str(current_map).replace("\\", "/").split("/")[-1],
    ):
        candidate_text = str(candidate or "").strip()
        if candidate_text and candidate_text not in candidate_names:
            candidate_names.append(candidate_text)

    reloaded_world = None
    last_error: Optional[Exception] = None
    for candidate_name in candidate_names:
        try:
            reloaded_world = client.load_world(candidate_name)
            current_map = candidate_name
            break
        except Exception as exc:
            last_error = exc
    if reloaded_world is None:
        raise RuntimeError(
            f"stream_flush_reload_failed:{candidate_names}:{last_error}"
        ) from last_error
    time.sleep(2.0)
    settings = reloaded_world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 1.0 / float(max(1.0, float(fps)))
    if hasattr(settings, "substepping"):
        settings.substepping = False
    reloaded_world.apply_settings(settings)
    print("[STREAM-FLUSH] World reloaded, sync mode reapplied", flush=True)
    return reloaded_world


def _spawn_actor_with_tick_validation(
    world: Any,
    blueprint: Any,
    transform: Any,
    *,
    tick_timeout_s: float,
    attach_to: Any = None,
) -> Any:
    try:
        actor = world.spawn_actor(blueprint, transform, attach_to=attach_to)
    except RuntimeError as exc:
        print(f"[spawn] spawn_actor failed at {transform}: {exc}", flush=True)
        return None
    except Exception as exc:
        print(f"[spawn] spawn_actor failed at {transform}: {exc}", flush=True)
        return None
    try:
        world.tick(float(tick_timeout_s))
    except Exception:
        pass
    try:
        if actor is not None and hasattr(actor, "is_alive") and not actor.is_alive:
            raise RuntimeError("ego_spawn_succeeded_but_actor_dead_after_tick")
    except RuntimeError:
        raise
    except Exception:
        pass
    return actor


def _is_timeout_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return ("time-out" in text) or ("timeout" in text) or ("timed out" in text)


def _is_first_frame_timeout_error_text(error_text: str) -> bool:
    msg = str(error_text or "").strip().lower()
    return (
        "first_frame_timeout" in msg
        or "thesis_rig_spawn_timeout" in msg
        or "first sample timeout" in msg
        or "first_sample_timeout" in msg
        or "first_measurement_no_callbacks" in msg
        or "spawn_timeout" in msg
    )


def _map_name_contains(actual_map: Any, expected_map: str) -> bool:
    expected = str(expected_map or "").strip().lower()
    if not expected:
        return True
    actual = str(actual_map or "").strip().lower()
    return expected in actual


def _tick_snapshot(world, *, timeout_s: float = 2.0) -> Dict[str, Any]:
    """
    Single tick with correct handling in sync mode.
    Returns dict: frame_id, snapshot_frame, elapsed_seconds.
    """
    # CARLA 0.9.16 requires positional timeout argument in sync mode.
    tick_result = world.tick(float(timeout_s))
    snap = tick_result if hasattr(tick_result, "frame") else None
    frame_id = -1
    if snap is not None:
        try:
            frame_id = int(getattr(snap, "frame", -1))
        except Exception:
            frame_id = -1
    else:
        try:
            frame_id = int(tick_result) if tick_result is not None else -1
        except Exception:
            frame_id = -1
        try:
            snap = world.get_snapshot()
        except Exception:
            snap = None
    snap_frame = int(getattr(snap, "frame", -1)) if snap is not None else -1
    ts = getattr(snap, "timestamp", None) if snap is not None else None
    elapsed = float(getattr(ts, "elapsed_seconds", -1.0)) if ts is not None else -1.0
    return {
        "frame_id": int(frame_id) if frame_id is not None else -1,
        "snapshot_frame": snap_frame,
        "elapsed_seconds": elapsed,
    }


def _tick_watchdog(
    world, out_dir: Path, *, n_ticks: int = 5, tick_timeout_s: float = 2.0
) -> Dict[str, Any]:
    """
    Verify ticks advance. Writes tick_watchdog.json always.
    """
    frames = []
    elapsed = []
    for _ in range(max(1, int(n_ticks))):
        info = _tick_snapshot(world, timeout_s=float(tick_timeout_s))
        frames.append(info["frame_id"])
        elapsed.append(info["elapsed_seconds"])
    advanced = any(b > a for a, b in zip(frames, frames[1:])) or any(
        b > a for a, b in zip(elapsed, elapsed[1:])
    )
    payload = {
        "schema_version": 3,
        "n_ticks": int(n_ticks),
        "frames": frames,
        "elapsed_seconds": elapsed,
        "advanced": bool(advanced),
        "snapshot": _tick_snapshot(world, timeout_s=float(tick_timeout_s)),
    }
    _write_json(out_dir / "tick_watchdog.json", payload)
    if not advanced:
        raise RuntimeError(
            "world_not_ticking:CARLA tick did not advance "
            "(sync deadlock or session wedged). Restart CARLA."
        )
    return payload


def _world_settings_match(world, *, fps: int) -> bool:
    try:
        current = world.get_settings()
    except Exception:
        return False
    expected_dt = 1.0 / float(max(1, int(fps)))
    got_sync = bool(getattr(current, "synchronous_mode", False))
    got_dt = float(getattr(current, "fixed_delta_seconds", 0.0) or 0.0)
    return got_sync and abs(got_dt - expected_dt) <= 1e-4


def _sensor_has_frames(
    sensor_counts: Dict[str, Any], sensor_names: list[str], *, fallback_count: int = 0
) -> bool:
    if int(fallback_count) > 0:
        return True
    if not sensor_names:
        return False
    for name in sensor_names:
        try:
            if int(sensor_counts.get(name, 0) or 0) > 0:
                return True
        except Exception:
            continue
    return False


def _first_measurement_callbacks_ready(
    tick_state: Dict[str, Any],
    *,
    rgb_sensor_names: list[str],
    require_semseg: bool,
    semseg_sensor_names: list[str],
) -> bool:
    counts = tick_state.get("sensor_frame_counts", {})
    if not isinstance(counts, dict):
        counts = {}
    rgb_ready = _sensor_has_frames(
        counts,
        rgb_sensor_names,
        fallback_count=int(tick_state.get("saved_images", 0) or 0),
    )
    if not rgb_ready:
        return False
    if not require_semseg:
        return True
    return _sensor_has_frames(
        counts,
        semseg_sensor_names,
        fallback_count=int(tick_state.get("saved_semseg", 0) or 0),
    )


def _call_with_timeout(
    fn, *, timeout_s: float, timeout_error: str
) -> Any:
    state: Dict[str, Any] = {"done": False, "result": None, "error": None}

    def _runner() -> None:
        try:
            state["result"] = fn()
        except Exception as exc:  # pragma: no cover - CARLA runtime dependent
            state["error"] = exc
        finally:
            state["done"] = True

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=max(0.2, float(timeout_s)))
    if t.is_alive():
        raise RuntimeError(str(timeout_error))
    if state.get("error") is not None:
        raise state["error"]  # type: ignore[misc]
    return state.get("result")


def _is_attach_retryable_error(error_text: str) -> bool:
    msg = str(error_text or "").strip().lower()
    return (
        "parent actor not found" in msg
        or "rpc" in msg
        or "time-out" in msg
        or "timed out" in msg
        or "timeout" in msg
    )


def _verify_ego_alive(world, ego_actor, retries: int = 3, wait_s: float = 2.0) -> bool:
    """Confirm ego actor is registered in world before attaching sensors."""
    try:
        ego_id = int(getattr(ego_actor, "id", 0) or 0)
    except Exception:
        return False
    if ego_id <= 0:
        return False
    for _attempt in range(max(1, int(retries))):
        try:
            actor = world.get_actor(int(ego_id))
            if actor is not None:
                return True
        except Exception:
            pass
        time.sleep(max(0.0, float(wait_s)))
    return False


def _get_rpc_timeout_for_map(spawn_point_count: int) -> float:
    count = int(max(0, int(spawn_point_count)))
    if count > 10000:
        return 60.0
    if count > 1000:
        return 30.0
    return 15.0


def _settle_ego_for_attach(
    world,
    *,
    is_xodr_mode: bool,
    tick_timeout_s: float,
) -> None:
    if not bool(is_xodr_mode):
        return
    # For XODR in async mode, give CARLA a short settle window without forcing a sync tick.
    _ = float(tick_timeout_s)  # kept for call-site compatibility and telemetry parity
    time.sleep(2.0)


def _spawn_sensor_with_retry(
    client,
    world,
    bp,
    transform,
    *,
    attach_to,
    retries: int = 3,
    wait_s: float = 1.5,
    sensor_name: str = "sensor",
):
    import carla  # type: ignore

    last_exc: Optional[Exception] = None
    max_attempts = max(1, int(retries))
    use_legacy_attach = False
    for attempt in range(max_attempts):
        try:
            if not bool(use_legacy_attach):
                parent_id = int(getattr(attach_to, "id", 0) or 0)
                if parent_id <= 0:
                    raise RuntimeError("invalid_attach_parent_id")
                try:
                    batch = [carla.command.SpawnActor(bp, transform, parent_id)]
                except Exception:
                    # CARLA build may not expose SpawnActor(parent_id) overload.
                    use_legacy_attach = True
                else:
                    responses = client.apply_batch_sync(batch, True)
                    if responses and not responses[0].error:
                        actor_id = int(getattr(responses[0], "actor_id", 0) or 0)
                        actor = world.get_actor(actor_id) if actor_id > 0 else None
                        if actor is not None:
                            return actor
                    err = responses[0].error if responses else "no_response"
                    raise RuntimeError(f"spawn_actor_returned_none_or_error:{err}")

            # Fallback path for CARLA variants where parent-id batch attach is unavailable.
            try:
                client.apply_batch_sync([], True)
            except Exception:
                time.sleep(0.5)
            actor = world.spawn_actor(bp, transform, attach_to=attach_to)
            if actor is not None:
                return actor
            raise RuntimeError("spawn_actor_returned_none_or_error")
        except Exception as exc:
            last_exc = exc
            retryable = _is_attach_retryable_error(str(exc))
            if retryable and attempt < (max_attempts - 1):
                time.sleep(max(0.0, float(wait_s) * float(attempt + 1)))
                continue
            raise RuntimeError(
                f"SENSOR_ATTACH_FAILED:{sensor_name}:attempt={int(attempt + 1)}:{exc}"
            ) from exc
    raise RuntimeError(
        f"SENSOR_ATTACH_FAILED:{sensor_name}:retries_exhausted:{last_exc}"
    )


@contextmanager
def _temporary_env_override(name: str, value: Optional[str]):
    prior = os.environ.get(name, None)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = str(value)
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = prior


def _read_json_if_dict(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sensor_kind_from_name(sensor_name: str) -> str:
    name = str(sensor_name or "").strip().lower()
    if "lidar" in name:
        return "lidar"
    if name.startswith("seg_") or name.startswith("semseg_") or "semantic" in name:
        return "semseg_raw"
    return "rgb"


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _count_saved_sensor_files(sensor_dir: Path, sensor_kind: str) -> int:
    if not sensor_dir.is_dir():
        return 0
    if str(sensor_kind) == "lidar":
        return sum(1 for _ in sensor_dir.glob("*.ply")) + sum(
            1 for _ in sensor_dir.glob("*.npz")
        )
    count = 0
    for pattern in ("*.png", "*.jpg", "*.jpeg"):
        count += sum(1 for _ in sensor_dir.glob(pattern))
    return int(count)


def _scan_recorded_artifacts_for_manifest(out_dir: Path) -> Dict[str, Any]:
    per_sensor_counts: Dict[str, Dict[str, Any]] = {}
    sensor_frame_counts: Dict[str, int] = {}
    output_dirs: Dict[str, str] = {}
    counts = {
        "rgb_files": 0,
        "semseg_files": 0,
        "lidar_files": 0,
    }
    kind_roots = (
        ("rgb", "rgb_files"),
        ("semseg_raw", "semseg_files"),
        ("lidar", "lidar_files"),
    )
    for kind, total_key in kind_roots:
        root_dir = out_dir / kind
        if not root_dir.is_dir():
            continue
        for sensor_dir in sorted(
            [p for p in root_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower()
        ):
            frame_count = _count_saved_sensor_files(sensor_dir, kind)
            if frame_count <= 0:
                continue
            sensor_name = str(sensor_dir.name)
            sensor_frame_counts[sensor_name] = int(frame_count)
            per_sensor_counts[sensor_name] = {
                "kind": kind,
                "frames": int(frame_count),
                "rgb_frames": int(frame_count) if kind == "rgb" else 0,
                "lidar_frames": int(frame_count) if kind == "lidar" else 0,
            }
            output_dirs[sensor_name] = str(sensor_dir)
            counts[total_key] += int(frame_count)

        root_level_count = _count_saved_sensor_files(root_dir, kind)
        if root_level_count > 0:
            root_sensor_name = f"{kind}_root"
            if root_sensor_name in sensor_frame_counts:
                root_sensor_name = f"{root_sensor_name}_files"
            sensor_frame_counts[root_sensor_name] = int(root_level_count)
            per_sensor_counts[root_sensor_name] = {
                "kind": kind,
                "frames": int(root_level_count),
                "rgb_frames": int(root_level_count) if kind == "rgb" else 0,
                "lidar_frames": int(root_level_count) if kind == "lidar" else 0,
            }
            output_dirs[root_sensor_name] = str(root_dir)
            counts[total_key] += int(root_level_count)

    counts["total_files"] = int(
        _int_or_zero(counts.get("rgb_files"))
        + _int_or_zero(counts.get("semseg_files"))
        + _int_or_zero(counts.get("lidar_files"))
    )
    sensors_payload = [
        {
            "name": sensor_name,
            "kind": str(per_sensor_counts.get(sensor_name, {}).get("kind", "rgb")),
            "type_id": "",
            "frame_count": int(sensor_frame_counts.get(sensor_name, 0)),
            "output_dir": str(
                output_dirs.get(
                    sensor_name,
                    out_dir
                    / str(per_sensor_counts.get(sensor_name, {}).get("kind", "rgb"))
                    / sensor_name,
                )
            ),
        }
        for sensor_name in sorted(sensor_frame_counts.keys())
    ]
    return {
        "sensors": sensors_payload,
        "per_sensor_counts": per_sensor_counts,
        "sensor_frame_counts": sensor_frame_counts,
        "counts": counts,
        "output_dirs": output_dirs,
    }


def _sensor_profile_kind(sensor_name: str, report_entry: Optional[Dict[str, Any]]) -> str:
    report_type = ""
    if isinstance(report_entry, dict):
        report_type = str(report_entry.get("type", "") or "").strip().lower()
    if report_type == "lidar":
        return "lidar"
    if report_type in {"semseg", "semantic_segmentation"}:
        return "semseg"
    if report_type in {"camera", "rgb"}:
        return "camera"
    name = str(sensor_name or "").strip().lower()
    if "lidar" in name:
        return "lidar"
    if name.startswith("seg_") or name.startswith("semseg_") or "semantic" in name:
        return "semseg"
    return "camera"


def _apply_front_only_profile(
    *,
    sensors: Dict[str, Any],
    rig_report: Dict[str, Any],
    seg_enabled: bool,
) -> Dict[str, Any]:
    names = sorted(str(name) for name in sensors.keys())
    kinds: Dict[str, str] = {}
    for name in names:
        report_entry = rig_report.get(name) if isinstance(rig_report, dict) else None
        kinds[name] = _sensor_profile_kind(name, report_entry if isinstance(report_entry, dict) else None)

    camera_names = [name for name in names if kinds.get(name) == "camera"]
    lidar_names = [name for name in names if kinds.get(name) == "lidar"]
    semseg_names = [name for name in names if kinds.get(name) == "semseg"]

    if not camera_names:
        raise RuntimeError("sensor_spawn_missing_required_modalities:rgb")
    if not lidar_names:
        raise RuntimeError("sensor_spawn_missing_required_modalities:lidar")

    front_camera_names = [
        name for name in camera_names if "front" in str(name).strip().lower()
    ]
    if not front_camera_names:
        front_camera_names = [sorted(camera_names)[0]]
    primary_lidar = sorted(lidar_names)[0]

    keep: set[str] = set(front_camera_names + [primary_lidar])
    if seg_enabled and semseg_names:
        semseg_keep: List[str] = []
        for semseg_name in semseg_names:
            semseg_lower = str(semseg_name).strip().lower()
            if "front" in semseg_lower:
                semseg_keep.append(semseg_name)
                continue
            if any(cam.lower() in semseg_lower for cam in front_camera_names):
                semseg_keep.append(semseg_name)
        if not semseg_keep:
            semseg_keep = [sorted(semseg_names)[0]]
        keep.update(semseg_keep)

    dropped: List[str] = []
    for name in names:
        if name in keep:
            continue
        actor = sensors.pop(name, None)
        if actor is not None:
            _safe_destroy(actor)
        if isinstance(rig_report, dict):
            rig_report.pop(name, None)
        dropped.append(name)

    kept_sorted = sorted(str(name) for name in sensors.keys())
    return {
        "active": True,
        "kept": kept_sorted,
        "dropped": dropped,
        "front_cameras": sorted(front_camera_names),
        "primary_lidar": str(primary_lidar),
    }


def _classify_capture_failure_reason(
    error_text: str,
    *,
    requested_town: str,
    use_current_world: bool,
    listen_attach_status: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    msg = str(error_text or "").strip().lower()
    if "ego_lost_before_attach" in msg:
        return "EGO_LOST_BEFORE_ATTACH"
    if "sensor_attach_failed" in msg:
        return "SENSOR_ATTACH_FAILED"
    if ("world_not_ticking" in msg) or ("tick did not advance" in msg):
        return "WORLD_NOT_TICKING"
    if "wrong_map_loaded" in msg:
        return "WRONG_MAP_LOADED"
    if "map_travel_risk_grid0821" in msg:
        return "MAP_TRAVEL_RISK_GRID0821"
    if "map_travel_risk" in msg:
        return "MAP_TRAVEL_RISK"
    if "streaming_collapse_during_capture" in msg or "pre_spawn_stream_unavailable" in msg:
        return "STREAMING_COLLAPSE_DURING_CAPTURE"
    if _is_first_frame_timeout_error_text(msg):
        return "first_frame_timeout"
    if (
        "sensor_spawn_failed" in msg
        or "sensor_spawn_missing_required_modalities" in msg
        or "ego_spawn_failed_or_timeout" in msg
    ):
        return "SENSOR_SPAWN_FAILED"
    if "listen_failed" in msg or "listen_unsupported" in msg:
        return "LISTEN_FAILED"
    if (
        "no_frames_received" in msg
        or "first_measurement_no_callbacks" in msg
        or "no_sensor_measurements" in msg
    ):
        return "NO_FRAMES_RECEIVED"
    if str(requested_town or "").strip().lower() == "grid0821" and not bool(
        use_current_world
    ):
        return "MAP_TRAVEL_RISK_GRID0821"
    if isinstance(listen_attach_status, dict):
        for payload in listen_attach_status.values():
            if not isinstance(payload, dict):
                continue
            if str(payload.get("error", "") or "").strip():
                return "LISTEN_FAILED"
    return "CAPTURE_RUNTIME_ERROR"


def _ensure_failure_manifest(
    *,
    out_dir: Path,
    sensor_names: List[str],
    carla_map_name: str,
    sync_settings: Dict[str, Any],
    failure_reason: str,
    listen_errors: List[str],
) -> str:
    manifest_path = out_dir / "recorder_manifest.json"
    existing = _read_json_if_dict(manifest_path)

    existing_counts = existing.get("counts", {}) if isinstance(existing, dict) else {}
    existing_total_files = _int_or_zero(
        existing_counts.get("total_files", 0) if isinstance(existing_counts, dict) else 0
    )
    existing_sensors = existing.get("sensors", []) if isinstance(existing, dict) else []
    existing_sensor_count = len(existing_sensors) if isinstance(existing_sensors, list) else 0

    scan_payload = _scan_recorded_artifacts_for_manifest(out_dir)
    scan_counts = scan_payload.get("counts", {})
    scan_total_files = _int_or_zero(
        scan_counts.get("total_files", 0) if isinstance(scan_counts, dict) else 0
    )
    scan_sensors = scan_payload.get("sensors", [])
    scan_sensor_count = len(scan_sensors) if isinstance(scan_sensors, list) else 0

    needs_salvage = bool(
        scan_total_files > existing_total_files
        or (scan_total_files > 0 and existing_total_files <= 0)
        or (scan_sensor_count > 0 and existing_sensor_count <= 0)
    )
    if existing and not needs_salvage:
        return str(manifest_path)

    unique_sensor_names: List[str] = []
    seen: set[str] = set()
    for sensor_name in sensor_names:
        name = str(sensor_name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        unique_sensor_names.append(name)

    if isinstance(existing_sensors, list):
        for entry in existing_sensors:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            unique_sensor_names.append(name)
    existing_sensor_frame_counts_raw = (
        existing.get("sensor_frame_counts", {}) if isinstance(existing, dict) else {}
    )
    if isinstance(existing_sensor_frame_counts_raw, dict):
        for sensor_name in existing_sensor_frame_counts_raw.keys():
            name = str(sensor_name or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            unique_sensor_names.append(name)

    if not unique_sensor_names:
        unique_sensor_names = ["sensor_unavailable"]

    per_sensor_counts_raw = scan_payload.get("per_sensor_counts", {})
    per_sensor_counts: Dict[str, Dict[str, Any]] = (
        dict(per_sensor_counts_raw) if isinstance(per_sensor_counts_raw, dict) else {}
    )
    sensor_frame_counts_raw = scan_payload.get("sensor_frame_counts", {})
    sensor_frame_counts: Dict[str, int] = {}
    if isinstance(sensor_frame_counts_raw, dict):
        sensor_frame_counts = {
            str(name): _int_or_zero(value)
            for name, value in sensor_frame_counts_raw.items()
            if str(name).strip()
        }
    output_dirs_raw = scan_payload.get("output_dirs", {})
    output_dirs: Dict[str, str] = (
        dict(output_dirs_raw) if isinstance(output_dirs_raw, dict) else {}
    )

    if isinstance(existing_sensor_frame_counts_raw, dict):
        for sensor_name, raw_count in existing_sensor_frame_counts_raw.items():
            name = str(sensor_name or "").strip()
            if not name:
                continue
            merged_count = max(
                _int_or_zero(sensor_frame_counts.get(name, 0)),
                _int_or_zero(raw_count),
            )
            sensor_frame_counts[name] = int(merged_count)
            kind = str(
                per_sensor_counts.get(name, {}).get("kind", _sensor_kind_from_name(name))
            )
            output_dirs.setdefault(name, str(out_dir / kind / name))
            per_sensor_counts[name] = {
                "kind": kind,
                "frames": int(merged_count),
                "rgb_frames": int(merged_count) if kind == "rgb" else 0,
                "lidar_frames": int(merged_count) if kind == "lidar" else 0,
            }

    for sensor_name in unique_sensor_names:
        if sensor_name in sensor_frame_counts:
            continue
        kind = str(
            per_sensor_counts.get(sensor_name, {}).get(
                "kind", _sensor_kind_from_name(sensor_name)
            )
        )
        sensor_frame_counts[sensor_name] = 0
        per_sensor_counts[sensor_name] = {
            "kind": kind,
            "frames": 0,
            "rgb_frames": 0,
            "lidar_frames": 0,
        }
        output_dirs.setdefault(sensor_name, str(out_dir / kind / sensor_name))

    rgb_total = 0
    semseg_total = 0
    lidar_total = 0
    sensors_payload: List[Dict[str, Any]] = []
    for sensor_name in sorted(per_sensor_counts.keys()):
        item = per_sensor_counts.get(sensor_name, {})
        kind = str(item.get("kind", _sensor_kind_from_name(sensor_name)))
        frames = _int_or_zero(item.get("frames", sensor_frame_counts.get(sensor_name, 0)))
        sensor_frame_counts[sensor_name] = int(frames)
        per_sensor_counts[sensor_name] = {
            "kind": kind,
            "frames": int(frames),
            "rgb_frames": int(frames) if kind == "rgb" else 0,
            "lidar_frames": int(frames) if kind == "lidar" else 0,
        }
        if kind == "rgb":
            rgb_total += int(frames)
        elif kind == "semseg_raw":
            semseg_total += int(frames)
        elif kind == "lidar":
            lidar_total += int(frames)
        sensors_payload.append(
            {
                "name": sensor_name,
                "kind": kind,
                "type_id": "",
                "frame_count": int(frames),
                "output_dir": str(
                    output_dirs.get(sensor_name, str(out_dir / kind / sensor_name))
                ),
            }
        )

    timestamp = datetime.now(timezone.utc).isoformat()
    existing_started_utc = str(
        existing.get("started_utc") or existing.get("start_time") or timestamp
    )
    save_errors_tail: List[str] = []
    if isinstance(existing.get("save_errors_tail"), list):
        save_errors_tail.extend(str(item) for item in existing.get("save_errors_tail", []))
    save_errors_tail.extend(str(item) for item in (listen_errors or []))
    map_name = str(carla_map_name or existing.get("carla_map_name") or "UNKNOWN")
    world_settings = (
        dict(sync_settings)
        if isinstance(sync_settings, dict) and sync_settings
        else (
            dict(existing.get("carla_world_settings", {}))
            if isinstance(existing.get("carla_world_settings"), dict)
            else {}
        )
    )
    manifest_payload = dict(existing) if isinstance(existing, dict) else {}
    manifest_payload.update(
        {
            "schema_version": 1,
            "started_utc": existing_started_utc,
            "closed_utc": timestamp,
            "start_time": existing_started_utc,
            "end_time": timestamp,
            "output_dir": str(out_dir),
            "output_roots": {
                "rgb": str(out_dir / "rgb"),
                "semseg": str(out_dir / "semseg_raw"),
                "lidar": str(out_dir / "lidar"),
                "meta": str(out_dir / "meta"),
            },
            "sensors": sensors_payload,
            "per_sensor_counts": per_sensor_counts,
            "sensor_frame_counts": sensor_frame_counts,
            "counts": {
                "rgb_files": int(rgb_total),
                "semseg_files": int(semseg_total),
                "lidar_files": int(lidar_total),
                "total_files": int(rgb_total + semseg_total + lidar_total),
            },
            "save_errors_tail": save_errors_tail[-100:],
            "last_tick_snapshot": existing.get("last_tick_snapshot"),
            "manifest_source": (
                "record_route_fixed_failure_salvage"
                if int(rgb_total + semseg_total + lidar_total) > 0
                else "record_route_fixed_synthetic_failure"
            ),
            "error": str(failure_reason or manifest_payload.get("error", "capture_failed")),
            "carla_map_name": map_name,
            "carla_map_basename": map_name.split("/")[-1],
            "carla_world_settings": world_settings,
        }
    )
    _write_json(manifest_path, manifest_payload)
    return str(manifest_path)


def _write_capture_status_artifact(
    *,
    out_dir: Path,
    status: str,
    failure_reason: str,
    failure_detail: str,
    context: Dict[str, Any],
    operator_instruction: str = "",
) -> Dict[str, Any]:
    tick_watchdog_payload = (
        context.get("tick_watchdog_payload")
        if isinstance(context.get("tick_watchdog_payload"), dict)
        else _read_json_if_dict(out_dir / "tick_watchdog.json")
    )
    capture_summary = _read_json_if_dict(out_dir / "capture_summary.json")
    manifest_payload = _read_json_if_dict(out_dir / "recorder_manifest.json")

    sensor_frame_counts = context.get("sensor_frame_counts")
    if not isinstance(sensor_frame_counts, dict) or not sensor_frame_counts:
        sensor_frame_counts = manifest_payload.get("sensor_frame_counts", {})
    if not isinstance(sensor_frame_counts, dict):
        sensor_frame_counts = {}

    listen_attach_status = context.get("listen_attach_status")
    if not isinstance(listen_attach_status, dict):
        listen_attach_status = {}
    listen_errors = context.get("listen_errors")
    if not isinstance(listen_errors, list):
        listen_errors = []

    saved_images = int(context.get("saved_images", 0) or 0)
    saved_lidars = int(context.get("saved_lidars", 0) or 0)
    ticks_observed = int(
        context.get(
            "ticks_observed",
            capture_summary.get("frames_ticks", 0) if isinstance(capture_summary, dict) else 0,
        )
        or 0
    )
    carla_map_name = str(
        context.get("carla_map_name")
        or context.get("town")
        or manifest_payload.get("carla_map_name")
        or "UNKNOWN"
    )
    sync_settings = (
        context.get("sync_settings")
        if isinstance(context.get("sync_settings"), dict)
        else manifest_payload.get("carla_world_settings", {})
    )
    if not isinstance(sync_settings, dict):
        sync_settings = {}

    sensor_names = sorted(
        {
            str(name)
            for name in (
                list(sensor_frame_counts.keys())
                + list(listen_attach_status.keys())
                + [str(x) for x in context.get("spawned_sensors", [])]
            )
            if str(name).strip()
        }
    )

    manifest_path = str(out_dir / "recorder_manifest.json")
    if str(status or "").upper() != "OK":
        manifest_path = _ensure_failure_manifest(
            out_dir=out_dir,
            sensor_names=sensor_names,
            carla_map_name=carla_map_name,
            sync_settings=sync_settings,
            failure_reason=failure_reason,
            listen_errors=[str(item) for item in listen_errors],
        )

    payload = {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": str(status or "FAIL"),
        "failure_reason": str(failure_reason or ""),
        "failure_detail": str(failure_detail or ""),
        "operator_instruction": str(operator_instruction or ""),
        "town": str(context.get("town", "") or ""),
        "use_current_world": bool(context.get("use_current_world", False)),
        "tick_watchdog_path": str(out_dir / "tick_watchdog.json"),
        "tick_watchdog_advanced": bool(
            tick_watchdog_payload.get("advanced", False)
            if isinstance(tick_watchdog_payload, dict)
            else False
        ),
        "tick_watchdog_snapshot": (
            tick_watchdog_payload.get("snapshot", {})
            if isinstance(tick_watchdog_payload, dict)
            else {}
        ),
        "ticks_observed": int(ticks_observed),
        "listen_attach_status": dict(listen_attach_status),
        "listen_errors": [str(item) for item in listen_errors][-100:],
        "sensor_frame_counts": {
            str(name): int(value or 0)
            for name, value in sensor_frame_counts.items()
        },
        "saved_images": int(saved_images),
        "saved_lidars": int(saved_lidars),
        "carla_map_name": str(carla_map_name),
        "sync_settings": dict(sync_settings),
        "capture_summary_path": str(out_dir / "capture_summary.json"),
        "sensor_rig_report_path": str(out_dir / "sensor_rig_report.json"),
        "recorder_manifest_path": str(manifest_path),
    }
    _write_json(out_dir / "capture_status.json", payload)
    return payload


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    mg = ap.add_mutually_exclusive_group(required=True)
    mg.add_argument("--town", help="Cooked CARLA town name (Grid0828/Grid0821/etc.)")
    mg.add_argument("--xodr", help="Path to XODR map")
    ap.add_argument("--calib", required=True, help="Calibration JSON path")
    ap.add_argument(
        "--use-current-world",
        action="store_true",
        help="Do not call client.load_world. Use client.get_world and verify map name. "
        "Recommended for Grid0821 to avoid CARLA map-travel crash.",
    )
    ap.add_argument(
        "--expected-map-name",
        default="",
        help="Expected map token for world-name verification. "
        "When set, capture fails fast on map mismatch.",
    )
    ap.add_argument("--out-dir", required=True, help="Output directory")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--stream-port", type=int, default=None)
    ap.add_argument("--skip-stream-check", action="store_true")
    ap.add_argument(
        "--record-route-timeout-s",
        type=float,
        default=float(os.environ.get("UP_RECORD_ROUTE_TIMEOUT_S", "300.0")),
        help=(
            "Outer runner timeout budget in seconds for diagnostics/metadata. "
            "The wrapper may terminate capture when this budget is exceeded."
        ),
    )
    ap.add_argument(
        "--load-timeout-s",
        type=float,
        default=float(os.environ.get("UP_CARLA_LOAD_TIMEOUT_S", "180.0")),
    )
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--spawn-index", type=int, default=0)
    ap.add_argument("--vehicle", default="vehicle.audi.a2")
    ap.add_argument("--lidar-format", choices=["npz", "ply"], default="ply")
    ap.add_argument("--seg", action="store_true")
    ap.add_argument(
        "--front-only",
        action="store_true",
        help="Keep only front camera(s) and primary LiDAR to reduce streaming load.",
    )
    ap.add_argument(
        "--seg-converter", choices=["raw", "cityscapes"], default="cityscapes"
    )
    ap.add_argument("--low-mem", action="store_true")
    ap.add_argument("--rig", choices=["dominik", "thesis"], default="thesis")
    ap.add_argument(
        "--sensor-smoke",
        action="store_true",
        help="Attach sensors one-by-one (dominik rig only)",
    )
    ap.add_argument("--spawn-sanity-objects", action="store_true")
    ap.add_argument(
        "--num-npcs",
        type=int,
        default=0,
        help="Number of NPC vehicles to spawn (default 0; use 5-10 for thesis runs).",
    )
    ap.add_argument("--tick-watchdog-ticks", type=int, default=5)
    ap.add_argument(
        "--tick-timeout-s",
        type=float,
        default=float(os.environ.get("UP_CAPTURE_TICK_TIMEOUT_S", "2.0")),
    )
    ap.add_argument(
        "--max-consecutive-tick-timeouts",
        type=int,
        default=int(os.environ.get("UP_CAPTURE_MAX_TICK_TIMEOUTS", "3")),
    )
    ap.add_argument(
        "--first-measurement-timeout-s",
        type=float,
        default=float(os.environ.get("UP_CAPTURE_FIRST_MEASUREMENT_TIMEOUT_S", "10.0")),
    )
    ap.add_argument(
        "--no-frames-watchdog-ticks",
        type=int,
        default=int(os.environ.get("UP_CAPTURE_NO_FRAMES_WATCHDOG_TICKS", "30")),
    )
    ap.add_argument(
        "--no-frames-watchdog-timeout-s",
        type=float,
        default=float(os.environ.get("UP_CAPTURE_NO_FRAMES_WATCHDOG_TIMEOUT_S", "10.0")),
    )
    ap.add_argument(
        "--attach-retry-count",
        type=int,
        default=int(os.environ.get("UP_ATTACH_RETRY_COUNT", "3")),
        help="Retry count for sensor attach/spawn operations on unstable maps.",
    )
    ap.add_argument(
        "--sensor-spawn-delay",
        type=float,
        default=float(os.environ.get("UP_SENSOR_SPAWN_DELAY_S", "0.5")),
        help="Seconds to wait between individual sensor spawns (default 0.5s).",
    )
    return ap.parse_args(argv)


def _main_impl(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    os.environ["UP_SENSOR_SPAWN_DELAY_S"] = str(
        max(0.0, float(getattr(args, "sensor_spawn_delay", 0.5)))
    )
    seg_enabled = bool(args.seg)
    repo_root = _repo_root_dir()
    out_dir = Path(args.out_dir).expanduser()
    if not out_dir.is_absolute():
        out_dir = Path.cwd() / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    _LAST_CAPTURE_CONTEXT.clear()
    _LAST_CAPTURE_CONTEXT.update(
        {
            "out_dir": str(out_dir),
            "town": str(args.town or ""),
            "use_current_world": bool(args.use_current_world),
            "tick_watchdog_payload": {},
            "sensor_frame_counts": {},
            "saved_images": 0,
            "saved_lidars": 0,
            "listen_attach_status": {},
            "listen_errors": [],
            "spawned_sensors": [],
            "ticks_observed": 0,
            "carla_map_name": str(args.town or "UNKNOWN"),
            "sync_settings": {},
        }
    )
    out_dir_metadata = _portable_path_for_metadata(out_dir, repo_root=repo_root)
    calib_path = Path(args.calib).expanduser()
    if not calib_path.is_absolute():
        calib_path = Path.cwd() / calib_path
    calib_path_metadata = _portable_path_for_metadata(calib_path, repo_root=repo_root)
    gate = _thesis_capture_gate_state(str(args.rig))
    sensor_rig_report: Dict[str, Any] = {
        "schema_version": 2,
        "ok": False,
        "reason": "prelaunch",
        "rig": str(args.rig),
        "rig_attach_attempted": False,
        "calib_path_resolved": str(calib_path_metadata),
        "calib_exists": bool(calib_path.exists()),
        "calib_source": str(os.environ.get("UP_CALIB_PATH", "") or ""),
        "gating_conditions": dict(gate),
        "spawned_sensors": [],
        "listener_callbacks_registered": 0,
        "sensors": [],
    }
    _write_json(out_dir / "sensor_rig_report.json", sensor_rig_report)
    print(f"Calib path resolved to: {calib_path}", flush=True)
    # "pending (prelaunch)" is unambiguous: the rig has NOT been attempted yet.
    # This is distinct from "no" (which could mean "attempted and gated/failed").
    # run_perception_safe._extract_rig_attach_diagnostics_from_stdout looks for "yes"
    # so this will correctly parse as attempted=False until line 1299 fires.
    print("Rig attach attempted: pending (prelaunch)", flush=True)
    if not calib_path.exists():
        sensor_rig_report["reason"] = "calib_missing"
        _write_json(out_dir / "sensor_rig_report.json", sensor_rig_report)
        raise RuntimeError("calib_missing")
    if bool(gate.get("gate_required", False)) and not bool(gate.get("enabled", False)):
        sensor_rig_report["reason"] = "rig_attach_gated"
        _write_json(out_dir / "sensor_rig_report.json", sensor_rig_report)
        raise RuntimeError("rig_attach_gated:UP_ENABLE_THESIS_PERCEPTION_CAPTURE")

    # Build RecorderConfig with schema-drift guard
    cfg_kwargs = {
        "fps": int(args.fps),
        "synchronous": True,
        "fixed_delta_seconds": 1.0 / float(args.fps),
        "lidar_format": str(args.lidar_format),
        "image_format": "png",
        # seg_converter is honored as segmentation_mode: semseg_raw/ always
        # holds raw class-id labels; "cityscapes" additionally writes a
        # human-viewable palette copy to semseg_viz/ (C8).
        "segmentation_mode": str(args.seg_converter),
        "flip_vehicle_y": True,
        "opencv_camera_axes": True,
        "write_sensor_transforms": True,
        "write_world_snapshot": True,
    }
    try:
        from dataclasses import fields as _dc_fields

        allowed = {f.name for f in _dc_fields(RecorderConfig)}
        filtered = {k: v for k, v in cfg_kwargs.items() if k in allowed}
        cfg = RecorderConfig(**filtered)
    except Exception:
        cfg = RecorderConfig(
            fps=int(args.fps),
            synchronous=True,
            fixed_delta_seconds=1.0 / float(args.fps),
            lidar_format=str(args.lidar_format),
            image_format="png",
            flip_vehicle_y=True,
            opencv_camera_axes=True,
            write_sensor_transforms=True,
            write_world_snapshot=True,
        )

    resolution_override: Optional[Tuple[int, int]] = None
    if args.low_mem:
        resolution_override = (
            cfg.low_mem_resolution
            if getattr(cfg, "low_mem_resolution", None)
            else LOW_MEM_DEFAULT_RES
        )

    stream_port = int(args.stream_port) if args.stream_port is not None else (int(args.port) + 1)
    streaming_enabled = not bool(args.skip_stream_check)
    stream_required_successes = max(1, _env_int("UP_STREAM_READY_SUCCESS_STREAK", 5))
    pre_spawn_stream_wait_s = max(8.0, float(stream_required_successes) + 2.0)

    run_info = {
        "schema_version": 1,
        "town": args.town,
        "xodr": _portable_path_for_metadata(args.xodr, repo_root=repo_root),
        "rig": args.rig,
        "host": args.host,
        "port": int(args.port),
        "stream_port": int(stream_port),
        "streaming_enabled": bool(streaming_enabled),
        "skip_stream_check": bool(args.skip_stream_check),
        "stream_required_successes": int(stream_required_successes),
        "pre_spawn_stream_wait_s": float(pre_spawn_stream_wait_s),
        "record_route_timeout_s": float(args.record_route_timeout_s),
        "fps": int(args.fps),
        "duration": float(args.duration),
        "load_timeout_s": float(args.load_timeout_s),
        "tick_timeout_s": float(args.tick_timeout_s),
        "max_consecutive_tick_timeouts": int(args.max_consecutive_tick_timeouts),
        "first_measurement_timeout_s": float(args.first_measurement_timeout_s),
        "no_frames_watchdog_ticks": int(args.no_frames_watchdog_ticks),
        "no_frames_watchdog_timeout_s": float(args.no_frames_watchdog_timeout_s),
        "attach_retry_count": int(args.attach_retry_count),
        "use_current_world": bool(args.use_current_world),
        "expected_map_name": str(args.expected_map_name or ""),
        "low_mem": bool(args.low_mem),
        "synchronous_mode": False,
        "fixed_delta_seconds": float(1.0 / float(args.fps)),
        "settings_applied_before_tick": False,
        "recorder_config": asdict(cfg) if hasattr(cfg, "__dataclass_fields__") else {},
        "calib": str(calib_path_metadata),
        "output_dir": str(out_dir_metadata),
        "thesis_capture_gate": dict(gate),
        "env": {
            "UP_CAMERA_CTV_ATTACH": os.environ.get("UP_CAMERA_CTV_ATTACH"),
            "UP_CAMERA_CTV_INVERT": os.environ.get("UP_CAMERA_CTV_INVERT"),
            "UP_CAMERA_OPENCV_AXES": os.environ.get("UP_CAMERA_OPENCV_AXES"),
            "UP_STRICT_RIG_VALIDATION": os.environ.get("UP_STRICT_RIG_VALIDATION"),
            "UP_ENABLE_THESIS_PERCEPTION_CAPTURE": os.environ.get(
                "UP_ENABLE_THESIS_PERCEPTION_CAPTURE"
            ),
            "UP_CALIB_PATH": os.environ.get("UP_CALIB_PATH"),
        },
    }
    _write_json(out_dir / "run_info.json", run_info)

    print(
        "[record_route_fixed] "
        f"rpc_port={int(args.port)} "
        f"streaming_enabled={str(bool(streaming_enabled)).lower()} "
        f"stream_port={int(stream_port)} "
        "sync_mode=deferred_until_after_attach "
        f"fixed_delta={1.0 / float(max(1, int(args.fps))):.6f}",
        flush=True,
    )

    # Lazy CARLA import
    import carla  # type: ignore

    client = carla.Client(args.host, int(args.port))
    client.set_timeout(float(args.load_timeout_s))

    # Load world
    if args.use_current_world:
        world = client.get_world()
        current = None
        try:
            current = world.get_map().name
        except Exception:
            current = None
        expected_map_name = str(args.expected_map_name or args.town or "").strip()
        if expected_map_name:
            # CARLA may return '/Game/Carla/Maps/Grid0821' or just 'Grid0821'
            if current is None or (not _map_name_contains(current, expected_map_name)):
                raise RuntimeError(
                    "wrong_map_loaded:"
                    f"expected={expected_map_name}:actual={current!r}"
                )
    else:
        if args.town:
            if str(args.town).strip().lower() == "grid0821":
                raise RuntimeError(
                    "map_travel_risk_grid0821: risky load_world on Grid0821 is blocked by default. "
                    "Load Grid0821 manually in CARLA and rerun with --use-current-world."
                )
            world = client.load_world(args.town)
        else:
            xodr_text = Path(args.xodr).read_text(encoding="utf-8", errors="replace")
            from ultimate_pipeline.core.carla_opendrive_loader import (
                load_opendrive_world,
            )

            world = load_opendrive_world(
                client,
                xodr_text,
                timeout_s=float(args.load_timeout_s),
                ready_timeout_s=float(args.load_timeout_s),
                retries=1,
                do_reload=True,
            )
    expected_map_name = str(args.expected_map_name or args.town or "").strip()
    if expected_map_name:
        loaded_map_name = ""
        try:
            loaded_map_name = str(world.get_map().name)
        except Exception:
            loaded_map_name = ""
        if not _map_name_contains(loaded_map_name, expected_map_name):
            raise RuntimeError(
                "wrong_map_loaded:"
                f"expected={expected_map_name}:actual={loaded_map_name!r}"
            )
    try:
        _LAST_CAPTURE_CONTEXT["carla_map_name"] = str(world.get_map().name)
    except Exception:
        _LAST_CAPTURE_CONTEXT["carla_map_name"] = str(args.town or "UNKNOWN")
    world = _maybe_reload_world_for_stream_flush(
        client=client,
        world=world,
        fps=float(args.fps),
    )
    try:
        _LAST_CAPTURE_CONTEXT["carla_map_name"] = str(world.get_map().name)
    except Exception:
        _LAST_CAPTURE_CONTEXT["carla_map_name"] = str(args.town or "UNKNOWN")
    # Warmup in async mode first
    try:
        if bool(getattr(world.get_settings(), "synchronous_mode", False)):
            for _ in range(5):
                world.tick(5.0)
        else:
            for _ in range(5):
                world.wait_for_tick(5.0)
    except Exception:
        pass

    # Scale RPC timeout by map size, with a 30s minimum before any sensor operations.
    spawn_points_count = 0
    try:
        spawn_points_count = int(len(_spawn_points_with_waypoint_fallback(world)))
    except Exception:
        spawn_points_count = 0
    runtime_timeout_s = max(30.0, float(_get_rpc_timeout_for_map(spawn_points_count)))
    try:
        client.set_timeout(float(runtime_timeout_s))
    except Exception:
        pass

    original_settings = world.get_settings()
    applied_world_settings = {
        "synchronous_mode": bool(
            getattr(original_settings, "synchronous_mode", False)
        ),
        "fixed_delta_seconds": float(
            getattr(original_settings, "fixed_delta_seconds", 0.0) or 0.0
        ),
        "substepping": bool(getattr(original_settings, "substepping", False))
        if hasattr(original_settings, "substepping")
        else None,
    }
    _LAST_CAPTURE_CONTEXT["sync_settings"] = dict(applied_world_settings)
    settings_applied_before_tick = False
    run_info["rpc_timeout_s"] = float(runtime_timeout_s)
    run_info["spawn_points_count"] = int(spawn_points_count)
    run_info["ego_spawn_method"] = "batch_sync"
    run_info["sensor_spawn_method"] = "batch_sync_with_legacy_fallback"
    run_info["synchronous_mode"] = bool(applied_world_settings["synchronous_mode"])
    run_info["fixed_delta_seconds"] = float(
        applied_world_settings["fixed_delta_seconds"]
    )
    run_info["settings_applied_before_tick"] = bool(settings_applied_before_tick)
    _write_json(out_dir / "run_info.json", run_info)

    # Spawn ego
    bp_lib = world.get_blueprint_library()
    candidates = bp_lib.filter(args.vehicle)
    if not candidates:
        raise RuntimeError(f"Vehicle blueprint not found: {args.vehicle}")
    veh_bp = candidates[0]
    spawns = _spawn_points_with_waypoint_fallback(world)
    run_info["spawn_points_count_from_map"] = int(len(spawns))
    if not spawns:
        raise RuntimeError("no_valid_spawn_points")
    spawn_index = max(0, min(int(args.spawn_index), len(spawns) - 1))
    ego = None
    batch_errors: List[Dict[str, Any]] = []
    candidate_indices = [spawn_index, 0, 1, 2, 3, 4, 5, 50, 100, 500]
    seen_indices = set()
    for i in candidate_indices:
        if not (0 <= int(i) < len(spawns)):
            continue
        if int(i) in seen_indices:
            continue
        seen_indices.add(int(i))
        try:
            batch = [carla.command.SpawnActor(veh_bp, spawns[int(i)])]
            responses = client.apply_batch_sync(batch, True)
            if responses and not responses[0].error:
                actor_id = int(getattr(responses[0], "actor_id", 0) or 0)
                ego_candidate = world.get_actor(actor_id) if actor_id > 0 else None
                if ego_candidate is None:
                    err = f"actor_not_materialized:actor_id={int(actor_id)}"
                    print(f"[ego_spawn] batch attempt {i} failed: {err}", flush=True)
                    batch_errors.append({"index": int(i), "error": str(err)})
            else:
                err = str(responses[0].error) if responses else "no_response"
                print(f"[ego_spawn] batch attempt {i} failed: {err}", flush=True)
                batch_errors.append({"index": int(i), "error": str(err)})
                ego_candidate = None
        except Exception as _esp:
            print(f"[ego_spawn] batch attempt {i} exception: {_esp}", flush=True)
            batch_errors.append({"index": int(i), "error": f"exception:{_esp}"})
            ego_candidate = None
        if ego_candidate is not None:
            ego = ego_candidate
            spawn_index = int(i)
            break
    run_info["ego_batch_spawn_errors"] = list(batch_errors)
    _write_json(out_dir / "run_info.json", run_info)
    if ego is None:
        # Batch spawn failed (common on XODR OpenDriveMap tiles).
        # Fall back: spawn_actor at multiple heights, then confirm liveness after a tick.
        print(
            "[ego_spawn] batch failed for all candidates - trying legacy "
            "spawn_actor fallback",
            flush=True,
        )
        fallback_transforms = [
            carla.Transform(carla.Location(x=0.0, y=0.0, z=10.0), carla.Rotation(yaw=0.0)),
            carla.Transform(carla.Location(x=0.0, y=0.0, z=5.0), carla.Rotation(yaw=0.0)),
            carla.Transform(carla.Location(x=0.0, y=0.0, z=2.0), carla.Rotation(yaw=0.0)),
            carla.Transform(carla.Location(x=5.0, y=0.0, z=5.0), carla.Rotation(yaw=0.0)),
            carla.Transform(carla.Location(x=10.0, y=0.0, z=5.0), carla.Rotation(yaw=0.0)),
        ]
        for _ftf in fallback_transforms:
            try:
                _candidate = _spawn_actor_with_tick_validation(
                    world,
                    veh_bp,
                    _ftf,
                    tick_timeout_s=float(args.tick_timeout_s),
                )
            except RuntimeError as _fe:
                print(f"[ego_spawn] legacy fallback exception: {_fe}", flush=True)
                _candidate = None
            except Exception as _fe:
                print(f"[ego_spawn] legacy fallback exception: {_fe}", flush=True)
                _candidate = None
            if _candidate is not None:
                # Force a physics server tick so actor is confirmed, not in "pending" state.
                try:
                    client.apply_batch_sync([], True)
                    time.sleep(0.5)
                    client.apply_batch_sync([], True)
                except Exception:
                    pass
                ego = _candidate
                run_info["ego_spawn_method"] = "legacy_spawn_actor_fallback"
                _write_json(out_dir / "run_info.json", run_info)
                print(f"[ego_spawn] legacy fallback succeeded at {_ftf.location}", flush=True)
                break
        if ego is None:
            run_info["ego_spawn_method"] = "all_failed"
            run_info["ego_batch_spawn_errors"] = list(batch_errors)
            _write_json(out_dir / "run_info.json", run_info)
            raise RuntimeError("ego_spawn_failed_all_candidates")

    _write_json(
        out_dir / "ego_spawn.json", {"vehicle": veh_bp.id, "spawn_index": spawn_index}
    )
    if str(run_info.get("ego_spawn_method", "")).strip().lower() not in (
        "legacy_spawn_actor_fallback",
        "all_failed",
    ):
        run_info["ego_spawn_method"] = "batch_sync"
    run_info["sensor_spawn_method"] = "batch_sync_with_legacy_fallback"
    _write_json(out_dir / "run_info.json", run_info)

    npc_actors = []
    npc_spawn_report: Dict[str, Any] = {
        "requested": int(args.num_npcs),
        "spawned": 0,
        "mode": "disabled",
    }
    if int(args.num_npcs) > 0:
        spawn_points = _spawn_points_with_waypoint_fallback(world)
        bp_lib = world.get_blueprint_library()
        vehicle_bps = [
            bp
            for bp in bp_lib.filter("vehicle.*")
            if bp.has_attribute("number_of_wheels")
            and bp.get_attribute("number_of_wheels").as_int() == 4
        ]
        usable_spawn_points = max(0, len(spawn_points) - 1)
        if not vehicle_bps or usable_spawn_points <= 0:
            npc_spawn_report = {
                "requested": int(args.num_npcs),
                "spawned": 0,
                "mode": "skipped",
                "reason": "no_spawn_points_or_blueprints",
                "spawn_points_available": int(len(spawn_points)),
                "vehicle_blueprints_available": int(len(vehicle_bps)),
            }
        else:
            import random as _random

            _random.seed(42)
            npc_count = min(int(args.num_npcs), usable_spawn_points)
            batch_cmds = []
            for i in range(1, npc_count + 1):
                bp = _random.choice(vehicle_bps)
                sp = spawn_points[i % len(spawn_points)]
                batch_cmds.append(carla.command.SpawnActor(bp, sp))

            responses = client.apply_batch_sync(batch_cmds, True)
            spawned_ids = []
            failed_responses = []
            for idx, response in enumerate(responses):
                if response.error:
                    failed_responses.append(
                        {"batch_index": int(idx), "error": str(response.error)}
                    )
                    continue
                spawned_ids.append(int(response.actor_id))

            if spawned_ids:
                npc_actors = list(world.get_actors(spawned_ids))
            npc_spawn_report = {
                "requested": int(args.num_npcs),
                "spawned": int(len(spawned_ids)),
                "mode": "batch_sync",
                "actor_ids": spawned_ids,
                "spawn_points_available": int(len(spawn_points)),
                "vehicle_blueprints_available": int(len(vehicle_bps)),
                "failed_count": int(len(failed_responses)),
                "failed_responses": failed_responses,
            }
    _write_json(out_dir / "npc_spawn_report.json", npc_spawn_report)

    # Optional sanity props
    sanity_actors = []
    if args.spawn_sanity_objects:
        try:
            cone = bp_lib.find("static.prop.constructioncone")
            if cone is not None:
                tf = ego.get_transform()
                loc = tf.transform(carla.Location(x=8.0, y=1.5, z=0.0))
                try:
                    a = world.spawn_actor(cone, carla.Transform(loc, tf.rotation))
                except RuntimeError:
                    a = None
                if a is not None:
                    sanity_actors.append(a)
        except Exception:
            pass

    xodr_mode = bool(args.xodr and not args.town)
    attach_retry_count = max(1, int(args.attach_retry_count))
    _settle_ego_for_attach(
        world,
        is_xodr_mode=bool(xodr_mode),
        tick_timeout_s=float(args.tick_timeout_s),
    )
    if not _verify_ego_alive(
        world,
        ego,
        retries=max(3, int(attach_retry_count)),
        wait_s=0.5,
    ):
        sensor_rig_report["ok"] = False
        sensor_rig_report["reason"] = "ego_lost_before_attach"
        sensor_rig_report["error"] = "SENSOR_ATTACH_FAILED:ego_lost_before_attach"
        sensor_rig_report["attach_retry_count"] = int(attach_retry_count)
        _write_json(out_dir / "sensor_rig_report.json", sensor_rig_report)
        raise RuntimeError("SENSOR_ATTACH_FAILED:ego_lost_before_attach")

    # Spawn sensors
    sensors: Dict[str, Any] = {}
    rig_report: Dict[str, Any] = {}
    rig: Any = None
    rig_attach_attempted = False
    listener_callbacks_registered = 0
    front_only_profile = {
        "active": bool(args.front_only),
        "kept": [],
        "dropped": [],
        "front_cameras": [],
        "primary_lidar": "",
    }
    try:
        if streaming_enabled:
            _stream_ok = _run_stream_precheck(
                host=str(args.host),
                stream_port=int(stream_port),
                pre_spawn_stream_wait_s=float(pre_spawn_stream_wait_s),
                stream_required_successes=int(stream_required_successes),
                sensor_rig_report=sensor_rig_report,
            )
            if not _stream_ok:
                # Streaming port is not open — sensor callbacks will never fire.
                # Raise early rather than spawning sensors that silently get 0 callbacks.
                raise RuntimeError(
                    "pre_spawn_stream_unavailable: streaming port not ready before sensor spawn"
                )
        print("Rig attach attempted: yes", flush=True)
        rig_attach_attempted = True
        sensor_rig_report["rig_attach_attempted"] = True
        sensor_rig_report["reason"] = "attach_attempt_started"
        _write_json(out_dir / "sensor_rig_report.json", sensor_rig_report)
        if args.rig == "thesis":
            from ultimate_pipeline.carla_tools.thesis_sensor_rig import (
                ThesisSensorRig,
                wait_for_first_sample,
            )

            rig = ThesisSensorRig(str(calib_path))
            if hasattr(rig, "set_spawn_report_path"):
                try:
                    rig.set_spawn_report_path(out_dir / "sensor_rig_report.json")
                except Exception:
                    pass
            if hasattr(rig, "set_client"):
                try:
                    rig.set_client(client)
                except Exception:
                    pass
            # Avoid unbounded healthcheck ticks during Grid bring-up; callback
            # readiness is enforced separately in this runner.
            if hasattr(rig, "ENABLE_SENSOR_HEALTHCHECK"):
                try:
                    rig.ENABLE_SENSOR_HEALTHCHECK = False
                except Exception:
                    pass
            grid_rig_mode = str(args.town or "").strip().lower().startswith("grid08")
            # Grid maps can exceed the short runtime RPC timeout at first attach_to.
            # Keep this widening scoped to thesis rig spawn and restore afterwards.
            grid_spawn_rpc_timeout_s = (
                max(120.0, float(runtime_timeout_s))
                if grid_rig_mode
                else float(runtime_timeout_s)
            )
            grid_spawn_watchdog_timeout_s = float(grid_spawn_rpc_timeout_s)
            if grid_rig_mode:
                override_raw = str(
                    os.environ.get("UP_CAPTURE_RIG_SPAWN_TIMEOUT_S", "") or ""
                ).strip()
                if override_raw:
                    try:
                        override_s = float(override_raw)
                        if override_s > 0.0:
                            grid_spawn_watchdog_timeout_s = max(
                                float(grid_spawn_rpc_timeout_s), float(override_s)
                            )
                            # Also widen the CARLA client RPC timeout so the server
                            # doesn't time-out before it finishes camera render init
                            # on large cooked maps (Grid0828 may take >120 s).
                            grid_spawn_rpc_timeout_s = max(
                                float(grid_spawn_rpc_timeout_s), float(override_s)
                            )
                    except (TypeError, ValueError):
                        pass
            if grid_rig_mode:
                try:
                    client.set_timeout(float(grid_spawn_rpc_timeout_s))
                except Exception:
                    pass
            try:
                spawn_timeout_s = (
                    float(grid_spawn_watchdog_timeout_s)
                    if grid_rig_mode
                    else max(20.0, float(args.first_measurement_timeout_s) * 2.0)
                )
                bootstrap_grid_front_only = bool(
                    str(args.town or "").strip().lower() == "grid0821"
                    and (not bool(args.front_only))
                )

                def _spawn_thesis_once(*, force_front_only_strict: Optional[bool]):
                    env_override = "1" if force_front_only_strict else None
                    with _temporary_env_override("UP_FRONT_ONLY_STRICT", env_override):
                        return _call_with_timeout(
                            lambda: rig.spawn_rig(world, ego),
                            timeout_s=float(spawn_timeout_s),
                            timeout_error="sensor_spawn_failed:thesis_rig_spawn_timeout",
                        )

                def _spawn_thesis_with_retries(
                    *,
                    force_front_only_strict: Optional[bool],
                    phase_name: str,
                ):
                    last_exc: Optional[Exception] = None
                    max_attempts = max(1, int(attach_retry_count))
                    for attempt in range(max_attempts):
                        if not _verify_ego_alive(
                            world,
                            ego,
                            retries=max(2, min(3, int(attach_retry_count))),
                            wait_s=0.5,
                        ):
                            raise RuntimeError(
                                "SENSOR_ATTACH_FAILED:ego_lost_before_attach"
                            )
                        _settle_ego_for_attach(
                            world,
                            is_xodr_mode=bool(xodr_mode),
                            tick_timeout_s=float(args.tick_timeout_s),
                        )
                        try:
                            return _spawn_thesis_once(
                                force_front_only_strict=force_front_only_strict
                            )
                        except Exception as exc:
                            last_exc = exc
                            retryable = _is_attach_retryable_error(str(exc))
                            if retryable and attempt < (max_attempts - 1):
                                print(
                                    f"[record_route_fixed] {phase_name} attach retry "
                                    f"{int(attempt + 1)}/{int(max_attempts)}: {exc}",
                                    flush=True,
                                )
                                time.sleep(1.5 * float(attempt + 1))
                                continue
                            raise RuntimeError(
                                "SENSOR_ATTACH_FAILED:"
                                f"{phase_name}:attempt={int(attempt + 1)}:{exc}"
                            ) from exc
                    if last_exc is not None:
                        raise RuntimeError(
                            f"SENSOR_ATTACH_FAILED:{phase_name}:retries_exhausted:{last_exc}"
                        ) from last_exc
                    raise RuntimeError(
                        f"SENSOR_ATTACH_FAILED:{phase_name}:retries_exhausted"
                    )

                staged_spawned = None
                used_bootstrap_only = False
                if bootstrap_grid_front_only:
                    staged_spawned = _spawn_thesis_with_retries(
                        force_front_only_strict=True,
                        phase_name="grid0821_front_only_bootstrap",
                    )
                    try:
                        spawned = _spawn_thesis_with_retries(
                            force_front_only_strict=False,
                            phase_name="grid0821_full_expand",
                        )
                        # Expansion succeeded; dispose bootstrap actors.
                        for staged in list((staged_spawned or {}).values()):
                            actor = getattr(staged, "actor", None)
                            if actor is not None:
                                _safe_destroy(actor)
                    except Exception as expand_exc:
                        used_bootstrap_only = True
                        print(
                            "[record_route_fixed] grid0821 full expansion failed; "
                            f"continuing with front-only bootstrap rig: {expand_exc}",
                            flush=True,
                        )
                        spawned = staged_spawned
                else:
                    spawned = _spawn_thesis_with_retries(
                        force_front_only_strict=None,
                        phase_name="thesis_rig_spawn",
                    )
            finally:
                if grid_rig_mode:
                    try:
                        client.set_timeout(float(runtime_timeout_s))
                    except Exception:
                        pass
            spawn_phase_report = _extract_thesis_spawn_phase_report(rig)
            if spawn_phase_report:
                sensor_rig_report.update(spawn_phase_report)
            if int(sensor_rig_report.get("spawn_success_count", 0) or 0) > 0 and int(listener_callbacks_registered) == 0:
                sensor_rig_report["failure_stage"] = "listener_registration"
                _write_json(out_dir / "sensor_rig_report.json", sensor_rig_report)
            sensors = {name: sp.actor for name, sp in spawned.items()}
            rig_report = {name: sp.report for name, sp in spawned.items()}
            sensor_rig_report["attach_retry_count"] = int(attach_retry_count)
            if bool(used_bootstrap_only):
                front_only_profile["active"] = True
                front_only_profile["kept"] = sorted(str(name) for name in sensors.keys())
                sensor_rig_report.setdefault("warnings", [])
                if isinstance(sensor_rig_report.get("warnings"), list):
                    sensor_rig_report["warnings"].append(
                        "grid0821_full_expand_failed_using_front_only_bootstrap"
                    )
            if seg_enabled:
                semseg_spawn_failures: list[str] = []
                semseg_spawn_retries = max(
                    1, int(os.environ.get("UP_SEMSEG_SPAWN_RETRIES", "3") or "3")
                )
                for name, sp in list(spawned.items()):
                    report = dict(sp.report or {})
                    if str(report.get("type", "")).lower() != "camera":
                        continue
                    tf_dict = dict(report.get("carla_transform") or {})
                    attrs = dict(report.get("attributes") or {})
                    seg_name = f"semseg_{name}"
                    last_exc: Optional[Exception] = None
                    for attempt_idx in range(semseg_spawn_retries):
                        try:
                            seg_tf = carla.Transform(
                                carla.Location(
                                    x=float(tf_dict.get("x", 0.0)),
                                    y=float(tf_dict.get("y", 0.0)),
                                    z=float(tf_dict.get("z", 0.0)),
                                ),
                                carla.Rotation(
                                    roll=float(tf_dict.get("roll", 0.0)),
                                    pitch=float(tf_dict.get("pitch", 0.0)),
                                    yaw=float(tf_dict.get("yaw", 0.0)),
                                ),
                            )
                            seg_bp = bp_lib.find("sensor.camera.semantic_segmentation")
                            if hasattr(seg_bp, "has_attribute") and seg_bp.has_attribute(
                                "image_size_x"
                            ):
                                seg_bp.set_attribute(
                                    "image_size_x", str(int(attrs.get("width", 1280)))
                                )
                            if hasattr(seg_bp, "has_attribute") and seg_bp.has_attribute(
                                "image_size_y"
                            ):
                                seg_bp.set_attribute(
                                    "image_size_y", str(int(attrs.get("height", 720)))
                                )
                            if hasattr(seg_bp, "has_attribute") and seg_bp.has_attribute(
                                "fov"
                            ):
                                seg_bp.set_attribute(
                                    "fov", str(float(attrs.get("fov", 90.0)))
                                )
                            parent_actor = ego
                            try:
                                parent_id = int(getattr(ego, "id", 0) or 0)
                                if parent_id > 0:
                                    parent_live = world.get_actor(parent_id)
                                    if parent_live is not None:
                                        parent_actor = parent_live
                            except Exception:
                                pass
                            try:
                                seg_actor = _spawn_sensor_with_retry(
                                    client,
                                    world,
                                    seg_bp,
                                    seg_tf,
                                    attach_to=parent_actor,
                                    retries=int(attach_retry_count),
                                    wait_s=0.5,
                                    sensor_name=f"{seg_name}:parent",
                                )
                            except RuntimeError as attach_exc:
                                attach_msg = str(attach_exc).lower()
                                if "parent actor not found" not in attach_msg:
                                    raise
                                # Fallback: attach semseg directly to the RGB camera actor
                                # with identity transform to keep viewpoints aligned.
                                seg_actor = _spawn_sensor_with_retry(
                                    client,
                                    world,
                                    seg_bp,
                                    carla.Transform(),
                                    attach_to=sp.actor,
                                    retries=int(attach_retry_count),
                                    wait_s=0.5,
                                    sensor_name=f"{seg_name}:camera_fallback",
                                )
                            sensors[seg_name] = seg_actor
                            rig_report[seg_name] = {
                                "type": "semseg",
                                "attributes": {
                                    "width": int(attrs.get("width", 1280)),
                                    "height": int(attrs.get("height", 720)),
                                    "fov": float(attrs.get("fov", 90.0)),
                                },
                                "carla_transform": {
                                    "x": float(tf_dict.get("x", 0.0)),
                                    "y": float(tf_dict.get("y", 0.0)),
                                    "z": float(tf_dict.get("z", 0.0)),
                                    "roll": float(tf_dict.get("roll", 0.0)),
                                    "pitch": float(tf_dict.get("pitch", 0.0)),
                                    "yaw": float(tf_dict.get("yaw", 0.0)),
                                },
                            }
                            last_exc = None
                            break
                        except Exception as exc:
                            last_exc = exc
                            try:
                                time.sleep(0.05)
                            except Exception:
                                pass
                            continue
                    if last_exc is not None:
                        semseg_spawn_failures.append(
                            f"{name}:{type(last_exc).__name__}:{last_exc}"
                        )
                if semseg_spawn_failures:
                    print(
                        "semseg_spawn_failures: "
                        + "; ".join(semseg_spawn_failures[:8]),
                        flush=True,
                    )
                semseg_spawned = any(
                    str(sensor_name).lower().startswith("seg_")
                    or str(sensor_name).lower().startswith("semseg_")
                    for sensor_name in sensors.keys()
                )
                if not semseg_spawned:
                    raise RuntimeError("sensor_spawn_missing_required_modalities:semseg")
            # Verify front RGB stream is live before recording.
            # Semseg sensors are already spawned above so they will receive frame 0
            # with no 1-frame lag between RGB and semseg capture.
            _front_camera = rig.get_front_rgb_camera()
            if _front_camera is None:
                for _sp in spawned.values():
                    if str((_sp.report or {}).get("type", "")).lower() == "camera":
                        _front_camera = _sp.actor
                        break
            if _front_camera is not None:
                if not wait_for_first_sample(
                    world, _front_camera, timeout=20.0, max_ticks=8
                ):
                    raise RuntimeError("sensor_stream_not_ready:front_rgb_timeout")
            if args.front_only:
                front_only_profile = _apply_front_only_profile(
                    sensors=sensors,
                    rig_report=rig_report,
                    seg_enabled=bool(seg_enabled),
                )
                print(
                    "Front-only profile active: kept="
                    + ",".join(front_only_profile.get("kept", [])),
                    flush=True,
                )
                if front_only_profile.get("dropped"):
                    print(
                        "Front-only profile dropped="
                        + ",".join(front_only_profile.get("dropped", [])),
                        flush=True,
                    )
            _write_json(out_dir / "thesis_rig_report.json", rig_report)
            sensor_rig_report = {
                "schema_version": 2,
                "ok": True,
                "reason": "spawned",
                "rig": "thesis",
                "rig_attach_attempted": bool(rig_attach_attempted),
                "calib_path_resolved": str(calib_path_metadata),
                "calib_exists": True,
                "gating_conditions": dict(gate),
                "spawned_sensors": sorted(str(name) for name in sensors.keys()),
                "listener_callbacks_registered": 0,
                "capture_profile": "front_only" if bool(args.front_only) else "full",
                "capture_profile_kept": list(front_only_profile.get("kept", [])),
                "capture_profile_dropped": list(front_only_profile.get("dropped", [])),
                "capture_profile_front_cameras": list(
                    front_only_profile.get("front_cameras", [])
                ),
                "capture_profile_primary_lidar": str(
                    front_only_profile.get("primary_lidar", "")
                ),
                "env": {
                    "UP_CAMERA_CTV_ATTACH": os.environ.get("UP_CAMERA_CTV_ATTACH"),
                    "UP_LIDAR_VTL_ATTACH": os.environ.get("UP_LIDAR_VTL_ATTACH"),
                },
                "sensors": [
                    {"name": name, **report} for name, report in rig_report.items()
                ],
            }
            sensor_rig_report.update(_extract_thesis_spawn_phase_report(rig))
            if int(sensor_rig_report.get("spawn_success_count", 0) or 0) > 0 and int(listener_callbacks_registered) == 0:
                sensor_rig_report["failure_stage"] = "listener_registration"
            _write_json(out_dir / "sensor_rig_report.json", sensor_rig_report)
        else:
            setup = DominikSensorSetup(
                str(calib_path),
                flip_vehicle_y=True,
                opencv_camera_axes=True,
                lidar_axes_mode="auto",
                verbose=False,
                resolution_override=resolution_override,
            )
            town_norm = str(args.town or "").strip().lower()
            grid_mode = town_norm.startswith("grid08")
            spawn_strict = not bool(grid_mode)
            sensors = setup.spawn_on_vehicle(
                world,
                ego,
                include_segmentation=seg_enabled,
                out_dir=str(out_dir),
                low_mem=bool(args.low_mem),
                strict=bool(spawn_strict),
                min_sensors=2 if seg_enabled else 1,
            )
            rgb_spawned = any(
                str(name).lower().startswith("rgb_") for name in sensors.keys()
            )
            semseg_spawned = any(
                str(name).lower().startswith("seg_")
                or str(name).lower().startswith("semseg_")
                for name in sensors.keys()
            )
            if not rgb_spawned:
                raise RuntimeError("sensor_spawn_missing_required_modalities:rgb")
            if seg_enabled and not semseg_spawned:
                raise RuntimeError("sensor_spawn_missing_required_modalities:semseg")
            if args.front_only:
                front_only_profile = _apply_front_only_profile(
                    sensors=sensors,
                    rig_report=rig_report,
                    seg_enabled=bool(seg_enabled),
                )
                print(
                    "Front-only profile active: kept="
                    + ",".join(front_only_profile.get("kept", [])),
                    flush=True,
                )
                if front_only_profile.get("dropped"):
                    print(
                        "Front-only profile dropped="
                        + ",".join(front_only_profile.get("dropped", [])),
                        flush=True,
                    )
            # Synthesize thesis-style rig report for run_perception_safe compatibility.
            ctv_inverted = _env_bool("UP_CAMERA_CTV_INVERT", False)
            rig_entries = []
            calib_data = dict(getattr(setup, "_calib", {}) or {})
            for cam_name, cam_data in (calib_data.get("cameras", {}) or {}).items():
                key = f"rgb_{cam_name}"
                if key not in sensors:
                    continue
                rig_entries.append(
                    {
                        "name": key,
                        "type": "camera",
                        "raw": {
                            "K_undistortion": cam_data.get("K_undistortion"),
                            "image_size": cam_data.get("image_size"),
                            "cTv": cam_data.get("cTv"),
                        },
                        "ctv_inverted": bool(ctv_inverted),
                        "inversion_applied": bool(ctv_inverted),
                        "transform_convention": "Used cTv (vehicle->camera) via canonical transform_conventions path.",
                    }
                )
            for _lid_name, lid_data in (calib_data.get("lidars", {}) or {}).items():
                if "lidar" not in sensors:
                    continue
                rig_entries.append(
                    {
                        "name": "lidar",
                        "type": "lidar",
                        "raw": {"vTl": lid_data.get("vTl")},
                        "vtl_inverted": True,
                        "inversion_applied": True,
                        "transform_convention": "Used inverse(vTl) (vehicle->lidar) via canonical transform_conventions path.",
                    }
                )
                break
            sensor_rig_report = {
                "schema_version": 2,
                "ok": True,
                "reason": "spawned",
                "rig": "dominik",
                "rig_attach_attempted": bool(rig_attach_attempted),
                "calib_path_resolved": str(calib_path_metadata),
                "calib_exists": True,
                "gating_conditions": dict(gate),
                "spawned_sensors": sorted(str(name) for name in sensors.keys()),
                "listener_callbacks_registered": 0,
                "capture_profile": "front_only" if bool(args.front_only) else "full",
                "capture_profile_kept": list(front_only_profile.get("kept", [])),
                "capture_profile_dropped": list(front_only_profile.get("dropped", [])),
                "capture_profile_front_cameras": list(
                    front_only_profile.get("front_cameras", [])
                ),
                "capture_profile_primary_lidar": str(
                    front_only_profile.get("primary_lidar", "")
                ),
                "sensors": rig_entries,
            }
            _write_json(out_dir / "sensor_rig_report.json", sensor_rig_report)
        print(f"Spawned sensors: {sorted(str(name) for name in sensors.keys())}", flush=True)
        _LAST_CAPTURE_CONTEXT["spawned_sensors"] = sorted(
            str(name) for name in sensors.keys()
        )
    except Exception as rig_exc:
        rig_exc_text = str(rig_exc or "")
        rig_exc_lower = rig_exc_text.lower()
        sensor_rig_report.update(_extract_thesis_spawn_phase_report(rig))
        spawn_response_count = int(sensor_rig_report.get("spawn_response_count", 0) or 0)
        spawn_success_count = int(sensor_rig_report.get("spawn_success_count", 0) or 0)
        spawn_error_count = int(sensor_rig_report.get("spawn_error_count", 0) or 0)
        first_spawn_error = str(sensor_rig_report.get("first_spawn_error", "") or "")
        if "ego_lost_before_attach" in rig_exc_lower:
            failure_reason = "ego_lost_before_attach"
            rethrow_error = "SENSOR_ATTACH_FAILED:ego_lost_before_attach"
        elif "missing_carla_client" in rig_exc_lower:
            failure_reason = "missing_carla_client"
            sensor_rig_report["failure_stage"] = "client_binding"
            rethrow_error = "missing_carla_client"
        elif "invalid_client_binding" in rig_exc_lower:
            failure_reason = "invalid_client_binding"
            sensor_rig_report["failure_stage"] = "client_binding"
            rethrow_error = first_spawn_error or rig_exc_text
        elif "sensor_attach_failed" in rig_exc_lower:
            failure_reason = "sensor_attach_failed"
            rethrow_error = f"SENSOR_ATTACH_FAILED:{rig_exc_text}"
        elif "streaming_collapse_during_capture" in rig_exc_lower or "pre_spawn_stream_unavailable" in rig_exc_lower:
            failure_reason = "streaming_collapse_during_capture"
            rethrow_error = "STREAMING_COLLAPSE_DURING_CAPTURE:pre_spawn_stream_unavailable"
        elif spawn_error_count > 0:
            failure_reason = "spawn_response_error"
            rethrow_error = f"spawn_response_error:{first_spawn_error or rig_exc_text}"
        elif spawn_response_count > 0 and spawn_success_count == 0:
            failure_reason = "zero_spawned_sensor_actors"
            rethrow_error = "zero_spawned_sensor_actors"
        elif spawn_success_count > 0 and listener_callbacks_registered == 0:
            failure_reason = "listener_registration_failed"
            sensor_rig_report["failure_stage"] = "listener_registration"
            rethrow_error = "listener_registration_failed"
        elif _is_first_frame_timeout_error_text(rig_exc_lower):
            failure_reason = "first_frame_timeout"
            rethrow_error = "FIRST_FRAME_TIMEOUT:streaming_unavailable"
        else:
            failure_reason = "sensor_spawn_failed"
            rethrow_error = "sensor_spawn_failed"
        sensor_rig_report["ok"] = False
        sensor_rig_report["reason"] = str(failure_reason)
        sensor_rig_report["error"] = (
            f"{rig_exc.__class__.__name__}:{rig_exc}"
        )
        sensor_rig_report["attach_retry_count"] = int(attach_retry_count)
        sensor_rig_report["rig_attach_attempted"] = bool(rig_attach_attempted)
        sensor_rig_report["spawned_sensors"] = sorted(
            str(name) for name in sensors.keys()
        )
        sensor_rig_report["listener_callbacks_registered"] = int(
            listener_callbacks_registered
        )
        _write_json(out_dir / "sensor_rig_report.json", sensor_rig_report)
        print(
            f"Spawned sensors: {sensor_rig_report.get('spawned_sensors', [])}",
            flush=True,
        )
        print(
            f"Listener callbacks registered: {int(listener_callbacks_registered)}",
            flush=True,
        )
        _LAST_CAPTURE_CONTEXT["spawned_sensors"] = sorted(
            str(name) for name in sensors.keys()
        )
        raise RuntimeError(str(rethrow_error)) from rig_exc

    rig_validation: Dict[str, Any]
    try:
        rig_validation = DominikSensorSetup.validate_sensor_geometry(
            world, ego, sensors
        )
    except Exception as exc:
        rig_validation = {
            "valid": False,
            "checks": [],
            "errors": [str(exc)],
            "exception": repr(exc),
        }
    _write_json(out_dir / "rig_validation.json", rig_validation)
    if _env_bool("UP_STRICT_RIG_VALIDATION", False) and not rig_validation.get(
        "valid", False
    ):
        raise RuntimeError("Rig validation failed; see rig_validation.json")

    # Switch to synchronous mode only after ego + sensors are fully materialized.
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 1.0 / float(args.fps)
    if hasattr(settings, "substepping"):
        settings.substepping = False
    apply_error: Optional[Exception] = None
    settings_applied = False
    for _ in range(2):
        try:
            world.apply_settings(settings)
            time.sleep(0.2)
            if _world_settings_match(world, fps=int(args.fps)):
                settings_applied = True
                break
        except Exception as exc:
            apply_error = exc
        time.sleep(0.2)
    if not settings_applied:
        if apply_error is not None:
            raise RuntimeError(
                f"streaming_unavailable:world_settings_apply_failed:{apply_error}"
            ) from apply_error
        raise RuntimeError("streaming_unavailable:world_settings_apply_failed")

    initial_tick_timeout_s = max(float(args.tick_timeout_s), float(runtime_timeout_s))
    try:
        _tick_snapshot(world, timeout_s=float(initial_tick_timeout_s))
    except Exception as sync_tick_exc:
        if _is_timeout_error(sync_tick_exc):
            raise RuntimeError(
                "streaming_unavailable:initial_sync_tick_timeout"
            ) from sync_tick_exc
        raise
    assert (
        bool(getattr(world.get_settings(), "synchronous_mode", False)) is True
    ), "sync must be on before listen"

    recorder = SensorRecorder(output_dir=str(out_dir), config=cfg)
    recorder.attach(world, ego, sensors)
    _LAST_CAPTURE_CONTEXT["listen_attach_status"] = recorder.get_listener_attach_status()
    _LAST_CAPTURE_CONTEXT["listen_errors"] = recorder.get_save_errors_tail(100)
    listener_callbacks_registered = len(sensors)
    sensor_rig_report["listener_callbacks_registered"] = int(listener_callbacks_registered)
    sensor_rig_report["spawned_sensors"] = sorted(str(name) for name in sensors.keys())
    if int(listener_callbacks_registered) > 0:
        sensor_rig_report["failure_stage"] = "first_frame_wait"
    if streaming_enabled:
        _record_post_spawn_stream_health(
            host=str(args.host),
            stream_port=int(stream_port),
            sensor_rig_report=sensor_rig_report,
        )
    sensor_rig_report["rig_attach_attempted"] = bool(rig_attach_attempted)
    _write_json(out_dir / "sensor_rig_report.json", sensor_rig_report)
    print(f"Listener callbacks registered: {int(listener_callbacks_registered)}", flush=True)
    for sensor_name in sorted(str(name) for name in sensors.keys()):
        print(f"listener registered: {sensor_name}", flush=True)

    tick_watchdog_payload: Dict[str, Any] = {}
    try:
        tick_watchdog_payload = _tick_watchdog(
            world,
            out_dir,
            n_ticks=int(args.tick_watchdog_ticks),
            tick_timeout_s=float(initial_tick_timeout_s),
        )
        _LAST_CAPTURE_CONTEXT["tick_watchdog_payload"] = dict(tick_watchdog_payload)
    except Exception as watchdog_exc:
        if _is_timeout_error(watchdog_exc):
            raise RuntimeError(
                "streaming_unavailable:tick_watchdog_timeout"
            ) from watchdog_exc
        raise

    applied_world_settings = {
        "synchronous_mode": bool(getattr(settings, "synchronous_mode", False)),
        "fixed_delta_seconds": float(
            getattr(settings, "fixed_delta_seconds", 0.0) or 0.0
        ),
        "substepping": bool(getattr(settings, "substepping", False))
        if hasattr(settings, "substepping")
        else None,
    }
    _LAST_CAPTURE_CONTEXT["sync_settings"] = dict(applied_world_settings)
    settings_applied_before_tick = True
    run_info["synchronous_mode"] = bool(applied_world_settings["synchronous_mode"])
    run_info["fixed_delta_seconds"] = float(
        applied_world_settings["fixed_delta_seconds"]
    )
    run_info["settings_applied_before_tick"] = bool(settings_applied_before_tick)
    _write_json(out_dir / "run_info.json", run_info)

    # Autopilot via TM if possible
    tm = None
    world_sync_mode = False
    try:
        world_settings = world.get_settings()
        world_sync_mode = bool(getattr(world_settings, "synchronous_mode", False))
    except Exception:
        world_sync_mode = False
    try:
        tm_seed_raw = str(os.environ.get("UP_TM_SEED", "42") or "42").strip()
        try:
            tm_seed = int(tm_seed_raw)
        except (TypeError, ValueError):
            tm_seed = 42
        tm = client.get_trafficmanager(8000)
        tm.set_synchronous_mode(bool(world_sync_mode))
        try:
            tm.set_global_distance_to_leading_vehicle(5.0)
        except Exception:
            pass
        try:
            tm.keep_right_rule_percentage(ego, 0.0)
        except Exception:
            pass
        tm.set_random_device_seed(int(tm_seed))
        ego.set_autopilot(True, tm.get_port())
    except Exception:
        try:
            ego.set_autopilot(True)
        except Exception:
            pass

    if npc_actors:
        npc_autopilot_errors = []
        npc_autopilot_enabled = 0
        tm_port = tm.get_port() if tm is not None else 8000
        for actor in npc_actors:
            try:
                actor.set_autopilot(True, tm_port)
                npc_autopilot_enabled += 1
            except Exception as exc:
                npc_autopilot_errors.append(
                    {
                        "actor_id": int(getattr(actor, "id", -1) or -1),
                        "error": repr(exc),
                    }
                )
        npc_spawn_report["autopilot_enabled"] = int(npc_autopilot_enabled)
        if npc_autopilot_errors:
            npc_spawn_report["autopilot_errors"] = npc_autopilot_errors
        _write_json(out_dir / "npc_spawn_report.json", npc_spawn_report)

    # Capture loop
    t0 = time.time()
    frames = -1
    tick_count = 0
    first_measurement_ok = False
    first_measurement_tick = -1
    first_measurement_elapsed_s = None
    first_sensor_frame_ids: Dict[str, int] = {}
    first_sensor_frame_ids_by_modality: Dict[str, int] = {}
    capture_deadline = t0 + float(args.duration)
    no_frames_deadline = t0 + max(1.0, float(args.no_frames_watchdog_timeout_s))
    no_frames_watchdog_ticks = max(1, int(args.no_frames_watchdog_ticks))
    startup_measurement_deadline = t0 + max(1.0, float(args.first_measurement_timeout_s))
    first_measurement_grace_s = max(
        1.0, min(5.0, float(max(1, int(args.fps))) * 0.5)
    )
    consecutive_tick_timeouts = 0
    settings_restored = False
    rgb_sensor_names = sorted(
        [name for name in sensors.keys() if str(name).lower().startswith("rgb_")]
    )
    semseg_sensor_names = sorted(
        [
            name
            for name in sensors.keys()
            if str(name).lower().startswith("seg_")
            or str(name).lower().startswith("semseg_")
        ]
    )
    require_semseg_callback = bool(seg_enabled and len(semseg_sensor_names) > 0)
    try:
        # Phase A: bounded readiness gate. Require camera callback and semseg callback when enabled.
        while (not first_measurement_ok) and (time.time() < startup_measurement_deadline):
            try:
                tick_info = _tick_snapshot(world, timeout_s=float(args.tick_timeout_s))  # one tick
                print(
                    f"world.tick i={int(tick_count + 1)} frame={int(tick_info.get('frame_id', -1))}",
                    flush=True,
                )
                consecutive_tick_timeouts = 0
            except Exception as tick_exc:
                if _is_timeout_error(tick_exc):
                    consecutive_tick_timeouts += 1
                    if consecutive_tick_timeouts >= max(
                        1, int(args.max_consecutive_tick_timeouts)
                    ):
                        raise RuntimeError(
                            "streaming_unavailable:repeated_tick_timeout"
                        ) from tick_exc
                    continue
                raise
            tick_state = recorder.tick()
            tick_count += 1
            frame_id_from_tick = int(tick_info.get("frame_id", frames + 1))
            frames = int(frame_id_from_tick)
            saved_images = int(tick_state.get("saved_images", 0) or 0)
            saved_lidars = int(tick_state.get("saved_lidars", 0) or 0)
            _LAST_CAPTURE_CONTEXT["saved_images"] = int(saved_images)
            _LAST_CAPTURE_CONTEXT["saved_lidars"] = int(saved_lidars)
            _LAST_CAPTURE_CONTEXT["ticks_observed"] = int(tick_count)
            _LAST_CAPTURE_CONTEXT["last_tick_frame_id"] = int(frames)
            counts = tick_state.get("sensor_frame_counts", {})
            if not isinstance(counts, dict):
                counts = {}
            _LAST_CAPTURE_CONTEXT["sensor_frame_counts"] = {
                str(name): int(value or 0) for name, value in counts.items()
            }
            _LAST_CAPTURE_CONTEXT["listen_errors"] = recorder.get_save_errors_tail(100)
            if (
                saved_images <= 0
                and saved_lidars <= 0
                and (
                    int(tick_count) >= int(no_frames_watchdog_ticks)
                    or time.time() >= float(no_frames_deadline)
                )
            ):
                raise RuntimeError("no_frames_received")
            for sensor_name, sensor_count in counts.items():
                try:
                    count_i = int(sensor_count or 0)
                except Exception:
                    count_i = 0
                if count_i <= 0:
                    continue
                if sensor_name not in first_sensor_frame_ids:
                    frame_id = int(tick_info.get("frame_id", -1))
                    first_sensor_frame_ids[sensor_name] = frame_id
                    modality = "other"
                    lower_name = str(sensor_name).lower()
                    if "lidar" in lower_name:
                        modality = "lidar"
                    elif lower_name.startswith("seg_") or lower_name.startswith("semseg_"):
                        modality = "semseg"
                    elif lower_name.startswith("rgb_") or "camera" in lower_name:
                        modality = "rgb"
                    if modality not in first_sensor_frame_ids_by_modality:
                        first_sensor_frame_ids_by_modality[modality] = frame_id
                    print(
                        f"first sensor frame: sensor={sensor_name} modality={modality} tick_frame={frame_id}",
                        flush=True,
                    )
            if _first_measurement_callbacks_ready(
                tick_state,
                rgb_sensor_names=rgb_sensor_names,
                require_semseg=require_semseg_callback,
                semseg_sensor_names=semseg_sensor_names,
            ):
                first_measurement_ok = True
                first_measurement_tick = int(tick_count)
                first_measurement_elapsed_s = max(0.0, time.time() - t0)
                break
        if not first_measurement_ok:
            raise RuntimeError("first_measurement_no_callbacks")

        # Phase B: continue recording until duration target is reached.
        while time.time() < capture_deadline:
            try:
                tick_info = _tick_snapshot(world, timeout_s=float(args.tick_timeout_s))
                print(
                    f"world.tick i={int(tick_count + 1)} frame={int(tick_info.get('frame_id', -1))}",
                    flush=True,
                )
                consecutive_tick_timeouts = 0
            except Exception as tick_exc:
                if _is_timeout_error(tick_exc):
                    consecutive_tick_timeouts += 1
                    if consecutive_tick_timeouts >= max(
                        1, int(args.max_consecutive_tick_timeouts)
                    ):
                        raise RuntimeError(
                            "streaming_unavailable:repeated_tick_timeout"
                        ) from tick_exc
                    continue
                raise
            tick_state = recorder.tick()
            tick_count += 1
            frame_id_from_tick = int(tick_info.get("frame_id", frames + 1))
            frames = int(frame_id_from_tick)
            saved_images = int(tick_state.get("saved_images", 0) or 0)
            saved_lidars = int(tick_state.get("saved_lidars", 0) or 0)
            _LAST_CAPTURE_CONTEXT["saved_images"] = int(saved_images)
            _LAST_CAPTURE_CONTEXT["saved_lidars"] = int(saved_lidars)
            _LAST_CAPTURE_CONTEXT["ticks_observed"] = int(tick_count)
            _LAST_CAPTURE_CONTEXT["last_tick_frame_id"] = int(frames)
            counts = tick_state.get("sensor_frame_counts", {})
            if not isinstance(counts, dict):
                counts = {}
            _LAST_CAPTURE_CONTEXT["sensor_frame_counts"] = {
                str(name): int(value or 0) for name, value in counts.items()
            }
            _LAST_CAPTURE_CONTEXT["listen_errors"] = recorder.get_save_errors_tail(100)
            if (
                saved_images <= 0
                and saved_lidars <= 0
                and (
                    int(tick_count) >= int(no_frames_watchdog_ticks)
                    or time.time() >= float(no_frames_deadline)
                )
            ):
                raise RuntimeError("no_frames_received")
            for sensor_name, sensor_count in counts.items():
                try:
                    count_i = int(sensor_count or 0)
                except Exception:
                    count_i = 0
                if count_i <= 0 or sensor_name in first_sensor_frame_ids:
                    continue
                frame_id = int(tick_info.get("frame_id", -1))
                first_sensor_frame_ids[sensor_name] = frame_id
                lower_name = str(sensor_name).lower()
                modality = (
                    "lidar"
                    if "lidar" in lower_name
                    else (
                        "semseg"
                        if lower_name.startswith("seg_")
                        or lower_name.startswith("semseg_")
                        else ("rgb" if lower_name.startswith("rgb_") or "camera" in lower_name else "other")
                    )
                )
                if modality not in first_sensor_frame_ids_by_modality:
                    first_sensor_frame_ids_by_modality[modality] = frame_id
    finally:
        # Stop–Drain–Destroy ordering (Windows-safe)
        # 1) Halt CARLA-side callback triggers IMMEDIATELY
        for s in list(sensors.values()):
            try:
                if hasattr(s, "stop"):
                    s.stop()
            except Exception:
                pass

        # 2) recorder.stop(): flush barrier for pending disk writes
        try:
            recorder.stop()  # Flush barrier: waits for pending writes
        except Exception:
            pass

        # 3) Quiescent drain ticks: allow server to process stop and clear buffers
        try:
            for _ in range(5):
                world.tick(float(args.tick_timeout_s))
        except Exception:
            pass

        # Let disk buffers settle before teardown
        time.sleep(0.5)

        try:
            recorder.close()
        except Exception:
            pass

        # Teardown best-effort (destroy only after drain)
        try:
            ego.set_autopilot(False)
        except Exception:
            pass
        if not _env_bool("UP_SKIP_DESTROY", False):
            sensor_destroy_flush = getattr(recorder, "prepare_for_destroy", None)
            _prepare_world_for_destroy(world, timeout_s=float(args.tick_timeout_s))
            # Final drain ticks before destruction
            try:
                for _ in range(5):
                    world.tick(float(args.tick_timeout_s))
            except Exception:
                pass
            for s in list(sensors.values()):
                _safe_destroy(s, pre_destroy=sensor_destroy_flush)
            for a in sanity_actors:
                _safe_destroy(a)
            for a in npc_actors:
                _safe_destroy(a)
            _safe_destroy(ego)
            # Confirm cleanup
            try:
                world.tick(float(args.tick_timeout_s))
            except Exception:
                pass
        try:
            world.apply_settings(original_settings)
            settings_restored = True
        except Exception:
            settings_restored = False

    actual_callback_count = int(recorder.get_recorded_frame_count())
    if int(tick_count) != int(actual_callback_count):
        print(
            f"[WARNING] tick_count={int(tick_count)} != frames_recorded={int(actual_callback_count)}",
            flush=True,
        )
    if int(args.frames) != int(actual_callback_count):
        print(
            f"[WARNING] frames_requested={int(args.frames)} != frames_recorded={int(actual_callback_count)}",
            flush=True,
        )
    capture_summary_payload = {
        "frames_requested": int(args.frames),
        "frames_recorded": int(actual_callback_count),
        "frames_ticks": int(tick_count),
        "tick_count": int(tick_count),
        "last_tick_frame_id": int(frames),
        "duration_s": float(args.duration),
        "first_measurement_ok": bool(first_measurement_ok),
        "first_measurement_tick": int(first_measurement_tick),
        "first_measurement_elapsed_s": first_measurement_elapsed_s,
        "first_measurement_grace_s": float(first_measurement_grace_s),
        "no_frames_watchdog_ticks": int(no_frames_watchdog_ticks),
        "no_frames_watchdog_timeout_s": float(args.no_frames_watchdog_timeout_s),
        "world_settings_applied": applied_world_settings,
        "settings_applied_before_tick": bool(settings_applied_before_tick),
        "world_settings_restored": bool(settings_restored),
        "tick_watchdog_path": str(out_dir / "tick_watchdog.json"),
        "first_sensor_frame_ids": first_sensor_frame_ids,
        "first_sensor_frame_ids_by_modality": first_sensor_frame_ids_by_modality,
        "saved_images": int(_LAST_CAPTURE_CONTEXT.get("saved_images", 0) or 0),
        "saved_lidars": int(_LAST_CAPTURE_CONTEXT.get("saved_lidars", 0) or 0),
    }
    if int(args.num_npcs) > 0 and int(npc_spawn_report.get("spawned", 0) or 0) == 0:
        capture_summary_payload["npc_spawn_warning"] = (
            "NPC vehicles requested but none spawned; "
            "XODR standalone maps may have limited spawn points"
        )
    _write_json(out_dir / "capture_summary.json", capture_summary_payload)
    _LAST_CAPTURE_CONTEXT["ticks_observed"] = int(tick_count)
    _LAST_CAPTURE_CONTEXT["last_tick_frame_id"] = int(frames)
    _LAST_CAPTURE_CONTEXT["status"] = "OK"
    _LAST_CAPTURE_CONTEXT["failure_reason"] = ""
    _LAST_CAPTURE_CONTEXT["failure_detail"] = ""
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    try:
        exit_code = int(_main_impl(argv))
        context = dict(_LAST_CAPTURE_CONTEXT)
        out_dir_text = str(context.get("out_dir", "") or "").strip()
        if out_dir_text:
            out_dir = Path(out_dir_text)
            out_dir.mkdir(parents=True, exist_ok=True)
            _write_capture_status_artifact(
                out_dir=out_dir,
                status="OK",
                failure_reason="",
                failure_detail="",
                context=context,
            )
        return int(exit_code)
    except Exception as exc:
        context = dict(_LAST_CAPTURE_CONTEXT)
        out_dir_text = str(context.get("out_dir", "") or "").strip()
        if not out_dir_text:
            try:
                parsed = parse_args(argv)
                parsed_out = Path(parsed.out_dir).expanduser()
                if not parsed_out.is_absolute():
                    parsed_out = Path.cwd() / parsed_out
                out_dir_text = str(parsed_out)
                context["town"] = str(parsed.town or "")
                context["use_current_world"] = bool(parsed.use_current_world)
            except Exception:
                out_dir_text = str(Path.cwd() / "recording")
        out_dir = Path(out_dir_text)
        out_dir.mkdir(parents=True, exist_ok=True)

        failure_detail = f"{exc.__class__.__name__}:{exc}"
        failure_reason = _classify_capture_failure_reason(
            failure_detail,
            requested_town=str(context.get("town", "") or ""),
            use_current_world=bool(context.get("use_current_world", False)),
            listen_attach_status=(
                context.get("listen_attach_status")
                if isinstance(context.get("listen_attach_status"), dict)
                else None
            ),
        )
        status = (
            "SKIP"
            if failure_reason in {"MAP_TRAVEL_RISK", "MAP_TRAVEL_RISK_GRID0821"}
            else "FAIL"
        )
        operator_instruction = ""
        if failure_reason == "MAP_TRAVEL_RISK_GRID0821":
            operator_instruction = (
                "Load Grid0821 manually in CARLA and rerun with --use-current-world."
            )

        _write_capture_status_artifact(
            out_dir=out_dir,
            status=status,
            failure_reason=failure_reason,
            failure_detail=failure_detail,
            context=context,
            operator_instruction=operator_instruction,
        )
        print(f"[record_route_fixed] {failure_reason}: {exc}", flush=True)
        return 0 if status == "SKIP" else 2


if __name__ == "__main__":
    raise SystemExit(main())
