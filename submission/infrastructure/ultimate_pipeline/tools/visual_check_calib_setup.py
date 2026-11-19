#!/usr/bin/env python3
# -*- coding: utf-8 -*-

r"""
Visual verification tool:
- Spawn ego vehicle
- Spawn labeled objects around ego (unique labels + optional prop variety)
- Attach sensors from calib_data.json:
  * Cameras: use K_undistortion, image_size; ignore K and D
  * cTv is vehicle->camera (as given)
  * LiDAR vTl is lidar->vehicle (as given)
- Capture images from all cameras, save, build mosaic (optional)
- Write rig_manifest.json (label->world + label->ego-relative)

Run from project root (PowerShell recommended):
  .\.venv\Scripts\python.exe .\ultimate_pipeline\tools\visual_check_calib_setup.py `
      --calib ".\ultimate_pipeline\sensors\calib_data.json" `
      --out ".\calib_visual_out" `
      --ticks 50 --sync
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import numpy as np
import carla
from carla import Actor


# -----------------------------
# Helpers
# -----------------------------

def ensure_mat4(m: Any, name: str) -> np.ndarray:
    arr = np.array(m, dtype=float)
    if arr.shape != (4, 4):
        raise ValueError(f"{name} must be 4x4, got {arr.shape}")
    return arr

def fov_from_K(K: Any, width_px: int) -> float:
    K = np.array(K, dtype=float)
    fx = float(K[0, 0])
    if fx <= 1e-9:
        return 90.0
    return float(2.0 * math.degrees(math.atan(width_px / (2.0 * fx))))

def rotmat_to_euler_zyx_deg(R: np.ndarray) -> Tuple[float, float, float]:
    # roll(X), pitch(Y), yaw(Z), ZYX convention
    v = float(-R[2, 0])
    v = max(-1.0, min(1.0, v))
    pitch = math.asin(v)
    roll = math.atan2(R[2, 1], R[2, 2])
    yaw = math.atan2(R[1, 0], R[0, 0])
    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)

def vehicle_pose_from_sensor_to_vehicle(
    T_sensor_to_vehicle: np.ndarray,
    *,
    is_camera_optical_frame: bool,
) -> carla.Transform:
    """
    We attach with carla.Transform where:
      - location is sensor origin in vehicle coordinates
      - rotation describes sensor axes relative to vehicle

    T_sensor_to_vehicle is expected as:
      p_vehicle = R_v_s * p_sensor + t_v_s
    where t_v_s is sensor origin in vehicle coords. (This matches your data well.)
    """

    R_v_s = T_sensor_to_vehicle[:3, :3].copy()
    t_v_s = T_sensor_to_vehicle[:3, 3].copy()

    # If camera is in optical frame (x right, y down, z forward), convert to CARLA sensor axes.
    if is_camera_optical_frame:
        # CARLA sensor: x forward, y right, z up
        # optical:      x right,   y down,  z forward
        # R_carla_from_optical:
        R_carla_from_optical = np.array(
            [[0.0, 0.0, 1.0],
             [1.0, 0.0, 0.0],
             [0.0, -1.0, 0.0]],
            dtype=float,
        )
        # We currently have R_vehicle_from_optical. Need R_vehicle_from_carlaSensor:
        R_optical_from_carla = R_carla_from_optical.T
        R_v_s = R_v_s @ R_optical_from_carla

    roll, pitch, yaw = rotmat_to_euler_zyx_deg(R_v_s)
    loc = carla.Location(x=float(t_v_s[0]), y=float(t_v_s[1]), z=float(t_v_s[2]))
    rot = carla.Rotation(roll=float(roll), pitch=float(pitch), yaw=float(yaw))
    return carla.Transform(loc, rot)

def try_project_to_road(world: carla.World, loc: carla.Location) -> carla.Location:
    try:
        wpt = world.get_map().get_waypoint(loc, project_to_road=True, lane_type=carla.LaneType.Driving)
        if wpt is not None:
            return carla.Location(x=wpt.transform.location.x, y=wpt.transform.location.y, z=wpt.transform.location.z)
    except Exception:
        pass
    return loc


# -----------------------------
# Data classes
# -----------------------------

@dataclass(frozen=True)
class CameraCalib:
    name: str
    width: int
    height: int
    K_undist: Any
    cTv: Any  # vehicle->camera (given)

@dataclass(frozen=True)
class LidarCalib:
    name: str
    vTl: Any  # lidar->vehicle (given)


def load_calib(path: Path) -> Tuple[Dict[str, CameraCalib], Dict[str, LidarCalib]]:
    data = json.loads(path.read_text(encoding="utf-8"))

    cams: Dict[str, CameraCalib] = {}
    for name, c in data.get("cameras", {}).items():
        w, h = int(c["image_size"][0]), int(c["image_size"][1])
        cams[name] = CameraCalib(
            name=name,
            width=w,
            height=h,
            K_undist=c["K_undistortion"],
            cTv=c["cTv"],
        )

    lids: Dict[str, LidarCalib] = {}
    for name, l in data.get("lidars", {}).items():
        lids[name] = LidarCalib(name=name, vTl=l["vTl"])

    if not cams:
        raise RuntimeError("No cameras found in calib_data.json")

    return cams, lids


# -----------------------------
# Spawning
# -----------------------------

def spawn_ego(world: carla.World, bp_filter: str, spawn_index: int) -> Actor:
    lib = world.get_blueprint_library()
    bps = lib.filter(bp_filter)
    if not bps:
        raise RuntimeError(f"No vehicle blueprint matches: {bp_filter}")
    bp = bps[0]
    bp.set_attribute("role_name", "ego")

    spawns = world.get_map().get_spawn_points()
    if not spawns:
        raise RuntimeError("No spawn points in this map.")
    spawn_index = max(0, min(spawn_index, len(spawns) - 1))

    ego = world.try_spawn_actor(bp, spawns[spawn_index])
    if not ego:
        raise RuntimeError("Failed to spawn ego.")
    return ego

def spawn_labeled_rig(
    world: carla.World,
    ego: carla.Actor,
    *,
    radii=(5.0, 8.0, 12.0, 18.0),
    angles_deg=(0, 30, 60, 90, 120, 150, 180, -150, -120, -90, -60, -30),
    heights=(0.25, 1.25),
    life_time=120.0,
) -> Tuple[List[carla.Actor], List[dict]]:
    """
    “Crucial angles” rig:
    - Many angles (front/side/rear + diagonals)
    - Multiple radii (near/mid/far)
    - Two heights (exposes pitch/roll confusion)
    - Unique labels via debug text (reliable) + optional prop variety (nice-to-have)
    """
    lib = world.get_blueprint_library()
    prop_ids = [
        "static.prop.streetbarrier",
        "static.prop.warningconstruction",
        "static.prop.trafficcone01",
        "static.prop.constructioncone",
        "static.prop.garbage01",
        "static.prop.garbage02",
        "static.prop.shoppingcart",
        "static.prop.box01",
    ]
    prop_bps = [lib.find(pid) for pid in prop_ids if lib.find(pid) is not None]

    ego_tf = ego.get_transform()
    spawned: List[carla.Actor] = []
    manifest: List[dict] = []

    idx = 0
    for r in radii:
        for ang in angles_deg:
            a = math.radians(float(ang))
            off = carla.Location(x=r * math.cos(a), y=r * math.sin(a), z=0.0)
            wloc = ego_tf.transform(off)
            wloc = try_project_to_road(world, wloc)

            for hz in heights:
                loc = carla.Location(x=wloc.x, y=wloc.y, z=wloc.z + float(hz))
                label = f"R{int(r)}_A{int(ang)}_H{int(hz*10)}"

                # big, unique, readable label in camera images
                try:
                    world.debug.draw_string(
                        loc,
                        label,
                        draw_shadow=True,
                        color=carla.Color(255, 0, 0),
                        life_time=float(life_time),
                        persistent_lines=False
                    )
                except Exception:
                    pass

                actor_id = None
                bp_id = None
                if prop_bps:
                    bp = prop_bps[idx % len(prop_bps)]
                    idx += 1
                    tf = carla.Transform(loc, carla.Rotation(yaw=ego_tf.rotation.yaw))
                    a_spawn = world.try_spawn_actor(bp, tf)
                    if a_spawn:
                        spawned.append(a_spawn)
                        actor_id = a_spawn.id
                        bp_id = bp.id

                # store ego-relative too (helps your perception pipeline)
                ego_loc = ego_tf.location
                rel = [loc.x - ego_loc.x, loc.y - ego_loc.y, loc.z - ego_loc.z]

                manifest.append({
                    "label": label,
                    "radius_m": float(r),
                    "angle_deg": float(ang),
                    "height_m": float(hz),
                    "world_xyz": [float(loc.x), float(loc.y), float(loc.z)],
                    "ego_rel_xyz": rel,
                    "blueprint": bp_id,
                    "actor_id": actor_id,
                })

    print(f"🧱 Rig spawned: {len(spawned)} props + {len(manifest)} labeled points.")
    return spawned, manifest


# -----------------------------
# Sensor attachment
# -----------------------------

def attach_sensors_from_calib(
    world: carla.World,
    ego: carla.Vehicle,
    cams: Dict[str, CameraCalib],
    lids: Dict[str, LidarCalib],
    *,
    camera_optical_frame: bool,
) -> Tuple[Dict[str, carla.Actor], List[carla.Sensor]]:
    bp_lib = world.get_blueprint_library()
    out: Dict[str, carla.Actor] = {}
    listeners: List[carla.Sensor] = []

    cam_bp = bp_lib.find("sensor.camera.rgb")
    if cam_bp is None:
        raise RuntimeError("Missing blueprint: sensor.camera.rgb")

    for name, cam in cams.items():
        bp = cam_bp
        bp.set_attribute("image_size_x", str(cam.width))
        bp.set_attribute("image_size_y", str(cam.height))
        bp.set_attribute("fov", str(fov_from_K(cam.K_undist, cam.width)))
        bp.set_attribute("sensor_tick", "0.0")

        # Given: cTv is vehicle->camera (your definition).
        # Convert to sensor->vehicle for pose extraction: inv(vehicle->camera) = camera->vehicle
        cTv = ensure_mat4(cam.cTv, f"{name}.cTv")
        vTc = np.linalg.inv(cTv)  # camera->vehicle

        tf = vehicle_pose_from_sensor_to_vehicle(vTc, is_camera_optical_frame=camera_optical_frame)
        actor = world.spawn_actor(bp, tf, attach_to=ego)
        out[name] = actor

    lidar_bp = bp_lib.find("sensor.lidar.ray_cast")
    if lidar_bp is None:
        print("⚠ Missing blueprint: sensor.lidar.ray_cast (skipping lidars)")
        return out, listeners

    for name, lid in lids.items():
        bp = lidar_bp
        bp.set_attribute("range", "80")
        bp.set_attribute("rotation_frequency", "20")
        bp.set_attribute("channels", "64")
        bp.set_attribute("points_per_second", "200000")
        bp.set_attribute("upper_fov", "10")
        bp.set_attribute("lower_fov", "-30")
        bp.set_attribute("sensor_tick", "0.0")

        # Given: vTl is lidar->vehicle (your definition).
        vTl = ensure_mat4(lid.vTl, f"{name}.vTl")  # already sensor->vehicle
        tf = vehicle_pose_from_sensor_to_vehicle(vTl, is_camera_optical_frame=False)

        actor = world.spawn_actor(bp, tf, attach_to=ego)
        out[name] = actor

    return out, listeners


# -----------------------------
# Main
# -----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", required=True, help="Path to calib_data.json")
    ap.add_argument("--out", default="calib_visual_out", help="Output directory")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--vehicle-bp", default="vehicle.tesla.model3")
    ap.add_argument("--spawn-index", type=int, default=0)
    ap.add_argument("--ticks", type=int, default=50)
    ap.add_argument("--sync", action="store_true", help="Enable synchronous mode for stable capture")
    ap.add_argument("--camera-optical", action="store_true", help="Assume camera extrinsics are optical frame (recommended)")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    calib_path = Path(args.calib).resolve()
    cams, lids = load_calib(calib_path)

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = client.get_world()

    old_settings = world.get_settings()
    touched = False

    cleanup: List[carla.Actor] = []
    listening: List[carla.Sensor] = []
    latest_images: Dict[str, str] = {}

    try:
        if args.sync and not old_settings.synchronous_mode:
            s = carla.WorldSettings(
                no_rendering_mode=old_settings.no_rendering_mode,
                synchronous_mode=True,
                fixed_delta_seconds=old_settings.fixed_delta_seconds or 0.05,
                max_substep_delta_time=old_settings.max_substep_delta_time,
                max_substeps=old_settings.max_substeps
            )
            world.apply_settings(s)
            touched = True
            world.tick()

        ego = spawn_ego(world, args.vehicle_bp, args.spawn_index)
        cleanup.append(ego)

        rig_actors, rig_manifest = spawn_labeled_rig(world, ego)
        cleanup.extend(rig_actors)

        (out_dir / "rig_manifest.json").write_text(json.dumps(rig_manifest, indent=2), encoding="utf-8")

        sensors, _ = attach_sensors_from_calib(
            world, ego, cams, lids,
            camera_optical_frame=bool(args.camera_optical)
        )
        cleanup.extend(list(sensors.values()))

        # Listen to camera streams and save frames
        def make_cb(cam_name: str):
            def _cb(image: carla.Image):
                fp = img_dir / f"{cam_name}_{image.frame}.png"
                image.save_to_disk(str(fp))
                latest_images[cam_name] = str(fp)
            return _cb

        for name, actor in sensors.items():
            if isinstance(actor, carla.Sensor) and actor.type_id.startswith("sensor.camera"):
                actor.listen(make_cb(name))
                listening.append(actor)

        print(f"✅ Spawned ego + rig. Attached {len(sensors)} sensors. Capturing {args.ticks} ticks...")
        for _ in range(args.ticks):
            world.tick()

        # Stop only sensors we listened to
        for s in listening:
            try:
                s.stop()
            except Exception:
                pass

        # Mosaic (optional)
        try:
            from PIL import Image
            cam_names = sorted([n for n in latest_images.keys()])
            imgs = [Image.open(latest_images[n]).convert("RGB") for n in cam_names]
            if imgs:
                cols = 3
                rows = (len(imgs) + cols - 1) // cols
                w = max(im.size[0] for im in imgs)
                h = max(im.size[1] for im in imgs)
                mosaic = Image.new("RGB", (cols * w, rows * h))
                for i, im in enumerate(imgs):
                    r = i // cols
                    c = i % cols
                    mosaic.paste(im, (c * w, r * h))
                mosaic_path = out_dir / "mosaic.png"
                mosaic.save(mosaic_path)
                print(f"🧩 Mosaic written → {mosaic_path}")
        except Exception as e:
            print(f"⚠ Mosaic skipped (Pillow missing or error): {e}")

        # Save run info
        run_info = {
            "calib": str(calib_path),
            "camera_optical_frame": bool(args.camera_optical),
            "ticks": int(args.ticks),
            "latest_images": latest_images,
        }
        (out_dir / "run_info.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")
        print(f"🗂 Output → {out_dir}")

    finally:
        # clean up
        for s in listening:
            try:
                s.stop()
            except Exception:
                pass
        for a in reversed(cleanup):
            try:
                a.destroy()
            except Exception:
                pass
        if touched:
            try:
                world.apply_settings(old_settings)
            except Exception:
                pass


if __name__ == "__main__":
    main()
