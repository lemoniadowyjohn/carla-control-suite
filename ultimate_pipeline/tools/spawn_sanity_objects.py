#!/usr/bin/env python3
"""
Deterministic CARLA object placement sanity tool.

Connects to CARLA, loads a map, spawns a fixed set of props/vehicles, and logs
actor IDs + transforms to spawn_sanity_objects_log.json. Debug markers can be
dropped for quick visual confirmation.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

import carla

from ultimate_pipeline.utils.bootstrap import bootstrap_console

from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
bootstrap_console()


def _tf_to_dict(tf: carla.Transform) -> Dict[str, Dict[str, float]]:
    loc = tf.location
    rot = tf.rotation
    return {
        "location": {"x": loc.x, "y": loc.y, "z": loc.z},
        "rotation": {"roll": rot.roll, "pitch": rot.pitch, "yaw": rot.yaw},
    }


def _relative_to_base(base: carla.Transform, target: carla.Transform) -> Dict[str, float]:
    bl = base.location
    br = base.rotation
    tl = target.location
    tr = target.rotation
    return {
        "dx": float(tl.x - bl.x),
        "dy": float(tl.y - bl.y),
        "dz": float(tl.z - bl.z),
        "droll": float(tr.roll - br.roll),
        "dpitch": float(tr.pitch - br.pitch),
        "dyaw": float(tr.yaw - br.yaw),
    }


def _clamp_index(idx: int, total: int) -> int:
    return max(0, min(idx, max(0, total - 1)))


def _get_base_spawn(world: carla.World, index: int) -> carla.Transform:
    spawns = world.get_map().get_spawn_points()
    if not spawns:
        raise RuntimeError("No spawn points found in this map.")
    return spawns[_clamp_index(index, len(spawns))]


def _offset_from_base(base: carla.Transform, dx: float, dy: float, dz: float, yaw_delta: float = 0.0) -> carla.Transform:
    offset_loc = base.transform(carla.Location(x=dx, y=dy, z=dz))
    rot = carla.Rotation(
        pitch=base.rotation.pitch,
        yaw=base.rotation.yaw + yaw_delta,
        roll=base.rotation.roll,
    )
    return carla.Transform(offset_loc, rot)


def _build_default_layout(world: carla.World, base_spawn_index: int) -> List[Dict[str, object]]:
    base = _get_base_spawn(world, base_spawn_index)
    # Spread objects around the base spawn so they are visible and non-random.
    defaults = [
        {"name": "sanity_vehicle", "blueprint": "vehicle.tesla.model3", "offset": (0.0, 0.0, 0.0), "yaw_offset": 0.0},
        {"name": "barrier_left", "blueprint": "static.prop.streetbarrier", "offset": (8.0, 3.5, 0.0), "yaw_offset": 0.0},
        {"name": "barrier_right", "blueprint": "static.prop.streetbarrier", "offset": (8.0, -3.5, 0.0), "yaw_offset": 0.0},
        {"name": "cone_front", "blueprint": "static.prop.constructioncone", "offset": (4.0, 1.5, 0.0), "yaw_offset": 0.0},
        {"name": "cone_rear", "blueprint": "static.prop.constructioncone", "offset": (-4.0, -1.5, 0.0), "yaw_offset": 0.0},
    ]

    layout: List[Dict[str, object]] = []
    for entry in defaults:
        tf = _offset_from_base(base, *entry["offset"], yaw_delta=float(entry.get("yaw_offset", 0.0)))
        layout.append({"name": entry["name"], "blueprint": entry["blueprint"], "transform": tf})
    return layout


def _load_layout_from_json(path: Path, world: carla.World, base_spawn_index: int) -> List[Dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "objects" not in data:
        raise ValueError("Layout JSON must be an object with an 'objects' array.")

    base_idx = int(data.get("base_spawn_index", base_spawn_index))
    base_tf = _get_base_spawn(world, base_idx)

    layout: List[Dict[str, object]] = []
    for obj in data.get("objects", []):
        name = str(obj.get("name", "unnamed"))
        bp = str(obj.get("blueprint", ""))
        if not bp:
            raise ValueError(f"Object '{name}' is missing blueprint.")

        if "offset" in obj:
            off = obj["offset"]
            dx = float(off.get("x", 0.0))
            dy = float(off.get("y", 0.0))
            dz = float(off.get("z", 0.0))
            yaw_delta = float(obj.get("yaw_offset", 0.0))
            tf = _offset_from_base(base_tf, dx, dy, dz, yaw_delta=yaw_delta)
        else:
            loc = obj.get("location", {})
            rot = obj.get("rotation", {})
            tf = carla.Transform(
                carla.Location(x=float(loc.get("x", 0.0)), y=float(loc.get("y", 0.0)), z=float(loc.get("z", 0.0))),
                carla.Rotation(
                    roll=float(rot.get("roll", 0.0)),
                    pitch=float(rot.get("pitch", 0.0)),
                    yaw=float(rot.get("yaw", 0.0)),
                ),
            )

        layout.append({"name": name, "blueprint": bp, "transform": tf})
    return layout


def main() -> int:
    ap = argparse.ArgumentParser(description="Spawn deterministic sanity objects in CARLA and log their transforms.")
    ap.add_argument("--map", required=False, help="Map name to load (e.g., Town03). If omitted, uses current world.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--config", type=Path, help="Optional JSON layout. Supports absolute transforms or offsets from base spawn.")
    ap.add_argument("--base-spawn-index", type=int, default=0, help="Spawn point index used for default or relative layouts.")
    ap.add_argument("--report", type=Path, default=Path("spawn_sanity_objects_log.json"), help="Where to write the log JSON.")
    ap.add_argument("--screenshot", type=Path, help="Optional path to save an RGB screenshot of the spawned objects.")
    ap.add_argument("--hold-seconds", type=float, default=2.0, help="Time to keep actors alive before optional cleanup.")
    ap.add_argument("--keep-alive", action="store_true", help="Leave spawned actors alive after the script exits.")
    ap.add_argument("--no-markers", dest="markers", action="store_false", help="Disable debug markers.")
    ap.add_argument("--marker-life", type=float, default=12.0, help="Lifetime for debug markers (seconds).")
    args = ap.parse_args()

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = _reload_ready_for_sensors(client, map_name=args.map, tm_port=8000) if args.map else client.get_world()

    map_name = world.get_map().name
    print(f"Connected to {args.host}:{args.port}, map={map_name}")

    base_tf = _get_base_spawn(world, args.base_spawn_index)
    if args.config:
        layout = _load_layout_from_json(args.config, world, args.base_spawn_index)
    else:
        layout = _build_default_layout(world, args.base_spawn_index)

    bp_lib = world.get_blueprint_library()
    spawned: List[carla.Actor] = []
    entries: List[Dict[str, Any]] = []

    for item in layout:
        name = str(item["name"])
        bp_id = str(item["blueprint"])
        tf: carla.Transform = item["transform"]

        bp = bp_lib.find(bp_id)
        if bp is None:
            print(f"Blueprint not found: {bp_id}")
            entries.append(
                {"name": name, "blueprint": bp_id, "spawned": False, "reason": "blueprint_not_found", "transform": _tf_to_dict(tf)}
            )
            continue

        actor = world.try_spawn_actor(bp, tf)
        if actor is None:
            print(f"Spawn failed (collision?) for {name} ({bp_id}) at {tf}")
            entries.append(
                {"name": name, "blueprint": bp_id, "spawned": False, "reason": "spawn_returned_none", "transform": _tf_to_dict(tf)}
            )
            continue

        spawned.append(actor)
        print(f"Spawned {name}: id={actor.id} type={actor.type_id}")
        actor_tf = actor.get_transform()
        entries.append(
            {
                "name": name,
                "blueprint": bp_id,
                "spawned": True,
                "actor_id": actor.id,
                "transform": _tf_to_dict(actor_tf),
                "relative_to_reference_spawn": _relative_to_base(base_tf, actor_tf),
            }
        )

        if args.markers:
            world.debug.draw_string(actor.get_transform().location, name, life_time=args.marker_life)

    # Optional screenshot
    if args.screenshot:
        import queue
        shot_path = Path(args.screenshot).resolve()
        shot_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Use first spawned object as a focus point if possible
        cam_loc = base_tf.location + carla.Location(x=-10, z=10)
        cam_rot = carla.Rotation(pitch=-30, yaw=base_tf.rotation.yaw)
        cam_tf = carla.Transform(cam_loc, cam_rot)
        
        cam_bp = bp_lib.find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", "1280")
        cam_bp.set_attribute("image_size_y", "720")
        
        camera = world.spawn_actor(cam_bp, cam_tf)
        image_queue = queue.Queue()
        camera.listen(image_queue.put)
        
        # Tick to get the frame
        world.tick()
        try:
            image = image_queue.get(timeout=10.0)
            image.save_to_disk(str(shot_path))
            print(f"Saved screenshot to {shot_path}")
        except queue.Empty:
            print("FAILED to capture screenshot (timeout)")
        finally:
            camera.destroy()

    if args.hold_seconds > 0:
        world.tick()
        time.sleep(args.hold_seconds)

    if not args.keep_alive:
        for actor in reversed(spawned):
            try:
                actor.destroy()
            except Exception:
                pass

    report_path = args.report
    if report_path.is_dir():
        report_path = report_path / "spawn_sanity_objects_log.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": args.host,
        "port": args.port,
        "map": map_name,
        "base_spawn_index": args.base_spawn_index,
        "reference_spawn_transform": _tf_to_dict(base_tf),
        "markers": {"enabled": bool(args.markers), "life_time": args.marker_life},
        "keep_alive": bool(args.keep_alive),
        "objects": entries,
    }

    report_path.write_text(json.dumps(report_payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote log to {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
