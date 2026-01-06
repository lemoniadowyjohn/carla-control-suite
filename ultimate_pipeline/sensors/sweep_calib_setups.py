#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sweep calibration conventions + orientation hypotheses, spawn a labeled rig around ego,
capture images for every run, and export CARLA-ready extrinsics for each run.

Outputs:
  <out_dir>/
    run_0001__vehROS1_camOPT1_inv0_yaw0_roll0/
      images/<cam>_<frame>.png
      mosaic.png (if Pillow installed)
      run_config.json
      export_carla.json
      rig_manifest.json

Default sweep size: 64 runs (2*2*2*8).
"""

from __future__ import annotations

import argparse
import json
import math
import time
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import carla


# ==========================================================
# Minimal 4x4 math (no numpy)
# ==========================================================

def mat4_mul(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    out = [[0.0] * 4 for _ in range(4)]
    for r in range(4):
        for c in range(4):
            out[r][c] = sum(a[r][k] * b[k][c] for k in range(4))
    return out


def mat4_inv_rigid(m: List[List[float]]) -> List[List[float]]:
    R = [[m[r][c] for c in range(3)] for r in range(3)]
    t = [m[r][3] for r in range(3)]
    Rt = [[R[c][r] for c in range(3)] for r in range(3)]
    tinv = [
        -(Rt[0][0] * t[0] + Rt[0][1] * t[1] + Rt[0][2] * t[2]),
        -(Rt[1][0] * t[0] + Rt[1][1] * t[1] + Rt[1][2] * t[2]),
        -(Rt[2][0] * t[0] + Rt[2][1] * t[1] + Rt[2][2] * t[2]),
    ]
    out = [[0.0] * 4 for _ in range(4)]
    for r in range(3):
        for c in range(3):
            out[r][c] = Rt[r][c]
        out[r][3] = tinv[r]
    out[3][3] = 1.0
    return out


def mat4_rot_transpose_only(m: List[List[float]]) -> List[List[float]]:
    out = [[0.0] * 4 for _ in range(4)]
    for r in range(3):
        for c in range(3):
            out[r][c] = m[c][r]
    out[3][3] = 1.0
    return out


def change_basis(T_parent_from_child: List[List[float]],
                 B_parent_old_to_new: List[List[float]],
                 B_child_old_to_new: List[List[float]]) -> List[List[float]]:
    # T_new = B_parent * T_old * inv(B_child)
    Bc_inv = mat4_rot_transpose_only(B_child_old_to_new)
    return mat4_mul(mat4_mul(B_parent_old_to_new, T_parent_from_child), Bc_inv)


def rot_z_deg(deg: float) -> List[List[float]]:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0, 0],
            [s, c, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]]


def rot_x_deg(deg: float) -> List[List[float]]:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [[1, 0, 0, 0],
            [0, c, -s, 0],
            [0, s, c, 0],
            [0, 0, 0, 1]]


def mat4_to_carla_transform(m: List[List[float]]) -> carla.Transform:
    # Extract yaw/pitch/roll from rotation matrix in a CARLA-friendly way (ZYX)
    R = [[m[r][c] for c in range(3)] for r in range(3)]

    # pitch = asin(-R[2][0])
    v = max(-1.0, min(1.0, -R[2][0]))
    pitch = math.asin(v)
    if abs(v) > 0.9999:
        yaw = math.atan2(-R[0][1], R[1][1])
        roll = 0.0
    else:
        yaw = math.atan2(R[1][0], R[0][0])
        roll = math.atan2(R[2][1], R[2][2])

    loc = carla.Location(x=float(m[0][3]), y=float(m[1][3]), z=float(m[2][3]))
    rot = carla.Rotation(roll=math.degrees(roll), pitch=math.degrees(pitch), yaw=math.degrees(yaw))
    return carla.Transform(loc, rot)


# ==========================================================
# Basis hypotheses
# ==========================================================

def basis_identity() -> List[List[float]]:
    return [[1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]]


def basis_ros_vehicle_to_carla_vehicle() -> List[List[float]]:
    # ROS: x forward, y left, z up
    # CARLA: x forward, y right, z up
    return [[1, 0, 0, 0],
            [0, -1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]]


def basis_optical_to_carla_sensor() -> List[List[float]]:
    # optical: x right, y down, z forward
    # carla sensor: x forward, y right, z up
    return [[0, 0, 1, 0],
            [1, 0, 0, 0],
            [0, -1, 0, 0],
            [0, 0, 0, 1]]


# ==========================================================
# Calibration loading
# ==========================================================

@dataclass
class CameraModel:
    name: str
    width: int
    height: int
    K_undist: List[List[float]]
    cTv: List[List[float]]


@dataclass
class LidarModel:
    name: str
    vTl: List[List[float]]


def load_calib(path: Path) -> Tuple[Dict[str, CameraModel], Dict[str, LidarModel]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cams: Dict[str, CameraModel] = {}
    for name, cfg in data.get("cameras", {}).items():
        w, h = cfg["image_size"]
        cams[name] = CameraModel(
            name=name,
            width=int(w),
            height=int(h),
            K_undist=cfg["K_undistortion"],
            cTv=cfg["cTv"],
        )
    lids: Dict[str, LidarModel] = {}
    for name, cfg in data.get("lidars", {}).items():
        lids[name] = LidarModel(name=name, vTl=cfg["vTl"])
    if not cams:
        raise RuntimeError("No cameras found in calib json.")
    return cams, lids


# ==========================================================
# CARLA helpers
# ==========================================================

def spawn_ego(world: carla.World, bp_filter: str, spawn_index: int) -> carla.Vehicle:
    lib = world.get_blueprint_library()
    bps = lib.filter(bp_filter)
    if not bps:
        raise RuntimeError(f"No vehicle blueprint matches: {bp_filter}")
    bp = bps[0]
    bp.set_attribute("role_name", "ego")
    spawns = world.get_map().get_spawn_points()
    if not spawns:
        raise RuntimeError("No spawn points.")
    spawn_index = max(0, min(spawn_index, len(spawns) - 1))
    ego = world.try_spawn_actor(bp, spawns[spawn_index])
    if not ego:
        raise RuntimeError("Failed to spawn ego.")
    return ego


def try_project_to_road(world: carla.World, loc: carla.Location) -> carla.Location:
    try:
        wpt = world.get_map().get_waypoint(loc, project_to_road=True, lane_type=carla.LaneType.Driving)
        if wpt:
            return carla.Location(x=wpt.transform.location.x, y=wpt.transform.location.y, z=wpt.transform.location.z)
    except Exception:
        pass
    return loc


def spawn_labeled_rig(world: carla.World, ego: carla.Actor,
                      radii=(5.0, 8.0, 12.0),
                      angles_deg=(0, 45, 90, 135, 180, -135, -90, -45),
                      heights=(0.2, 1.2),
                      life_time=90.0) -> Tuple[List[carla.Actor], List[dict]]:
    """
    Spawns props + draws debug string labels.
    Labels are the *reliable unique identifiers* visible in camera images.
    """
    lib = world.get_blueprint_library()
    # Robust list: some will fail depending on CARLA build; we fallback.
    prop_ids = [
        "static.prop.trafficcone01",
        "static.prop.streetbarrier",
        "static.prop.warningconstruction",
        "static.prop.constructioncone",
        "static.prop.garbage01",
        "static.prop.garbage02",
        "static.prop.shoppingcart",
        "static.prop.box01",
    ]
    prop_bps = [lib.find(pid) for pid in prop_ids if lib.find(pid) is not None]
    if not prop_bps:
        # worst-case: still draw labels without props
        prop_bps = []

    ego_tf = ego.get_transform()
    spawned: List[carla.Actor] = []
    manifest: List[dict] = []

    idx = 0
    for r in radii:
        for ang in angles_deg:
            a = math.radians(float(ang))
            # Ego local: x forward, y right in CARLA
            off = carla.Location(x=r * math.cos(a), y=r * math.sin(a), z=0.0)
            wloc = ego_tf.transform(off)
            wloc = try_project_to_road(world, wloc)

            for hz in heights:
                loc = carla.Location(x=wloc.x, y=wloc.y, z=wloc.z + hz)

                label = f"R{int(r)}_A{int(ang)}_H{int(hz * 10)}"
                # Draw label (this is the unique ID that shows up in images)
                try:
                    world.debug.draw_string(
                        loc,
                        label,
                        draw_shadow=False,
                        color=carla.Color(255, 0, 0),
                        life_time=life_time,
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

                manifest.append({
                    "label": label,
                    "radius_m": r,
                    "angle_deg": ang,
                    "height_m": hz,
                    "world_xyz": [loc.x, loc.y, loc.z],
                    "blueprint": bp_id,
                    "actor_id": actor_id,
                })

    print(f"🧱 Rig: spawned {len(spawned)} props + {len(manifest)} labels.")
    return spawned, manifest


def attach_camera(world: carla.World, ego: carla.Actor, cam: CameraModel, T_v_c: List[List[float]]) -> carla.Sensor:
    bp = world.get_blueprint_library().find("sensor.camera.rgb")
    bp.set_attribute("image_size_x", str(cam.width))
    bp.set_attribute("image_size_y", str(cam.height))
    # fov from fx
    fx = float(cam.K_undist[0][0])
    if fx > 1e-9:
        fov = 2.0 * math.degrees(math.atan(cam.width / (2.0 * fx)))
    else:
        fov = 90.0
    bp.set_attribute("fov", str(float(fov)))
    bp.set_attribute("sensor_tick", "0.0")
    tf = mat4_to_carla_transform(T_v_c)
    return world.spawn_actor(bp, tf, attach_to=ego)


def attach_lidar(world: carla.World, ego: carla.Actor, T_v_l: List[List[float]]) -> carla.Sensor:
    bp = world.get_blueprint_library().find("sensor.lidar.ray_cast")
    bp.set_attribute("range", "80")
    bp.set_attribute("rotation_frequency", "20")
    bp.set_attribute("channels", "64")
    bp.set_attribute("points_per_second", "200000")
    bp.set_attribute("upper_fov", "10")
    bp.set_attribute("lower_fov", "-30")
    bp.set_attribute("sensor_tick", "0.0")
    tf = mat4_to_carla_transform(T_v_l)
    return world.spawn_actor(bp, tf, attach_to=ego)


# ==========================================================
# Sweep definition
# ==========================================================

@dataclass(frozen=True)
class RunHypothesis:
    veh_basis_ros: bool
    cam_basis_optical: bool
    invert_extrinsic: bool
    yaw_deg: int
    roll_deg: int

    def tag(self) -> str:
        return f"vehROS{int(self.veh_basis_ros)}_camOPT{int(self.cam_basis_optical)}_inv{int(self.invert_extrinsic)}_yaw{self.yaw_deg}_roll{self.roll_deg}"


def build_sweep(full: bool) -> List[RunHypothesis]:
    veh_basis = [False, True]  # identity vs ROS->CARLA
    cam_basis = [False, True]  # identity vs optical->CARLA
    invs = [False, True]  # no-invert vs invert
    yaw_set = [0, 90, 180, 270]  # direction mistakes
    roll_set = [0, 180]  # upside-down mistakes

    runs = []
    for vb in veh_basis:
        for cb in cam_basis:
            for inv in invs:
                for yaw in yaw_set:
                    for roll in roll_set:
                        runs.append(RunHypothesis(vb, cb, inv, yaw, roll))

    # Hook for you: in "full" mode you could add pitch hypotheses too.
    # Keep default manageable.
    return runs


# ==========================================================
# Main
# ==========================================================

def main():
    ap = argparse.ArgumentParser(description="Sweep calibration conventions + orientation hypotheses")

    # Auto-detect calibration path relative to script location
    script_dir = Path(__file__).resolve().parent
    default_calib = script_dir / "calib_data.json"

    ap.add_argument("--calib", default=str(default_calib), help=f"Path to calib_data.json (default: {default_calib})")
    ap.add_argument("--out", default="calib_sweep_out", help="Output directory (default: calib_sweep_out)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--vehicle-bp", default="vehicle.tesla.model3")
    ap.add_argument("--spawn-index", type=int, default=0)
    ap.add_argument("--ticks", type=int, default=30)
    ap.add_argument("--sync", action="store_true", help="Enable synchronous mode for stable capture")
    ap.add_argument("--full", action="store_true", help="Use extended sweep (placeholder hook)")
    args = ap.parse_args()

    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    calib_path = Path(args.calib).resolve()
    if not calib_path.exists():
        print(f"Error: Calibration file not found at {calib_path}")
        return

    cams, lids = load_calib(calib_path)

    runs = build_sweep(full=args.full)
    print(f"🧪 Sweep runs: {len(runs)}")

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = client.get_world()

    old_settings = world.get_settings()
    touched = False

    all_cleanup: List[carla.Actor] = []
    rig_cleanup: List[carla.Actor] = []

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
        all_cleanup.append(ego)

        # Spawn rig once (labels persist long enough for all runs)
        rig_actors, rig_manifest = spawn_labeled_rig(world, ego)
        rig_cleanup.extend(rig_actors)
        all_cleanup.extend(rig_actors)

        (out_root / "rig_manifest.json").write_text(json.dumps(rig_manifest, indent=2), encoding="utf-8")

        for i, hyp in enumerate(runs, start=1):
            run_dir = out_root / f"run_{i:04d}__{hyp.tag()}"
            img_dir = run_dir / "images"
            img_dir.mkdir(parents=True, exist_ok=True)

            # Build bases
            Bv = basis_ros_vehicle_to_carla_vehicle() if hyp.veh_basis_ros else basis_identity()
            Bc = basis_optical_to_carla_sensor() if hyp.cam_basis_optical else basis_identity()

            # Post-rotation in sensor frame (catch wrong-looking cameras)
            R_post = mat4_mul(rot_z_deg(hyp.yaw_deg), rot_x_deg(hyp.roll_deg))

            sensors: List[carla.Actor] = []
            listening: List[carla.Sensor] = []
            latest_images: Dict[str, str] = {}

            def make_cb(cam_name: str):
                def _cb(image: carla.Image):
                    fp = img_dir / f"{cam_name}_{image.frame}.png"
                    image.save_to_disk(str(fp))
                    latest_images[cam_name] = str(fp)

                return _cb

            # Attach cameras
            for name, cam in cams.items():
                m = cam.cTv
                # Convert bases properly
                m2 = change_basis(m, Bv, Bc)
                if hyp.invert_extrinsic:
                    m2 = mat4_inv_rigid(m2)
                # Apply post-rotation to orientation hypothesis (keep translation)
                m3 = mat4_mul(m2, R_post)

                s = attach_camera(world, ego, cam, m3)
                s.listen(make_cb(name))
                listening.append(s)
                sensors.append(s)
                all_cleanup.append(s)

            # Attach lidars (optional; you can extend with lidar yaw/roll too)
            for lname, lid in lids.items():
                m = lid.vTl
                # assume lidar axes ~ vehicle axes; basis-change on both sides
                m2 = change_basis(m, Bv, Bv)
                # typically lidar->vehicle, we want vehicle->lidar:
                T_v_l = mat4_inv_rigid(m2)
                s = attach_lidar(world, ego, T_v_l)
                sensors.append(s)
                all_cleanup.append(s)

            print(f"[{i:04d}/{len(runs)}] {hyp.tag()}  sensors={len(sensors)}  capturing {args.ticks} ticks")
            for _ in range(args.ticks):
                world.tick()

            # Stop listeners (avoid unsubscribe warnings)
            for s in listening:
                try:
                    s.stop()
                except Exception:
                    pass

            # Save run configs + export
            run_cfg = {
                "hypothesis": {
                    "veh_basis_ros": hyp.veh_basis_ros,
                    "cam_basis_optical": hyp.cam_basis_optical,
                    "invert_extrinsic": hyp.invert_extrinsic,
                    "yaw_deg": hyp.yaw_deg,
                    "roll_deg": hyp.roll_deg,
                },
                "calib": str(calib_path),
                "ticks": args.ticks,
                "rig_manifest": "rig_manifest.json",
                "latest_images": latest_images,
            }
            (run_dir / "run_config.json").write_text(json.dumps(run_cfg, indent=2), encoding="utf-8")

            export = {"format": "carla_export_sweep_v1", "cameras": {}, "lidars": {}}
            for name, cam in cams.items():
                m = cam.cTv
                m2 = change_basis(m, Bv, Bc)
                if hyp.invert_extrinsic:
                    m2 = mat4_inv_rigid(m2)
                m3 = mat4_mul(m2, R_post)
                export["cameras"][name] = {
                    "image_size": [cam.width, cam.height],
                    "K_undistortion": cam.K_undist,
                    "T_vehicle_camera": m3,
                }
            for lname, lid in lids.items():
                m2 = change_basis(lid.vTl, Bv, Bv)
                export["lidars"][lname] = {
                    "T_vehicle_lidar": mat4_inv_rigid(m2),
                }
            (run_dir / "export_carla.json").write_text(json.dumps(export, indent=2), encoding="utf-8")

            # Mosaic (optional)
            try:
                from PIL import Image
                cam_names = sorted(latest_images.keys())
                imgs = [Image.open(latest_images[n]).convert("RGB") for n in cam_names if n in latest_images]
                if imgs:
                    cols = 3
                    rows = (len(imgs) + cols - 1) // cols
                    w = max(im.size[0] for im in imgs)
                    h = max(im.size[1] for im in imgs)
                    mosaic = Image.new("RGB", (cols * w, rows * h))
                    for k, im in enumerate(imgs):
                        r = k // cols
                        c = k % cols
                        mosaic.paste(im, (c * w, r * h))
                    mosaic.save(run_dir / "mosaic.png")
            except Exception:
                pass

            # Destroy sensors for next run (ego + rig stay)
            for a in sensors:
                try:
                    a.destroy()
                except Exception:
                    pass

        print(f"✅ Sweep complete. Output → {out_root}")

    finally:
        # Clean up ego + rig
        for a in reversed(all_cleanup):
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