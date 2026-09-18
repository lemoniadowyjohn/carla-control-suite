#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CARLA map probe tool (import-safe).

This tool probes a CARLA server with an OpenDRIVE map load.
All CARLA-dependent imports are deferred to main() to allow import-time safety checks.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import copy
from typing import Any


def _clone_transform(tf: Any) -> Any:
    """Best-effort clone of a Transform-like object.

    Must be import-safe without CARLA installed. Unit tests use DummyTransform.
    """
    try:
        return copy.deepcopy(tf)
    except Exception:
        try:
            return copy.copy(tf)
        except Exception:
            return tf


def _spawn_props(world: Any, ego_tf: Any, *, count: int = 3) -> int:
    """Spawn a few static props near the ego transform without mutating ego_tf.

    Used by unit tests (no CARLA). Returns number of spawn attempts.
    """
    try:
        bp_lib = world.get_blueprint_library()
    except Exception:
        return 0

    bp = None
    try:
        cands = list(bp_lib.filter("static.prop.*"))
        if cands:
            bp = cands[0]
    except Exception:
        bp = None
    if bp is None:
        try:
            bp = bp_lib.find("static.prop.trafficcone01")
        except Exception:
            return 0

    spawned = 0
    for i in range(int(count)):
        tf2 = _clone_transform(ego_tf)
        try:
            if hasattr(tf2, "location") and hasattr(tf2.location, "x"):
                tf2.location.x = float(tf2.location.x) + 1.0 + float(i)
            if hasattr(tf2, "location") and hasattr(tf2.location, "y"):
                tf2.location.y = float(tf2.location.y) + 0.5 * float(i)
        except Exception:
            pass
        try:
            world.try_spawn_actor(bp, tf2)
            spawned += 1
        except Exception:
            continue
    return spawned


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Load an XODR in CARLA, spawn ego+props, tick, and save a screenshot."
    )
    ap.add_argument("--xodr", required=True, type=Path, help="Path to OpenDRIVE .xodr")
    ap.add_argument("--out", required=True, type=Path, help="Output directory for logs/results")
    ap.add_argument("--host", default="127.0.0.1", help="CARLA host")
    ap.add_argument("--port", type=int, default=2000, help="CARLA RPC port")
    ap.add_argument("--frames", type=int, default=50, help="Number of ticks to run after load")
    return ap.parse_args()


def main() -> int:
    """Entry point with lazy imports for CARLA-dependent code."""
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    # Lazy imports - these pull in carla and carla_opendrive_loader
    import json
    import math
    import time
    from queue import Queue, Empty
    from typing import Any, Dict

    def _save_json(path: Path, data: Dict[str, Any]) -> None:
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    result_path = args.out / "probe_result.json"

    try:
        # Import CARLA-dependent modules here (not at module level)
        from ultimate_pipeline.quality.check_lane_link_targets_exist import check_lane_link_targets_exist
        from ultimate_pipeline.carla_tools.carla_readiness import wait_for_carla_ready

        lane_report = check_lane_link_targets_exist(str(args.xodr))
        _save_json(args.out / "lane_link_target_report.json", lane_report)
        if not lane_report.get("ok", False):
            payload = {
                "status": "FAIL",
                "failure_reason": "lane_link_targets_failed",
                "frames": args.frames,
                "host": args.host,
                "port": args.port,
                "screenshot_path": "",
            }
            _save_json(result_path, payload)
            print(json.dumps(payload, indent=2))
            return 1

        readiness = wait_for_carla_ready(args.host, args.port, timeout_s=45.0, require_tick=True)
        if not readiness.get("ok", False):
            payload = {
                "status": "FAIL",
                "failure_reason": "carla_not_ready",
                "frames": args.frames,
                "host": args.host,
                "port": args.port,
                "screenshot_path": "",
                "carla_readiness": readiness,
            }
            _save_json(result_path, payload)
            print(json.dumps(payload, indent=2))
            return 1

        import carla  # type: ignore
        from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world, ensure_world_ticks

        client = carla.Client(args.host, args.port)
        client.set_timeout(45.0)

        xodr_text = args.xodr.read_text(encoding="utf-8", errors="ignore")
        world = load_opendrive_world(
            client,
            xodr_text,
            params=None,
            timeout_s=45.0,
            retries=0,
            do_reload=True,
            fallback_enabled=False,
            fallback_maps=None,
        )

        ensure_world_ticks(world, n=3, timeout_per_tick_s=2.0)

        original_settings = world.get_settings()
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        settings.no_rendering_mode = False
        world.apply_settings(settings)

        actors = []
        screenshot_path = args.out / "probe_screenshot.png"
        status = "PASS"
        failure_reason = ""

        try:
            spawn_points = world.get_map().get_spawn_points()
            if not spawn_points:
                raise RuntimeError("No spawn points found.")
            ego_tf = spawn_points[0]
            bp_lib = world.get_blueprint_library()
            vehicles = bp_lib.filter("vehicle.audi.a2") or bp_lib.filter("vehicle.*")
            ego_bp = bp_lib.find(vehicles[0].id if hasattr(vehicles[0], "id") else vehicles[0])
            ego = world.try_spawn_actor(ego_bp, ego_tf)
            if ego is None:
                raise RuntimeError("Failed to spawn ego vehicle.")
            actors.append(ego)

            tm = client.get_trafficmanager(8000)
            tm.set_synchronous_mode(True)
            tm.set_random_device_seed(42)
            tm.set_global_distance_to_leading_vehicle(2.0)
            ego.set_autopilot(True, tm.get_port())

            # Spawn camera
            cam_bp = bp_lib.find("sensor.camera.rgb")
            cam_bp.set_attribute("image_size_x", "800")
            cam_bp.set_attribute("image_size_y", "450")
            cam_bp.set_attribute("fov", "90")
            cam_tf = carla.Transform(carla.Location(x=1.5, z=2.0))
            camera = world.spawn_actor(cam_bp, cam_tf, attach_to=ego)
            actors.append(camera)

            camera_q: Queue = Queue(maxsize=8)

            def _cb(img):
                try:
                    camera_q.put_nowait(img)
                except Exception:
                    pass

            camera.listen(_cb)

            captured = False
            for idx in range(args.frames):
                world.tick()
                try:
                    img = camera_q.get(timeout=2.0)
                except Empty:
                    continue
                if not captured or idx == args.frames - 1:
                    img.save_to_disk(str(screenshot_path))
                    captured = True

        except Exception as exc:
            status = "FAIL"
            failure_reason = str(exc)
        finally:
            world.apply_settings(original_settings)
            for actor in actors[::-1]:
                try:
                    actor.destroy()
                except Exception:
                    pass

        payload = {
            "status": status,
            "failure_reason": failure_reason,
            "frames": args.frames,
            "host": args.host,
            "port": args.port,
            "screenshot_path": str(screenshot_path) if screenshot_path.exists() else "",
            "carla_readiness": readiness,
        }
        _save_json(result_path, payload)
        print(json.dumps(payload, indent=2))
        return 0 if status == "PASS" else 1

    except Exception as exc:
        import json as json_fallback
        err = {
            "status": "FAIL",
            "failure_reason": str(exc),
            "frames": args.frames,
            "host": args.host,
            "port": args.port,
        }
        result_path.write_text(json_fallback.dumps(err, indent=2, sort_keys=True), encoding="utf-8")
        print(json_fallback.dumps(err, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
