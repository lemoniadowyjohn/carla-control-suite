#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PowerShell-friendly smoke check for Windows thesis experiments.

Runs offline checks always, and CARLA checks if the CARLA Python API is importable.
Writes JSON artifacts under --out.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_stage_file(
    out_dir: Path,
    idx: int,
    stage: str,
    *,
    ok: bool,
    started_at_s: float,
    elapsed_s: float,
    error: Optional[str] = None,
    tb: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write stage JSON file following carla_debug_ladder schema."""
    stages_dir = out_dir / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "stage": str(stage),
        "ok": bool(ok),
        "started_at_s": float(started_at_s),
        "elapsed_s": float(elapsed_s),
        "error": error,
        "traceback": tb,
        "details": details or {},
    }
    path = stages_dir / f"{idx:02d}_{stage}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _write_debug_log(
    out_dir: Path,
    *,
    args: argparse.Namespace,
    carla_result: Dict[str, Any],
    exc_traceback: Optional[str] = None,
) -> Path:
    """Write a human-readable smoke_check.log for debugging CARLA failures."""
    log_path = out_dir / "smoke_check.log"
    # Map status to human-readable stage
    status_to_stage = {
        "carla_api_not_importable": "import",
        "rpc_not_responsive": "connect",
        "load_world_failed": "load_world",
        "tick_failed": "tick",
        "vehicle_blueprint_missing": "spawn_prep",
        "no_spawn_points": "spawn_prep",
        "vehicle_spawn_failed": "spawn_vehicle",
        "camera_spawn_failed": "spawn_camera",
        "spawn_check_exception": "spawn",
        "ok": "complete",
        "exception": "unknown",
        "unknown": "unknown",
    }
    status = carla_result.get("status", "unknown")
    stage_reached = status_to_stage.get(status, status)

    lines = [
        f"smoke_check_all debug log",
        f"timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "=== Parameters ===",
        f"host: {args.host}",
        f"port: {args.port}",
        f"manual_town: {args.manual_town}",
        f"spawn_index: {args.spawn_index}",
        f"vehicle: {args.vehicle}",
        f"xodr: {args.xodr}",
        "",
        "=== CARLA Check Result ===",
        f"stage_reached: {stage_reached}",
        f"available: {carla_result.get('available')}",
        f"status: {carla_result.get('status')}",
        f"error: {carla_result.get('error')}",
        f"server_version: {carla_result.get('server_version')}",
        "",
    ]

    # Add all other keys from carla_result for completeness
    for k, v in carla_result.items():
        if k not in ("available", "status", "error", "server_version"):
            lines.append(f"{k}: {v}")

    lines.extend([
        "",
        "=== Recommendations ===",
        "1. Ensure CARLA server is running (CarlaUE4.exe)",
        "2. Check that the RPC port (default 2000) is reachable",
        "3. Try setting UP_DISABLE_STREAMING=1 if streaming port issues occur",
        "4. For Windows, ensure no firewall is blocking localhost connections",
        "",
    ])

    if exc_traceback:
        lines.extend([
            "=== Exception Traceback ===",
            exc_traceback,
            "",
        ])

    out_dir.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines), encoding="utf-8")
    return log_path


def _try_import(name: str) -> Tuple[bool, Optional[str]]:
    try:
        importlib.import_module(name)
    except Exception as exc:
        return False, str(exc)
    return True, None


def _parse_xodr_basic(path: Path) -> Tuple[bool, Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return False, f"read_failed: {exc}"
    if "<OpenDRIVE" not in text and "<OpenDrive" not in text and "OpenDRIVE" not in text:
        return False, "missing_OpenDRIVE_tag"
    try:
        ET.fromstring(text)
    except Exception as exc:
        return False, f"xml_parse_failed: {exc}"
    return True, None


def _try_import_carla():
    try:
        import carla  # type: ignore
    except Exception as exc:
        return None, str(exc)
    return carla, None


def _yolo_integration_check() -> Dict[str, Any]:
    """
    Lightweight check: confirm Ultralytics can be imported and YOLO can be constructed on CPU.
    This is optional and must not block experiments.
    """
    result: Dict[str, Any] = {"integrated": True, "status": "unknown", "error": None}
    if importlib.util.find_spec("ultralytics") is None:
        result["status"] = "ultralytics_not_installed"
        return result

    # Prefer CPU-only behavior for a smoke check.
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")

    try:
        from ultralytics import YOLO  # type: ignore

        model_path = Path("ultimate_pipeline/perception/yolov8n.pt")
        if not model_path.is_file():
            result["status"] = "model_missing"
            result["model_path"] = str(model_path)
            return result
        _ = YOLO(str(model_path))
        result["status"] = "ok"
        result["model_path"] = str(model_path)
        return result
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        return result


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True, help="Path to an XODR file to sanity-check")
    ap.add_argument("--manual-town", required=True, choices=["Grid0821", "Grid0828"], help="Manual CARLA town")
    ap.add_argument("--out", required=True, help="Output directory for smoke-check artifacts")
    ap.add_argument("--host", default="127.0.0.1", help="CARLA host")
    ap.add_argument("--port", type=int, default=2000, help="CARLA RPC port")
    ap.add_argument("--spawn-index", type=int, default=0, help="Spawn point index to try (default: 0)")
    ap.add_argument("--vehicle", default="vehicle.audi.a2", help="Vehicle blueprint id")
    ap.add_argument("--skip-carla", action="store_true", help="Skip CARLA checks even if API is available")
    return ap.parse_args(argv)


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


def _tick(world, *, n: int, timeout_s: float) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """
    Tick the world n times with bounded timeout.
    Handles both sync and async world modes (mirroring record_route robustness).

    Returns: (success, error_msg, details_dict)
    """
    n = max(0, int(n))
    details: Dict[str, Any] = {"n": n, "frames": [], "sync_mode": None}
    if n == 0:
        return True, None, details

    # Detect sync mode (mirroring record_route)
    try:
        settings = world.get_settings()
        sync = bool(getattr(settings, "synchronous_mode", False))
        details["sync_mode"] = sync
    except Exception:
        sync = False
        details["sync_mode"] = None

    # CARLA 0.9.16: must use positional float, not keyword arg.
    for i in range(n):
        try:
            if sync:
                snap = world.tick()
            else:
                snap = world.wait_for_tick(float(timeout_s))
            frame = int(getattr(snap, "frame", -1)) if snap else -1
            details["frames"].append(frame)
        except Exception as exc:
            details["failed_at_tick"] = i
            return False, str(exc), details
    return True, None, details


def _spawn_candidate_indices(
    requested: int,
    n: int,
    *,
    max_scan: int = 20,
    extra_fallbacks: Optional[list[int]] = None,
) -> list[int]:
    """
    Build spawn candidate indices with stable fallback strategy (mirrors record_route).

    Rules:
      - Always try requested index first (if in range)
      - Then try stable fallback indices (50, 100, 500, 0, 1, 2, 5, 10)
      - Then scan up to max_scan indices
      - No duplicates, all indices bounded to [0, n)
    """
    n = int(n)
    if n <= 0:
        return []
    requested = int(requested)
    # Default stable fallbacks mirror record_route for Grid0828 compatibility
    if extra_fallbacks is None:
        extra_fallbacks = [50, 100, 500, 0, 1, 2, 5, 10]
    scan_max = min(max(0, int(max_scan)), n - 1)

    def _push(out: list[int], seen: set, i: int) -> None:
        if 0 <= int(i) < n and int(i) not in seen:
            seen.add(int(i))
            out.append(int(i))

    seen: set = set()
    out: list[int] = []

    # 1. Requested index first (if valid)
    if 0 <= requested < n:
        _push(out, seen, requested)
    else:
        _push(out, seen, 0)

    # 2. Stable fallback indices (from record_route)
    for i in extra_fallbacks:
        _push(out, seen, int(i))

    # 3. Bounded scan range (0..scan_max)
    for i in range(0, scan_max + 1):
        _push(out, seen, i)

    return out


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


def _carla_checks(
    *,
    host: str,
    port: int,
    manual_town: str,
    spawn_index: int,
    vehicle_blueprint: str,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    global t0
    carla, err = _try_import_carla()
    if carla is None:
        return {"available": False, "status": "carla_api_not_importable", "error": err, "stage_reached": "import", "failing_stage": "import"}

    stages: list[Dict[str, Any]] = []
    stage_idx = [0]  # mutable counter for stage file numbering
    last_stage = ["init"]  # track last successful stage

    def _write_stage(name: str, ok: bool, elapsed_s: float, error: Optional[str] = None, tb: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        """Write stage file if out_dir is provided."""
        if out_dir is not None:
            _write_stage_file(
                out_dir, stage_idx[0], name,
                ok=ok, started_at_s=time.time(), elapsed_s=elapsed_s,
                error=error, tb=tb, details=details,
            )
        stage_idx[0] += 1
        if ok:
            last_stage[0] = name

    def _stage(name: str):
        def _decorator(fn):
            def _wrapped(*args, **kwargs):
                t0 = time.monotonic()
                try:
                    out = fn(*args, **kwargs)
                    elapsed = round(time.monotonic() - t0, 3)
                    stages.append({"stage": name, "ok": True, "elapsed_s": elapsed})
                    _write_stage(name, True, elapsed)
                    return out
                except Exception as exc:
                    elapsed = round(time.monotonic() - t0, 3)
                    tb_str = traceback.format_exc()
                    stages.append({"stage": name, "ok": False, "elapsed_s": elapsed, "error": str(exc), "traceback": tb_str})
                    _write_stage(name, False, elapsed, error=str(exc), tb=tb_str)
                    raise

            return _wrapped

        return _decorator

    # Configurable client timeout (Windows: load_world can be slow on first load)
    client_timeout_s = _env_float("UP_SMOKE_CLIENT_TIMEOUT_S", 60.0)
    client = carla.Client(host, int(port))
    client.set_timeout(float(client_timeout_s))
    status: Dict[str, Any] = {
        "available": True,
        "status": "unknown",
        "error": None,
        "stages": stages,
        "config": {
            "client_timeout_s": client_timeout_s,
            "z_offset_m": _env_float("UP_SPAWN_Z_OFFSET_M", 1.0),
        },
    }
    try:
        @_stage("connect")
        def _connect():
            status["server_version"] = client.get_server_version()

        _connect()
    except Exception as exc:
        status["status"] = "rpc_not_responsive"
        status["error"] = str(exc)
        status["stage_reached"] = "init"
        status["failing_stage"] = "connect"
        return status

    try:
        maps = list(client.get_available_maps())
        status["manual_town_in_available_maps"] = any(manual_town.lower() in str(m).lower() for m in maps)
    except Exception as exc:
        status["manual_town_in_available_maps"] = None
        status["available_maps_error"] = str(exc)

    # load_world with bounded retry (mirroring record_route robustness)
    load_world_retries = _env_int("UP_SMOKE_LOAD_WORLD_RETRIES", 2)
    load_world_retries = max(1, min(5, load_world_retries))
    status["load_world_attempts"] = []
    world = None
    for attempt in range(load_world_retries):
        try:
            t0 = time.monotonic()
            world = _reload_ready_for_sensors(client, map_name=manual_town, tm_port=8000)
            elapsed = round(time.monotonic() - t0, 3)
            status["load_world_attempts"].append({"attempt": attempt + 1, "ok": True, "elapsed_s": elapsed})
            stages.append({"stage": "load_world", "ok": True, "elapsed_s": elapsed, "attempt": attempt + 1})
            _write_stage("load_world", True, elapsed, details={"town": manual_town, "attempt": attempt + 1})
            break
        except Exception as exc:
            elapsed = round(time.monotonic() - t0, 3)
            tb_str = traceback.format_exc()
            status["load_world_attempts"].append({"attempt": attempt + 1, "ok": False, "error": str(exc), "elapsed_s": elapsed})
            if attempt == load_world_retries - 1:
                stages.append({"stage": "load_world", "ok": False, "elapsed_s": elapsed, "error": str(exc), "attempts": load_world_retries})
                _write_stage("load_world", False, elapsed, error=str(exc), tb=tb_str, details={"town": manual_town, "attempts": load_world_retries})
                status["status"] = "load_world_failed"
                status["error"] = str(exc)
                status["stage_reached"] = "connect"
                status["failing_stage"] = "load_world"
                return status
            # Brief pause before retry
            time.sleep(1.0)

    if world is None:
        status["status"] = "load_world_failed"
        status["error"] = "world_is_none_after_load"
        status["stage_reached"] = "connect"
        status["failing_stage"] = "load_world"
        return status

    # Stabilize ticks after load (bounded, configurable timeout) - mirroring record_route
    try:
        from ultimate_pipeline.config.settings import SETTINGS
        tick_timeout_s = float(getattr(SETTINGS, "CARLA_READY_TICK_TIMEOUT", 2.0))
    except Exception:
        tick_timeout_s = 2.0
    tick_timeout_s = _env_float("UP_SMOKE_TICK_TIMEOUT_S", tick_timeout_s)
    stabilize_ticks = _env_int("UP_SMOKE_STABILIZE_TICKS", 10)
    stabilize_ticks = max(1, min(30, stabilize_ticks))

    t0 = time.monotonic()
    ok, tick_err, tick_details = _tick(world, n=stabilize_ticks, timeout_s=tick_timeout_s)
    tick_elapsed = round(time.monotonic() - t0, 3)
    if not ok:
        status["status"] = "tick_failed"
        status["error"] = tick_err
        status["stage_reached"] = "load_world"
        status["failing_stage"] = "post_load_tick"
        stages.append({
            "stage": "post_load_tick",
            "ok": False,
            "elapsed_s": tick_elapsed,
            "error": tick_err,
            "n": stabilize_ticks,
            "details": tick_details,
        })
        _write_stage("post_load_tick", False, tick_elapsed, error=tick_err, details={"n": stabilize_ticks, "tick_details": tick_details})
        return status
    stages.append({
        "stage": "post_load_tick",
        "ok": True,
        "elapsed_s": tick_elapsed,
        "n": stabilize_ticks,
        "timeout_s": tick_timeout_s,
        "details": tick_details,
    })
    _write_stage("post_load_tick", True, tick_elapsed, details={"n": stabilize_ticks, "timeout_s": tick_timeout_s})

    # TrafficManager is optional; warn-only.
    try:
        @_stage("traffic_manager")
        def _tm():
            tm_port = int(os.environ.get("UP_TM_PORT", "8000"))
            tm = client.get_trafficmanager(tm_port)
            try:
                tm.set_synchronous_mode(True)
            except Exception:
                pass
            return {"ok": True, "tm_port": tm_port}

        status["traffic_manager"] = _tm()
    except Exception as exc:
        status["traffic_manager"] = {"ok": False, "error": str(exc)}

    # Pre-spawn tick stabilization (mirroring record_route robustness)
    pre_spawn_ticks = _env_int("UP_SMOKE_PRE_SPAWN_TICKS", 3)
    pre_spawn_ticks = max(0, min(10, pre_spawn_ticks))
    if pre_spawn_ticks > 0:
        ok_pre, _, pre_details = _tick(world, n=pre_spawn_ticks, timeout_s=tick_timeout_s)
        stages.append({
            "stage": "pre_spawn_tick",
            "ok": ok_pre,
            "n": pre_spawn_ticks,
            "details": pre_details,
        })

    # Minimal spawn check: ego + 1 tiny RGB camera
    try:
        status["spawn_attempts"] = []
        bp_lib = world.get_blueprint_library()
        vehicle_bps = bp_lib.filter(vehicle_blueprint)
        if not vehicle_bps:
            status["status"] = "vehicle_blueprint_missing"
            status["error"] = vehicle_blueprint
            status["stage_reached"] = "post_load_tick"
            status["failing_stage"] = "spawn_prep"
            _write_stage("spawn_prep", False, 0.0, error=f"vehicle_blueprint_missing: {vehicle_blueprint}", details={"blueprint": vehicle_blueprint})
            return status
        vehicle_bp = vehicle_bps[0]
        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            status["status"] = "no_spawn_points"
            status["stage_reached"] = "post_load_tick"
            status["failing_stage"] = "spawn_prep"
            _write_stage("spawn_prep", False, 0.0, error="no_spawn_points")
            return status

        # Bounded spawn fallback across multiple indices (mirroring record_route)
        max_spawn_scan = _env_int("UP_SMOKE_MAX_SPAWN_SCAN", 20)
        candidates = _spawn_candidate_indices(int(spawn_index), len(spawn_points), max_scan=max_spawn_scan)
        status["spawn_candidates"] = list(candidates)
        status["spawn_point_count"] = len(spawn_points)
        z_offset_m = _env_float("UP_SPAWN_Z_OFFSET_M", 1.0)
        # Early tick count after spawn to validate world stability (mirrors record_route)
        early_tick_n = _env_int("UP_SMOKE_EARLY_TICKS", 2)
        early_tick_n = max(0, min(10, early_tick_n))
        status["config"]["early_tick_n"] = early_tick_n
        try:
            @_stage("spawn_vehicle")
            def _spawn_vehicle():
                ego = None
                chosen_idx = None
                for idx in candidates:
                    base_tf = spawn_points[int(idx)]
                    for dz in (0.0, z_offset_m):
                        tf = _apply_spawn_z_offset(carla, base_tf, dz)
                        try:
                            actor = world.try_spawn_actor(vehicle_bp, tf)
                        except Exception as exc:
                            status["spawn_attempts"].append(
                                {"index": int(idx), "ok": False, "error": str(exc), "dz": float(dz), "early_tick_ok": None}
                            )
                            continue
                        if actor is None:
                            status["spawn_attempts"].append(
                                {"index": int(idx), "ok": False, "error": "try_spawn_actor_returned_none", "dz": float(dz), "early_tick_ok": None}
                            )
                            continue

                        # Early tick check after spawn (mirrors record_route robustness)
                        if early_tick_n > 0:
                            tick_ok, tick_err, tick_det = _tick(world, n=early_tick_n, timeout_s=tick_timeout_s)
                            if not tick_ok:
                                status["spawn_attempts"].append(
                                    {"index": int(idx), "ok": False, "error": f"early_tick_failed: {tick_err}", "dz": float(dz), "early_tick_ok": False}
                                )
                                # Cleanup failed spawn before retry (mirrors record_route)
                                try:
                                    actor.destroy()
                                except Exception:
                                    pass
                                # Brief stabilization tick after cleanup
                                _tick(world, n=1, timeout_s=tick_timeout_s)
                                continue

                        ego = actor
                        chosen_idx = int(idx)
                        status["spawn_attempts"].append({"index": int(idx), "ok": True, "error": None, "dz": float(dz), "early_tick_ok": True if early_tick_n > 0 else None})
                        break
                    if ego is not None:
                        break

                if ego is None or chosen_idx is None:
                    raise RuntimeError("vehicle_spawn_failed")
                return ego, chosen_idx

            ego, chosen_idx = _spawn_vehicle()
        except Exception as exc:
            status["status"] = "vehicle_spawn_failed"
            status["error"] = str(exc)
            status["stage_reached"] = "post_load_tick"
            status["failing_stage"] = "spawn_vehicle"
            return status

        status["spawn_index_selected"] = int(chosen_idx)

        try:
            @_stage("attach_rgb_camera")
            def _attach_rgb():
                cam_bp_id = "sensor.camera.rgb"
                cam_bp = bp_lib.find(cam_bp_id)
                if cam_bp is None:
                    raise RuntimeError(f"blueprint_not_found: {cam_bp_id}")
                cam_attrs = {}
                for attr in ("image_size_x", "image_size_y", "fov"):
                    if cam_bp.has_attribute(attr):
                        cam_attrs[attr] = {"has": True}
                if cam_bp.has_attribute("image_size_x"):
                    cam_bp.set_attribute("image_size_x", "320")
                    cam_attrs["image_size_x"]["value"] = "320"
                if cam_bp.has_attribute("image_size_y"):
                    cam_bp.set_attribute("image_size_y", "240")
                    cam_attrs["image_size_y"]["value"] = "240"
                if cam_bp.has_attribute("fov"):
                    cam_bp.set_attribute("fov", "90")
                    cam_attrs["fov"]["value"] = "90"
                cam_tf = carla.Transform(carla.Location(x=1.5, y=0.0, z=1.7))
                cam = world.try_spawn_actor(cam_bp, cam_tf, attach_to=ego)
                if cam is None:
                    raise RuntimeError(f"try_spawn_actor_returned_none: blueprint={cam_bp_id}, attrs={cam_attrs}")
                status["rgb_camera_attrs"] = cam_attrs
                return cam

            cam = _attach_rgb()
        except Exception as exc:
            status["status"] = "camera_spawn_failed"
            status["error"] = str(exc)
            status["stage_reached"] = "spawn_vehicle"
            status["failing_stage"] = "attach_rgb_camera"
            try:
                ego.destroy()
            except Exception:
                pass
            return status

        status["spawned_vehicle_id"] = getattr(ego, "id", None)
        status["spawned_camera_id"] = getattr(cam, "id", None)
        status["z_offset_m_used"] = z_offset_m

        # Post-spawn tick to validate world stability
        post_spawn_ticks = _env_int("UP_SMOKE_POST_SPAWN_TICKS", 2)
        t0 = time.monotonic()
        ok2, tick_err2, post_details = _tick(world, n=post_spawn_ticks, timeout_s=tick_timeout_s)
        tick_elapsed2 = round(time.monotonic() - t0, 3)
        status["post_spawn_tick_ok"] = bool(ok2)
        status["post_spawn_tick_details"] = post_details
        stages.append({
            "stage": "tick_after_spawn",
            "ok": ok2,
            "elapsed_s": tick_elapsed2,
            "n": post_spawn_ticks,
            "details": post_details,
        })
        _write_stage("tick_after_spawn", ok2, tick_elapsed2, error=tick_err2 if not ok2 else None, details={"n": post_spawn_ticks})

        # Final status
        status["status"] = "ok"
        status["stage_reached"] = "tick_after_spawn"
        status["failing_stage"] = None

        # Soft teardown (best-effort, never raises)
        try:
            cam.destroy()
        except Exception:
            pass
        try:
            ego.destroy()
        except Exception:
            pass
        return status
    except Exception as exc:
        tb_str = traceback.format_exc()
        status["status"] = "spawn_check_exception"
        status["error"] = str(exc)
        status["traceback"] = tb_str
        status["stage_reached"] = last_stage[0]
        status["failing_stage"] = "spawn_check"
        _write_stage("spawn_check_exception", False, 0.0, error=str(exc), tb=tb_str)
        return status


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    report: Dict[str, Any] = {"timestamp": time.strftime("%Y%m%d_%H%M%S"), "success": False, "checks": {}}
    status_path = out_dir / "smoke_status.json"
    report_path = out_dir / "smoke_check_report.json"

    try:
        # Offline checks
        imports = {}
        for mod in (
            "ultimate_pipeline.perception.record_route",
            "ultimate_pipeline.sensors.dominik_sensor_setup",
            "ultimate_pipeline.tools.run_perception_pair",
        ):
            ok, err = _try_import(mod)
            imports[mod] = {"ok": ok, "error": err}
        report["checks"]["imports"] = imports

        xodr_path = Path(args.xodr)
        report["checks"]["xodr_exists"] = xodr_path.is_file()
        xodr_ok, xodr_err = _parse_xodr_basic(xodr_path) if xodr_path.is_file() else (False, "missing_file")
        report["checks"]["xodr_parse"] = {"ok": xodr_ok, "error": xodr_err}

        # YOLO integration is optional; never blocks experiments.
        report["checks"]["yolo"] = _yolo_integration_check()

        offline_ok = all(v.get("ok", False) for v in imports.values()) and xodr_ok

        # CARLA checks (optional)
        if args.skip_carla:
            report["checks"]["carla"] = {"available": None, "status": "skipped_by_flag"}
        else:
            report["checks"]["carla"] = _carla_checks(
                host=str(args.host),
                port=int(args.port),
                manual_town=str(args.manual_town),
                spawn_index=int(args.spawn_index),
                vehicle_blueprint=str(args.vehicle),
                out_dir=out_dir,
            )

        carla_available = bool(report["checks"]["carla"].get("available"))
        carla_ok = (not carla_available) or report["checks"]["carla"].get("status") == "ok"

        # Extract stage tracking for report
        report["stage_reached"] = report["checks"]["carla"].get("stage_reached")
        report["failing_stage"] = report["checks"]["carla"].get("failing_stage")

        report["success"] = bool(offline_ok and carla_ok)
        _write_json(report_path, report)
        _write_json(
            status_path,
            {
                "success": report["success"],
                "offline_ok": bool(offline_ok),
                "carla_ok": bool(carla_ok),
                "carla_available": bool(carla_available),
                "stage_reached": report["stage_reached"],
                "failing_stage": report["failing_stage"],
                "report": str(report_path),
            },
        )

        if report["success"]:
            print(f"[OK] smoke_check_all: {out_dir}")
            return 0

        print(f"[ERROR] smoke_check_all failed: {out_dir}")
        if not offline_ok:
            print("[ERROR] Offline checks failed (imports or XODR parse).")
        if carla_available and not carla_ok:
            print("[ERROR] CARLA checks failed (RPC/load/tick/spawn).")
            # Write debug log for CARLA failures
            log_path = _write_debug_log(
                out_dir,
                args=args,
                carla_result=report["checks"]["carla"],
            )
            print(f"[DEBUG] Debug log written: {log_path}")
        return 2
    except Exception:
        tb = traceback.format_exc()
        _write_json(
            report_path,
            {
                "success": False,
                "error": "unhandled_exception",
                "traceback": tb,
            },
        )
        _write_json(status_path, {"success": False, "error": "unhandled_exception", "report": str(report_path)})
        # Write debug log with traceback
        _write_debug_log(
            out_dir,
            args=args,
            carla_result={"status": "exception", "error": "unhandled_exception"},
            exc_traceback=tb,
        )
        print(f"[ERROR] smoke_check_all crashed: {out_dir}")
        print(f"[DEBUG] Debug log written: {out_dir / 'smoke_check.log'}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
