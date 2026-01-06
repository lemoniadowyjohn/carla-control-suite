#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ultimate_pipeline/perception/record_route.py
"""
Record a short CARLA run on an OpenDRIVE (.xodr) map using Dominik-calibrated sensors,
synchronized capture, and per-frame metadata.

Fixes vs your current script:
✅ Uses the FIXED DominikSensorSetup API (calib_file required, no out_dir arg)
✅ Uses the FIXED SensorRecorder (calibrated + synchronized + meta.jsonl)
✅ Runs CARLA in synchronous mode with fixed delta (deterministic, aligned frames)
✅ Autopilot + TrafficManager in sync mode
✅ Robust spawn (tries multiple spawn points)
✅ Clean cleanup + restores world settings

Example:
python -m ultimate_pipeline.perception.record_route \
  --xodr cities/ingolstadt/ingolstadt_dominik.xodr \
  --calib calib_data.json \
  --out-dir ultimate_pipeline_out/recordings \
  --duration 60 \
  --fps 20 \
  --lidar-format npz \
  --seg
"""

from __future__ import annotations

import os
import time
import json
import argparse
from typing import Optional, Dict, Any, List

import carla

from ultimate_pipeline.sensors.recorder import SensorRecorder, RecorderConfig
from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world, load_builtin_world


# ---------------------------
# CLI
# ---------------------------

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True, help="Path to XODR map (OpenDRIVE .xodr)")
    ap.add_argument("--calib", required=True, help="Path to Dominik calib_data.json")
    ap.add_argument("--out-dir", required=True, help="Base output folder (recording run folder created inside)")
    ap.add_argument("--duration", type=int, default=60, help="Duration in seconds (approx, sync mode)")
    ap.add_argument("--fps", type=int, default=20, help="FPS for synchronous capture")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)

    ap.add_argument("--lidar-format", choices=["npz", "ply"], default="npz",
                    help="LiDAR storage format (npz recommended on HPC)")
    ap.add_argument("--seg", action="store_true", help="Also record semantic segmentation cameras")
    ap.add_argument("--seg-converter", choices=["raw", "cityscapes"], default="cityscapes")

    ap.add_argument("--flip-vehicle-y", action="store_true", default=True,
                    help="Flip vehicle Y (robotics +Y left -> CARLA +Y right). Default: True")
    ap.add_argument("--no-flip-vehicle-y", action="store_false", dest="flip_vehicle_y",
                    help="Disable vehicle Y flip")

    ap.add_argument("--opencv-camera-axes", action="store_true", default=True,
                    help="Assume OpenCV camera axes in calibration and convert to CARLA. Default: True")
    ap.add_argument("--no-opencv-camera-axes", action="store_false", dest="opencv_camera_axes",
                    help="Disable OpenCV->CARLA camera axes conversion")

    ap.add_argument("--vehicle", default="vehicle.audi.a2", help="Vehicle blueprint id")
    ap.add_argument("--tm-port", type=int, default=8000, help="TrafficManager port")
    ap.add_argument("--seed", type=int, default=42, help="TM random seed")
    return ap.parse_args()


# ---------------------------
# CARLA helpers
# ---------------------------

def connect_carla(host: str, port: int) -> carla.Client:
    client = carla.Client(host, port)
    client.set_timeout(60.0)
    return client


def load_map_from_xodr(client: carla.Client, xodr_path: str) -> carla.World:
    # Optionally force built-in maps (useful as a 'keep working' mode).
    if getattr(SETTINGS, "CARLA_FORCE_BUILTIN_MAP", False):
        return load_builtin_world(client, getattr(SETTINGS, "CARLA_BUILTIN_MAP", "Town10HD_Opt"))

    with open(xodr_path, "r", encoding="utf-8") as f:
        xodr_data = f.read()

    return load_opendrive_world(
        client,
        xodr_data,
        params=None,
        timeout_s=180.0,
        retries=2,
        do_reload=True,
        fallback_enabled=getattr(SETTINGS, "CARLA_ENABLE_MAP_FALLBACK", False),
        fallback_maps=getattr(SETTINGS, "CARLA_FALLBACK_MAPS", None),
    )


def _try_spawn_ego(world: carla.World, vehicle_bp_id: str, tries: int = 20) -> carla.Actor:
    bp_lib = world.get_blueprint_library()
    bp = bp_lib.find(vehicle_bp_id)

    spawn_points = world.get_map().get_spawn_points()
    if not spawn_points:
        raise RuntimeError("No spawn points in map (get_spawn_points() empty).")

    # Try multiple spawn points (sometimes first is occupied/invalid)
    for i in range(min(tries, len(spawn_points))):
        ego = world.try_spawn_actor(bp, spawn_points[i])
        if ego is not None:
            return ego

    # Fallback: brute attempt on random subset
    for sp in spawn_points[:tries]:
        ego = world.try_spawn_actor(bp, sp)
        if ego is not None:
            return ego

    raise RuntimeError("Failed to spawn ego vehicle after multiple tries.")


def _setup_tm(world: carla.World, tm_port: int, seed: int) -> carla.TrafficManager:
    client = world.get_client()
    tm = client.get_trafficmanager(tm_port)
    tm.set_synchronous_mode(True)
    tm.set_random_device_seed(seed)
    tm.set_global_distance_to_leading_vehicle(2.0)
    return tm


# ---------------------------
# Main
# ---------------------------

def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    client = connect_carla(args.host, args.port)
    world = load_map_from_xodr(client, args.xodr)

    # Configure TrafficManager + spawn ego
    tm = _setup_tm(world, args.tm_port, args.seed)
    ego = _try_spawn_ego(world, args.vehicle)

    # Autopilot on
    ego.set_autopilot(True, args.tm_port)

    # Recorder config (sync mode + calibrated sensors)
    rec_cfg = RecorderConfig(
        fps=int(args.fps),
        synchronous=True,
        fixed_delta_seconds=1.0 / float(args.fps),
        lidar_format=str(args.lidar_format),
        add_segmentation=bool(args.seg),
        seg_converter=str(args.seg_converter),
        flip_vehicle_y=bool(args.flip_vehicle_y),
        opencv_camera_axes=bool(args.opencv_camera_axes),
    )

    run_name = f"route_{time.strftime('%Y%m%d_%H%M%S')}"
    recorder = SensorRecorder(
        world=world,
        base_logs_dir=args.out_dir,
        calib_file=args.calib,
        run_name=run_name,
        config=rec_cfg,
        verbose=True,
    )

    # Attach calibrated sensors & start listening
    sensors = recorder.attach_to_vehicle(ego)

    # Write run meta (top-level)
    meta = {
        "schema_version": 1,
        "xodr": args.xodr,
        "calib": args.calib,
        "duration_sec": int(args.duration),
        "fps": int(args.fps),
        "frames_target": int(args.duration * args.fps),
        "host": args.host,
        "port": int(args.port),
        "vehicle": args.vehicle,
        "tm_port": int(args.tm_port),
        "seed": int(args.seed),
        "flip_vehicle_y": bool(args.flip_vehicle_y),
        "opencv_camera_axes": bool(args.opencv_camera_axes),
        "lidar_format": args.lidar_format,
        "segmentation": bool(args.seg),
        "seg_converter": args.seg_converter,
        "map_name": world.get_map().name if world and world.get_map() else None,
        "timestamp_start_unix": time.time(),
        "run_dir": recorder.run_dir,
        "sensor_names": list(sensors.keys()),
    }
    with open(os.path.join(recorder.run_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    # Record loop
    frames = int(args.duration * args.fps)
    print(f"🚗 Recording autopilot run: {frames} frames @ {args.fps} FPS ...")

    try:
        # Warm-up a couple frames (helps with first-frame missing sensors)
        for _ in range(10):
            recorder.record_step(ego_vehicle=ego)

        for _ in range(frames):
            recorder.record_step(ego_vehicle=ego)

    finally:
        print("🧹 Cleaning up actors and restoring settings...")
        try:
            recorder.stop()
        except Exception:
            pass

        # Destroy ego last
        try:
            if ego.is_alive:
                ego.destroy()
        except Exception:
            pass

        print(f"✅ Done. Output: {recorder.run_dir}")


if __name__ == "__main__":
    main()
