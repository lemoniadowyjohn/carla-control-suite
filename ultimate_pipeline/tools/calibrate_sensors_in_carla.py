#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Calibration smoke-test + CARLA export tool

WHAT THIS IS:
- Robust integration + verification tool.
- It does NOT optimize calibration (no reprojection minimization).
- It selects the most plausible convention / basis mapping and exports CARLA-ready T_vehicle_sensor.

MAIN FIXES VS YOUR VERSION:
- Proper change-of-basis: T' = B_parent * T * inv(B_child)
- Adds OpenCV optical -> CARLA sensor basis conversion (critical).
- Chooses ONE global convention across cameras.
- Better marker spawning: multi-radius ring + many angles, tries to project to road.
- Avoids stop() on sensors that never listened (silences warnings).
"""

import argparse
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, Optional, List

import carla


# ==========================================================
# Math helpers (no numpy)
# ==========================================================

def mat4_mul(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    out = [[0.0] * 4 for _ in range(4)]
    for r in range(4):
        for c in range(4):
            out[r][c] = sum(a[r][k] * b[k][c] for k in range(4))
    return out

def mat4_inv(m: List[List[float]]) -> List[List[float]]:
    # Invert a rigid transform (R,t; 0,1) assuming last row [0,0,0,1]
    R = [[m[r][c] for c in range(3)] for r in range(3)]
    t = [m[r][3] for r in range(3)]
    Rt = [[R[c][r] for c in range(3)] for r in range(3)]  # R^T
    tinv = [
        -(Rt[0][0]*t[0] + Rt[0][1]*t[1] + Rt[0][2]*t[2]),
        -(Rt[1][0]*t[0] + Rt[1][1]*t[1] + Rt[1][2]*t[2]),
        -(Rt[2][0]*t[0] + Rt[2][1]*t[1] + Rt[2][2]*t[2]),
    ]
    out = [[0.0]*4 for _ in range(4)]
    for r in range(3):
        for c in range(3):
            out[r][c] = Rt[r][c]
        out[r][3] = tinv[r]
    out[3][3] = 1.0
    return out

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def rotmat_to_euler_zyx_degrees(R: List[List[float]]) -> Tuple[float, float, float]:
    # Returns (roll_deg, pitch_deg, yaw_deg) from ZYX matrix.
    sp = clamp(-R[2][0], -1.0, 1.0)
    pitch = math.asin(sp)
    if abs(sp) > 0.9999:
        yaw = math.atan2(-R[0][1], R[1][1])
        roll = 0.0
    else:
        yaw = math.atan2(R[1][0], R[0][0])
        roll = math.atan2(R[2][1], R[2][2])
    return (math.degrees(roll), math.degrees(pitch), math.degrees(yaw))

def mat4_to_carla_transform(m: List[List[float]]) -> carla.Transform:
    R = [[m[r][c] for c in range(3)] for r in range(3)]
    roll, pitch, yaw = rotmat_to_euler_zyx_degrees(R)
    loc = carla.Location(x=m[0][3], y=m[1][3], z=m[2][3])
    rot = carla.Rotation(roll=roll, pitch=pitch, yaw=yaw)
    return carla.Transform(loc, rot)

def build_K_from_fx_fy_cx_cy(fx: float, fy: float, cx: float, cy: float) -> List[List[float]]:
    return [[fx, 0.0, cx],
            [0.0, fy, cy],
            [0.0, 0.0, 1.0]]

def project_point(K: List[List[float]], p_cam: Tuple[float, float, float]) -> Optional[Tuple[float, float]]:
    x, y, z = p_cam
    if z <= 0.05:
        return None
    u = (K[0][0] * x / z) + K[0][2]
    v = (K[1][1] * y / z) + K[1][2]
    return (u, v)

def tf_to_mat4(tf: carla.Transform) -> List[List[float]]:
    # Build R from yaw/pitch/roll (degrees), ZYX order
    roll = math.radians(tf.rotation.roll)
    pitch = math.radians(tf.rotation.pitch)
    yaw = math.radians(tf.rotation.yaw)

    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)

    Rz = [[cy, -sy, 0],
          [sy,  cy, 0],
          [0,    0, 1]]
    Ry = [[cp, 0, sp],
          [0,  1, 0],
          [-sp,0, cp]]
    Rx = [[1, 0, 0],
          [0, cr,-sr],
          [0, sr, cr]]

    def mul3(A, B):
        return [[sum(A[r][k]*B[k][c] for k in range(3)) for c in range(3)] for r in range(3)]

    R = mul3(mul3(Rz, Ry), Rx)

    M = [[0.0]*4 for _ in range(4)]
    for r in range(3):
        for c in range(3):
            M[r][c] = R[r][c]
    M[0][3] = tf.location.x
    M[1][3] = tf.location.y
    M[2][3] = tf.location.z
    M[3][3] = 1.0
    return M


# ==========================================================
# Basis / convention transforms (THE IMPORTANT PART)
# ==========================================================

def basis_ros_vehicle_to_carla_vehicle() -> List[List[float]]:
    # ROS vehicle: x forward, y left, z up
    # CARLA vehicle: x forward, y right, z up
    # => flip Y
    return [
        [1, 0, 0, 0],
        [0,-1, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ]

def basis_optical_to_carla_sensor() -> List[List[float]]:
    """
    OpenCV optical frame:
      x right, y down, z forward
    CARLA/Unreal sensor frame:
      x forward, y right, z up

    Mapping:
      carla_x = optical_z
      carla_y = optical_x
      carla_z = -optical_y
    """
    return [
        [0, 0, 1, 0],
        [1, 0, 0, 0],
        [0,-1, 0, 0],
        [0, 0, 0, 1],
    ]

def mat4_rot_transpose_only(m: List[List[float]]) -> List[List[float]]:
    # For pure basis rotations: inv = transpose (no translation)
    out = [[0.0]*4 for _ in range(4)]
    for r in range(3):
        for c in range(3):
            out[r][c] = m[c][r]
    out[3][3] = 1.0
    return out

def change_basis(T_parent_from_child: List[List[float]],
                 B_parent_old_to_new: List[List[float]],
                 B_child_old_to_new: List[List[float]]) -> List[List[float]]:
    """
    Correct change-of-basis:
      T_new = B_parent * T_old * inv(B_child)
    """
    Bc_inv = mat4_rot_transpose_only(B_child_old_to_new)
    return mat4_mul(mat4_mul(B_parent_old_to_new, T_parent_from_child), Bc_inv)


# ==========================================================
# Calibration parsing
# ==========================================================

@dataclass
class CameraModel:
    name: str
    width: int
    height: int
    K_undist: List[List[float]]
    cTv: List[List[float]]  # as stored (Dominik format)

@dataclass
class LidarModel:
    name: str
    vTl: List[List[float]]  # as stored

def load_calib(calib_path: Path) -> Tuple[Dict[str, CameraModel], Dict[str, LidarModel]]:
    with calib_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

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
        raise RuntimeError("No cameras found in calib.json")
    if not lids:
        print("⚠ No lidars found in calib.json (continuing with cameras only).")

    return cams, lids


# ==========================================================
# CARLA helpers
# ==========================================================

def spawn_ego(world: carla.World, bp_filter: str = "vehicle.tesla.model3", spawn_index: int = 0) -> carla.Vehicle:
    bps = world.get_blueprint_library().filter(bp_filter)
    if not bps:
        raise RuntimeError(f"No vehicle blueprint matches: {bp_filter}")
    bp = bps[0]
    bp.set_attribute("role_name", "ego")

    spawns = world.get_map().get_spawn_points()
    if not spawns:
        raise RuntimeError("No spawn points on this map.")
    spawn_index = max(0, min(spawn_index, len(spawns) - 1))

    ego = world.try_spawn_actor(bp, spawns[spawn_index])
    if not ego:
        raise RuntimeError("Failed to spawn ego.")
    return ego

def _try_project_to_road(world: carla.World, loc: carla.Location) -> carla.Location:
    """
    Best-effort: project a location to the nearest driving lane waypoint, and use its Z.
    If projection fails, keep original Z.
    """
    try:
        wpt = world.get_map().get_waypoint(loc, project_to_road=True, lane_type=carla.LaneType.Driving)
        if wpt is not None:
            out = carla.Location(x=wpt.transform.location.x, y=wpt.transform.location.y, z=wpt.transform.location.z)
            return out
    except Exception:
        pass
    return loc

def spawn_markers_ring(world: carla.World, ego: carla.Actor) -> List[carla.Actor]:
    """
    Marker setup that actually catches calibration mistakes:

    - Multiple radii: 5m / 8m / 12m
    - Many angles: every 30° around the car (front/right/back/left + diagonals)
    - Two heights: ground-ish (z+0.2) and slightly higher (z+1.2) to stress pitch/roll
    - Project to road where possible so markers don't float/sink

    This produces “constraints” for front/side/rear cameras simultaneously.
    """
    lib = world.get_blueprint_library()

    # Use larger, highly visible props if available
    candidates = [
        "static.prop.streetbarrier",
        "static.prop.warningconstruction",
        "static.prop.trafficcone01",
        "static.prop.constructioncone",
    ]
    bps = []
    for cid in candidates:
        bp = lib.find(cid)
        if bp is not None:
            bps.append(bp)

    if not bps:
        print("⚠ No marker prop blueprints found; skipping marker spawn.")
        return []

    ego_tf = ego.get_transform()

    radii = [5.0, 8.0, 12.0]
    angles_deg = [0, 30, 60, 90, 120, 150, 180, -150, -120, -90, -60, -30]
    heights = [0.2, 1.2]  # low + mid height (helps detect roll/pitch bugs)

    actors: List[carla.Actor] = []

    idx = 0
    for r in radii:
        for ang in angles_deg:
            a = math.radians(ang)
            # Ego local frame: x forward, y right in CARLA
            off = carla.Location(x=r * math.cos(a), y=r * math.sin(a), z=0.0)

            wloc = ego_tf.transform(off)
            wloc = _try_project_to_road(world, wloc)

            for hz in heights:
                wloc2 = carla.Location(x=wloc.x, y=wloc.y, z=wloc.z + hz)
                tf = carla.Transform(wloc2, carla.Rotation(yaw=ego_tf.rotation.yaw))
                bp = bps[idx % len(bps)]
                idx += 1
                a_spawned = world.try_spawn_actor(bp, tf)
                if a_spawned:
                    actors.append(a_spawned)

    print(f"🧱 Spawned {len(actors)} markers around ego (multi-radius/angles).")
    return actors


# ==========================================================
# Convention testing (auto convention selection, not real calibration)
# ==========================================================

@dataclass
class Convention:
    name: str
    invert_extrinsic: bool  # invert stored matrix before using

def score_camera(
    cam: CameraModel,
    T_vehicle_camera: List[List[float]],
    marker_world_points: List[carla.Location],
    ego_tf: carla.Transform,
) -> int:
    """
    Score = number of marker centers that project inside image bounds.
    This is a *coarse* validity check, but it becomes useful when markers are many + well distributed.
    """
    # Build camera world transform: T_w_c = T_w_v * T_v_c
    T_w_v = tf_to_mat4(ego_tf)
    T_w_c = mat4_mul(T_w_v, T_vehicle_camera)
    T_c_w = mat4_inv(T_w_c)

    fx = float(cam.K_undist[0][0])
    fy = float(cam.K_undist[1][1])
    cx = float(cam.K_undist[0][2])
    cy = float(cam.K_undist[1][2])
    K = build_K_from_fx_fy_cx_cy(fx, fy, cx, cy)

    score = 0
    for pw in marker_world_points:
        xw, yw, zw = pw.x, pw.y, pw.z
        xc = T_c_w[0][0]*xw + T_c_w[0][1]*yw + T_c_w[0][2]*zw + T_c_w[0][3]
        yc = T_c_w[1][0]*xw + T_c_w[1][1]*yw + T_c_w[1][2]*zw + T_c_w[1][3]
        zc = T_c_w[2][0]*xw + T_c_w[2][1]*yw + T_c_w[2][2]*zw + T_c_w[2][3]
        uv = project_point(K, (xc, yc, zc))
        if uv is None:
            continue
        u, v = uv
        if 0 <= u < cam.width and 0 <= v < cam.height:
            score += 1
    return score


# ==========================================================
# Sensor attachment
# ==========================================================

def attach_camera(world: carla.World, ego: carla.Actor, cam: CameraModel, T_v_c: List[List[float]]) -> carla.Sensor:
    bp = world.get_blueprint_library().find("sensor.camera.rgb")
    bp.set_attribute("image_size_x", str(cam.width))
    bp.set_attribute("image_size_y", str(cam.height))

    fx = float(cam.K_undist[0][0])
    fov = 2.0 * math.degrees(math.atan(cam.width / (2.0 * fx)))
    bp.set_attribute("fov", str(fov))

    tf = mat4_to_carla_transform(T_v_c)
    sensor = world.spawn_actor(bp, tf, attach_to=ego)
    return sensor

def attach_lidar(world: carla.World, ego: carla.Actor, T_v_l: List[List[float]]) -> carla.Sensor:
    bp = world.get_blueprint_library().find("sensor.lidar.ray_cast")
    bp.set_attribute("channels", "32")
    bp.set_attribute("points_per_second", "56000")
    bp.set_attribute("rotation_frequency", "10")
    bp.set_attribute("range", "60")
    bp.set_attribute("upper_fov", "10")
    bp.set_attribute("lower_fov", "-30")

    tf = mat4_to_carla_transform(T_v_l)
    sensor = world.spawn_actor(bp, tf, attach_to=ego)
    return sensor


# ==========================================================
# Main
# ==========================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", required=True, help="Path to calib_data.json")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--vehicle-bp", default="vehicle.tesla.model3")
    ap.add_argument("--spawn-index", type=int, default=0)
    ap.add_argument("--ticks", type=int, default=40)
    ap.add_argument("--output", default="calib_test_out")
    ap.add_argument("--sync", action="store_true", help="Temporarily enable synchronous mode for stable tick capture")
    args = ap.parse_args()

    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    calib_path = Path(args.calib).resolve()
    cams, lids = load_calib(calib_path)

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = client.get_world()

    actor_cleanup: List[carla.Actor] = []
    listening_sensors: List[carla.Sensor] = []

    # Save/restore world settings if we touch them
    old_settings = world.get_settings()
    touched_settings = False

    try:
        if args.sync and not old_settings.synchronous_mode:
            new_settings = carla.WorldSettings(
                no_rendering_mode=old_settings.no_rendering_mode,
                synchronous_mode=True,
                fixed_delta_seconds=old_settings.fixed_delta_seconds or 0.05,
                max_substep_delta_time=old_settings.max_substep_delta_time,
                max_substeps=old_settings.max_substeps
            )
            world.apply_settings(new_settings)
            touched_settings = True
            # let it settle
            world.tick()

        ego = spawn_ego(world, args.vehicle_bp, args.spawn_index)
        actor_cleanup.append(ego)

        markers = spawn_markers_ring(world, ego)
        actor_cleanup.extend(markers)

        # Use marker centers in world frame
        marker_points: List[carla.Location] = []
        for a in markers:
            try:
                bb = a.bounding_box
                center_world = a.get_transform().transform(bb.location)
                marker_points.append(center_world)
            except Exception:
                marker_points.append(a.get_transform().location)

        ego_tf = ego.get_transform()

        # Candidate: only ambiguity left is whether stored matrix needs inversion.
        conventions = [
            Convention("stored as vehicle->sensor (no invert)", invert_extrinsic=False),
            Convention("stored as sensor->vehicle (invert)",    invert_extrinsic=True),
        ]

        # Basis conversions (assumption: vehicle frame is ROS-ish, camera is optical)
        Bv = basis_ros_vehicle_to_carla_vehicle()
        Bc = basis_optical_to_carla_sensor()

        # Choose ONE convention globally (sum over cameras)
        best_conv = conventions[0]
        best_sum = -1

        for conv in conventions:
            total = 0
            for _, cam in cams.items():
                m = cam.cTv

                # Convert stored to CARLA-consistent basis
                # m is "camera<->vehicle" but in ROS vehicle basis + optical camera basis
                m2 = change_basis(m, Bv, Bc)

                # If stored direction is opposite, invert
                if conv.invert_extrinsic:
                    m2 = mat4_inv(m2)

                # Now interpret as T_vehicle_camera (vehicle -> camera) ? or camera -> vehicle ?
                # We want vehicle->camera for CARLA attachment. If your stored is camera->vehicle,
                # inversion above makes it vehicle->camera.
                T_v_c = m2

                total += score_camera(cam, T_v_c, marker_points, ego_tf) if marker_points else 0

            if total > best_sum:
                best_sum = total
                best_conv = conv

        # Build final T_vehicle_camera per camera
        T_vehicle_camera: Dict[str, List[List[float]]] = {}
        for name, cam in cams.items():
            m = cam.cTv
            m2 = change_basis(m, Bv, Bc)
            if best_conv.invert_extrinsic:
                m2 = mat4_inv(m2)
            T_vehicle_camera[name] = m2

            # Debug print: euler sanity
            R = [[m2[r][c] for c in range(3)] for r in range(3)]
            roll, pitch, yaw = rotmat_to_euler_zyx_degrees(R)
            print(f"📷 {name}: convention={best_conv.name} score_sum={best_sum} "
                  f"t=({m2[0][3]:.2f},{m2[1][3]:.2f},{m2[2][3]:.2f}) "
                  f"rpy=({roll:.1f},{pitch:.1f},{yaw:.1f})")

        # LiDAR: you likely have a different basis than optical camera.
        # Here we assume vTl is ROS vehicle basis and lidar axes match ROS sensor basis (common).
        # We only apply vehicle basis flip (ROS->CARLA), and optionally invert direction.
        T_vehicle_lidar: Dict[str, List[List[float]]] = {}
        for lname, lid in lids.items():
            m = lid.vTl
            # Change basis for parent (vehicle) only; assume lidar child basis is already "sensor-like" with x forward.
            # If your lidar is also in ROS sensor axes (x forward, y left, z up), then child basis == parent basis.
            # So we use the same Bv for both.
            m2 = change_basis(m, Bv, Bv)

            # Many files store lidar->vehicle; for CARLA attach we want vehicle->lidar
            T_vehicle_lidar[lname] = mat4_inv(m2)
            print(f"📡 {lname}: using basis ROS->CARLA + invert(vTl) to get vehicle->lidar")

        # Attach sensors + capture
        latest_images: Dict[str, str] = {}
        sensors: List[carla.Actor] = []

        def make_cam_callback(cam_name: str):
            def _cb(image: carla.Image):
                fp = out_dir / f"{cam_name}_{image.frame}.png"
                image.save_to_disk(str(fp))
                latest_images[cam_name] = str(fp)
            return _cb

        for name, cam in cams.items():
            s = attach_camera(world, ego, cam, T_vehicle_camera[name])
            s.listen(make_cam_callback(name))
            listening_sensors.append(s)
            sensors.append(s)
            actor_cleanup.append(s)

        # Lidar: attach, but do NOT listen (unless you want data)
        for lname in T_vehicle_lidar.keys():
            s = attach_lidar(world, ego, T_vehicle_lidar[lname])
            sensors.append(s)
            actor_cleanup.append(s)

        print(f"✅ Attached {len(sensors)} sensors. Capturing {args.ticks} ticks...")

        for _ in range(args.ticks):
            world.tick()

        # Mosaic
        try:
            from PIL import Image
            cam_names = sorted(latest_images.keys())
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

        # Export
        export = {
            "format": "carla_export_v1",
            "source_calib": str(calib_path),
            "global_selected_convention": best_conv.name,
            "cameras": {},
            "lidars": {},
        }

        for name, cam in cams.items():
            export["cameras"][name] = {
                "image_size": [cam.width, cam.height],
                "K_undistortion": cam.K_undist,
                "T_vehicle_camera": T_vehicle_camera[name],
            }

        for lname, mat in T_vehicle_lidar.items():
            export["lidars"][lname] = {
                "T_vehicle_lidar": mat,
                "note": "computed as vehicle->lidar = inverse(change_basis(vTl, Bv, Bv))",
            }

        export_path = out_dir / "calib_carla_export.json"
        export_path.write_text(json.dumps(export, indent=2), encoding="utf-8")
        print(f"🧾 CARLA export written → {export_path}")
        print("🎉 Calibration integration test complete.")

    finally:
        # Stop only sensors that listened (prevents those unsubscribe warnings)
        for s in listening_sensors:
            try:
                s.stop()
            except Exception:
                pass

        for a in reversed(actor_cleanup):
            try:
                a.destroy()
            except Exception:
                pass

        if touched_settings:
            try:
                world.apply_settings(old_settings)
            except Exception:
                pass


if __name__ == "__main__":
    main()
