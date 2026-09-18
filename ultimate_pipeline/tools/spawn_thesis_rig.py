#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, Any

from ultimate_pipeline.utils.bootstrap import bootstrap_console

bootstrap_console()

from ultimate_pipeline.carla_tools.thesis_sensor_rig import ThesisSensorRig, SpawnedSensor
from ultimate_pipeline.optional.carla_api import get_carla
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world_from_file


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Spawn thesis-grade sensor rig in CARLA.")
    ap.add_argument("--calib", required=True, help="Path to calib_data.json")
    ap.add_argument("--host", default="localhost", help="CARLA host")
    ap.add_argument("--port", type=int, default=2000, help="CARLA port")
    ap.add_argument("--map-xodr", dest="map_xodr", required=True, help="Path to OpenDRIVE map")
    ap.add_argument("--out", dest="out_dir", required=True, help="Output directory for reports")
    ap.add_argument(
        "--draw-debug",
        action="store_true",
        help="Draw axis markers and labels for each sensor for 10 seconds.",
    )
    ap.add_argument("--ego-bp", default="", help="Vehicle blueprint id to use (defaults to tesla/lincoln/audi fallback list).")
    ap.add_argument("--spawn-index", type=int, default=0, help="Spawn point index (deterministic).")
    ap.add_argument("--keep-actors", action="store_true", help="Do not destroy spawned actors on exit.")
    ap.add_argument("--include-timestamp", action="store_true", help="Include timestamp_utc in thesis_rig_report.json.")
    return ap.parse_args()


def _connect_client(host: str, port: int):
    carla = get_carla()
    client = carla.Client(host, port)
    client.set_timeout(60.0)
    return client


def _load_world(client: Any, xodr_path: Path):

    if not xodr_path.is_file():
        raise FileNotFoundError(f"OpenDRIVE file not found: {xodr_path}")
    print(f"[spawn_thesis_rig] Loading map from {xodr_path} ...")
    world = load_opendrive_world_from_file(client, xodr_path)
    print("[spawn_thesis_rig] Map loaded.")
    return world


def _pick_vehicle_bp(bp_lib: Any, preferred: str | None = None):
    if preferred:
        try:
            return bp_lib.find(preferred)
        except Exception:
            raise RuntimeError(f"Requested vehicle blueprint not found: {preferred}")

    candidates = [
        "vehicle.tesla.model3",
        "vehicle.lincoln.mkz2017",
        "vehicle.audi.tt",
    ]
    for c in candidates:
        try:
            return bp_lib.find(c)
        except Exception:
            continue
    vehicles = bp_lib.filter("vehicle.*")
    if not vehicles:
        raise RuntimeError("No vehicle blueprints available.")
    return vehicles[0]


def _spawn_ego(world: Any, blueprint_id: str, spawn_index: int):
    spawn_points = world.get_map().get_spawn_points()
    if not spawn_points:
        raise RuntimeError("No spawn points available in the loaded map.")

    base_spawn = spawn_points[0]
    idx = max(0, min(spawn_index, len(spawn_points) - 1))
    chosen_spawn = spawn_points[idx]

    bp = _pick_vehicle_bp(world.get_blueprint_library(), preferred=blueprint_id or None)
    ego = world.try_spawn_actor(bp, chosen_spawn)
    if ego is None:
        raise RuntimeError(f"Failed to spawn ego at index {idx} (ref spawn_index={spawn_index}).")
    return ego, base_spawn, chosen_spawn, idx


def _sleep_with_world(world: Any, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            # CARLA 0.9.16: must use positional float, not keyword arg
            world.wait_for_tick(1.0)
        except Exception:
            time.sleep(0.5)


def _write_report(path: Path, report: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)


def _tf_to_dict(tf: Any) -> Dict[str, Dict[str, float]]:
    loc = tf.location
    rot = tf.rotation
    return {
        "location": {"x": float(loc.x), "y": float(loc.y), "z": float(loc.z)},
        "rotation": {"roll": float(rot.roll), "pitch": float(rot.pitch), "yaw": float(rot.yaw)},
    }


def _relative_offset(ref_tf: Any, target_tf: Any) -> Dict[str, float]:
    """Return target - ref (location and yaw/pitch/roll deltas)."""
    ref_loc = ref_tf.location
    ref_rot = ref_tf.rotation
    tgt_loc = target_tf.location
    tgt_rot = target_tf.rotation
    return {
        "dx": float(tgt_loc.x - ref_loc.x),
        "dy": float(tgt_loc.y - ref_loc.y),
        "dz": float(tgt_loc.z - ref_loc.z),
        "droll": float(tgt_rot.roll - ref_rot.roll),
        "dpitch": float(tgt_rot.pitch - ref_rot.pitch),
        "dyaw": float(tgt_rot.yaw - ref_rot.yaw),
    }


def main() -> int:
    args = _parse_args()

    calib_path = Path(args.calib)
    out_dir = Path(args.out_dir)
    xodr_path = Path(args.map_xodr)

    if not calib_path.is_file():
        print(f"[spawn_thesis_rig] Calibration file not found: {calib_path}")
        return 1

    try:
        calib_data = json.loads(calib_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[spawn_thesis_rig] Failed to read calibration file: {exc}")
        return 1

    cams = calib_data.get("cameras", {}) if isinstance(calib_data, dict) else {}
    lids = calib_data.get("lidars", {}) if isinstance(calib_data, dict) else {}
    if not cams and not lids:
        raise RuntimeError("calib_data.json contains no cameras or lidars.")
    client = _connect_client(args.host, args.port)
    print(f"[spawn_thesis_rig] Connected to CARLA at {args.host}:{args.port}")

    ego = None
    spawned: Dict[str, SpawnedSensor] = {}
    world = None

    try:
        world = _load_world(client, xodr_path)
        ego, ref_spawn, chosen_spawn, used_index = _spawn_ego(world, args.ego_bp, args.spawn_index)
        print(f"[spawn_thesis_rig] Ego vehicle spawned with id={ego.id} at index={used_index}")

        rig = ThesisSensorRig(calib_path)
        spawned = rig.spawn_rig(world, ego)
        print(f"[spawn_thesis_rig] Attached {len(spawned)} sensors.")

        ego_tf = ego.get_transform()
        sensors_report: Dict[str, Any] = {}
        for name in sorted(spawned.keys()):
            s = spawned[name]
            tf = s.actor.get_transform()
            rel = _relative_offset(ref_spawn, tf)
            entry = dict(s.report)
            entry["carla_transform"] = _tf_to_dict(tf)
            entry["relative_to_reference_spawn"] = rel
            sensors_report[name] = entry

        ego_report = {
            "actor_id": ego.id,
            "blueprint": ego.type_id,
            "spawn_index": used_index,
            "relative_to_reference_spawn": _relative_offset(ref_spawn, ego_tf),
            "carla_transform": _tf_to_dict(ego_tf),
        }

        report = {
            "calibration_file": str(calib_path),
            "map_xodr": str(xodr_path),
            "host": args.host,
            "port": int(args.port),
            "transform_notes": (
                "cTv (vehicle->camera) is used directly; inversion is forbidden by the thesis contract. "
                "vTl (lidar->vehicle) is inverted to vehicle->lidar for CARLA attachment."
            ),
            "reference_spawn_index": 0,
            "reference_spawn_transform": _tf_to_dict(ref_spawn),
            "ego": ego_report,
            "sensors": sensors_report,
        }
        if args.include_timestamp:
            report["timestamp_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        report_path = out_dir / "thesis_rig_report.json"
        _write_report(report_path, report)
        print(f"[spawn_thesis_rig] Report written to {report_path}")

        if args.draw_debug and world is not None:
            print("[spawn_thesis_rig] Drawing debug axes for 10 seconds...")
            ThesisSensorRig.draw_debug_axes(world, spawned, life_time=10.0, scale=1.0)
            _sleep_with_world(world, 10.0)
        else:
            if world is not None:
                _sleep_with_world(world, 1.0)

    except Exception as exc:
        print(f"[spawn_thesis_rig] Error: {exc}")
        return 1
    finally:
        if not args.keep_actors:
            for sensor in spawned.values():
                try:
                    sensor.actor.stop()
                except Exception:
                    pass
                try:
                    sensor.actor.destroy()
                except Exception:
                    pass
            if ego is not None:
                try:
                    ego.destroy()
                except Exception:
                    pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
