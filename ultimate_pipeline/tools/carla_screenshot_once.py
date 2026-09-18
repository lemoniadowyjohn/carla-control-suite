#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Capture a single CARLA RGB screenshot with minimal dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import time


def _sanitize_reason(reason: str) -> str:
    if not reason:
        return "unknown_error"
    return reason.encode("ascii", "replace").decode("ascii")


def _write_result(out_dir: str, result: dict) -> None:
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "screenshot_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=True)


def _advance_world(world, timeout_s: float) -> bool:
    try:
        world.tick()
        return True
    except Exception:
        try:
            # CARLA 0.9.16: must use positional float, not keyword arg
            world.wait_for_tick(float(timeout_s))
            return True
        except Exception:
            return False


def main() -> int:
    global return_code
    parser = argparse.ArgumentParser(description="Capture one CARLA screenshot.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout-s", type=float, default=45.0)
    parser.add_argument("--warmup", type=int, default=10)
    args = parser.parse_args()

    png_path = os.path.join(args.out, "screenshot_once.png")
    result = {
        "status": "FAIL",
        "failure_reason": "",
        "png_path": png_path,
        "host": args.host,
        "port": args.port,
    }

    from ultimate_pipeline.carla_tools.carla_readiness import wait_for_carla_ready
    readiness = wait_for_carla_ready(args.host, args.port, timeout_s=args.timeout_s, require_tick=True)
    if not readiness.get("ok", False):
        result["failure_reason"] = "carla_not_ready"
        result["carla_readiness"] = readiness
        _write_result(args.out, result)
        return 1

    try:
        import carla  # type: ignore
    except Exception as exc:
        result["failure_reason"] = _sanitize_reason(f"carla_import_failed: {exc}")
        result["carla_readiness"] = readiness
        _write_result(args.out, result)
        return 1

    vehicle = None
    camera = None
    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(args.timeout_s)
        world = client.get_world()
        if not _advance_world(world, args.timeout_s):
            raise RuntimeError("carla_tick_failed")

        carla_map = world.get_map()
        spawns = carla_map.get_spawn_points()
        if not spawns:
            raise RuntimeError("no_spawn_points")

        bp_lib = world.get_blueprint_library()
        vehicle_bps = bp_lib.filter("vehicle.*")
        if not vehicle_bps:
            raise RuntimeError("no_vehicle_blueprints")

        vehicle = world.try_spawn_actor(vehicle_bps[0], spawns[0])
        if vehicle is None:
            raise RuntimeError("spawn_vehicle_failed")

        cam_bp = bp_lib.find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", "800")
        cam_bp.set_attribute("image_size_y", "600")
        cam_bp.set_attribute("fov", "90")
        cam_transform = carla.Transform(carla.Location(x=1.5, z=1.7))
        camera = world.spawn_actor(cam_bp, cam_transform, attach_to=vehicle)

        img_queue: "queue.Queue" = queue.Queue()
        camera.listen(lambda img: img_queue.put(img))

        warmup_frames = max(0, args.warmup)
        for _ in range(warmup_frames):
            _advance_world(world, args.timeout_s)
            try:
                img_queue.get(timeout=0.5)
            except queue.Empty:
                pass

        deadline = time.time() + args.timeout_s
        image = None
        while time.time() < deadline:
            _advance_world(world, args.timeout_s)
            try:
                image = img_queue.get(timeout=1.0)
                if image is not None:
                    break
            except queue.Empty:
                continue

        if image is None:
            raise RuntimeError("no_image_received")

        os.makedirs(args.out, exist_ok=True)
        image.save_to_disk(png_path)

        result["status"] = "PASS"
        result["failure_reason"] = ""
        result["carla_readiness"] = readiness
        return_code = 0
    except Exception as exc:
        result["failure_reason"] = _sanitize_reason(str(exc))
        result["carla_readiness"] = readiness
        return_code = 1
    finally:
        try:
            if camera is not None:
                camera.stop()
        except Exception:
            pass
        try:
            if camera is not None:
                camera.destroy()
        except Exception:
            pass
        try:
            if vehicle is not None:
                vehicle.destroy()
        except Exception:
            pass
        _write_result(args.out, result)

    return return_code


if __name__ == "__main__":
    sys.exit(main())
