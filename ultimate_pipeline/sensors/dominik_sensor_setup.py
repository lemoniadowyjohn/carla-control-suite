#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ultimate_pipeline/sensors/dominik_sensor_setup.py

DominikSensorSetup (thesis-rig compliant, version-tolerant)

What this module guarantees
- Reads `calib_data.json` (cameras + lidars).
- Cameras:
    * uses K_undistortion only (pinhole); ignores K and D
    * uses `cTv` (vehicle -> camera) to compute the camera pose on the vehicle
    * optional OpenCV/optical-axis conversion (default ON)
- LiDARs:
    * uses `vTl` (lidar -> vehicle) directly (no inversion)
- Optional vehicle-Y flip (robotics +Y left -> CARLA +Y right), default ON.

Stable API used across the codebase:
  - DominikSensorSetup(calib_path, flip_vehicle_y=True, opencv_camera_axes=True, verbose=False)
  - .cameras / .lidars (raw dicts from JSON)
  - setup_camera(), setup_lidar(), setup_all_sensors()
  - get_camera_transform(), get_lidar_transform()

Calibration semantics (as you specified)
- Cameras:
    * `cTv` gives the transform from Vehicle -> Camera.
      We invert it to obtain Camera -> Vehicle (sensor -> vehicle), which is the pose we need.
- LiDAR:
    * `vTl` gives the transform from LiDAR -> Vehicle (sensor -> vehicle). Use directly.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import os
from typing import Any, Dict, Optional, Tuple

import numpy as np

try:
    import carla
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        "CARLA Python API not found. Ensure the CARLA egg is on PYTHONPATH."
    ) from e


# -----------------------------
# Math helpers
# -----------------------------

_VEHICLE_Y_FLIP = np.diag([1.0, -1.0, 1.0]).astype(float)


# ROS sensor axes -> CARLA sensor axes (x forward, y left, z up) -> (x forward, y right, z up)
_ROS_AXES_RIGHT = np.diag([1.0, -1.0, 1.0]).astype(float)
# Optical(OpenCV) -> CARLA sensor axes
# cv: x right, y down, z forward
# carla sensor: x forward, y right, z up
_OPENCV_CAM_TO_CARLA = np.array(
    [
        [0.0, 0.0, 1.0],   # carla_x = cv_z
        [1.0, 0.0, 0.0],   # carla_y = cv_x
        [0.0, -1.0, 0.0],  # carla_z = -cv_y
    ],
    dtype=float,
)
_CARLA_TO_OPENCV = _OPENCV_CAM_TO_CARLA.T  # cv = CARLA_TO_OPENCV * carla


def _ensure_matrix4(m: Any, name: str) -> np.ndarray:
    arr = np.asarray(m, dtype=float)
    if arr.shape != (4, 4):
        raise ValueError(f"{name} must be 4x4, got shape={arr.shape}")
    return arr


def _inv_T(T: np.ndarray) -> np.ndarray:
    R = T[:3, :3]
    t = T[:3, 3]
    Ti = np.eye(4, dtype=float)
    Ti[:3, :3] = R.T
    Ti[:3, 3] = -R.T @ t
    return Ti


def _rotmat_to_rpy_deg(R: np.ndarray) -> Tuple[float, float, float]:
    """Extract roll/pitch/yaw in degrees from rotation matrix (ZYX)."""
    yaw = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    pitch = math.degrees(math.atan2(-R[2, 0], math.sqrt(R[2, 1] ** 2 + R[2, 2] ** 2)))
    roll = math.degrees(math.atan2(R[2, 1], R[2, 2]))
    return float(roll), float(pitch), float(yaw)


def _fov_from_K_undist(K_undist: Any, width_px: int) -> float:
    K = np.asarray(K_undist, dtype=float)
    fx = float(K[0, 0])
    if fx <= 1e-9:
        return 90.0
    return float(2.0 * math.degrees(math.atan(width_px / (2.0 * fx))))


def _tf_from_sensor_to_vehicle(
    T_sensor_to_vehicle: np.ndarray,
    *,
    flip_vehicle_y: bool,
    opencv_camera_axes: bool,
    sensor_axes_right: np.ndarray | None = None,
) -> carla.Transform:
    """Convert 4x4 (sensor->vehicle) to a CARLA Transform (pose relative vehicle)."""
    R_v_s = T_sensor_to_vehicle[:3, :3].astype(float)
    t_v_s = T_sensor_to_vehicle[:3, 3].astype(float)

    if flip_vehicle_y:
        t_v_s = _VEHICLE_Y_FLIP @ t_v_s
        R_v_s = _VEHICLE_Y_FLIP @ R_v_s

    if opencv_camera_axes:
        # We currently have R_vehicle_from_optical; want R_vehicle_from_carlaSensor:
        # R_v_carla = R_v_optical * R_optical_from_carla
        R_v_s = R_v_s @ _CARLA_TO_OPENCV


    if sensor_axes_right is not None:
        R_v_s = R_v_s @ sensor_axes_right
    roll, pitch, yaw = _rotmat_to_rpy_deg(R_v_s)
    loc = carla.Location(x=float(t_v_s[0]), y=float(t_v_s[1]), z=float(t_v_s[2]))
    rot = carla.Rotation(roll=roll, pitch=pitch, yaw=yaw)
    return carla.Transform(loc, rot)


class DominikSensorSetup:
    def __init__(
        self,
        calib_json_path: str,
        *,
        flip_vehicle_y: bool = True,
        opencv_camera_axes: bool = True,
        lidar_axes_mode: str = "auto",
        verbose: bool = False,
    ):
        self.calib_path = Path(calib_json_path)
        if not self.calib_path.exists():
            raise FileNotFoundError(f"Calibration JSON not found: {self.calib_path}")

        self.flip_vehicle_y = bool(flip_vehicle_y)
        self.opencv_camera_axes = bool(opencv_camera_axes)
        self.lidar_axes_mode = str(lidar_axes_mode).strip().lower()
        self.verbose = bool(verbose)

        with self.calib_path.open("r", encoding="utf-8") as f:
            self.data = json.load(f)

        # Raw dicts (stable API used by recorder.py)
        self.cameras: Dict[str, Dict[str, Any]] = dict(self.data.get("cameras", {}) or {})
        self.lidars: Dict[str, Dict[str, Any]] = dict(self.data.get("lidars", {}) or {})

        if self.verbose:
            print(f"📐 Loaded calibration: {self.calib_path}")
            print(f"   cameras={len(self.cameras)} lidars={len(self.lidars)}")
            print(f"   flip_vehicle_y={self.flip_vehicle_y} opencv_camera_axes={self.opencv_camera_axes}")


    # -----------------------------
    # Backwards-compat helpers
    # -----------------------------

    def load(self) -> "DominikSensorSetup":
        """Legacy no-op; older generators call setup.load()."""
        return self

    def camera_names(self) -> list[str]:
        return sorted(self.cameras.keys())

    def lidar_names(self) -> list[str]:
        return sorted(self.lidars.keys())

    def get_camera_size(self, camera_name: str) -> tuple[int, int]:
        cfg = self.cameras[camera_name]
        return int(cfg["image_size"][0]), int(cfg["image_size"][1])

    def get_camera_fov(self, camera_name: str) -> float:
        w, _ = self.get_camera_size(camera_name)
        cfg = self.cameras[camera_name]
        return _fov_from_K_undist(cfg["K_undistortion"], w)

    def get_camera_transform_vehicle_to_sensor(self, camera_name: str) -> carla.Transform:
        """Legacy name used by older dataset generators."""
        return self.get_camera_transform(camera_name)

    def get_lidar_transform_vehicle_to_sensor(self, lidar_name: str) -> carla.Transform:
        return self.get_lidar_transform(lidar_name)

    # -----------------------------
    # Pose getters
    # -----------------------------

    def get_camera_transform(self, camera_name: str) -> carla.Transform:
        cfg = self.cameras[camera_name]
        cTv = _ensure_matrix4(cfg["cTv"], f"{camera_name}.cTv")  # vehicle -> camera
        vTc = _inv_T(cTv)  # camera -> vehicle  (sensor -> vehicle)
        return _tf_from_sensor_to_vehicle(
            vTc,
            flip_vehicle_y=self.flip_vehicle_y,
            opencv_camera_axes=self.opencv_camera_axes,
        )

    def get_lidar_transform(self, lidar_name: str) -> carla.Transform:
        cfg = self.lidars[lidar_name]
        vTl = _ensure_matrix4(cfg["vTl"], f"{lidar_name}.vTl")  # lidar -> vehicle

        # Real-vehicle LiDAR calibrations are often given in a ROS-like sensor frame
        # (x forward, y left, z up). CARLA expects (x forward, y right, z up).
        # If your `vTl` was computed with ROS LiDAR axes, set lidar_axes_mode="ros".
        sensor_axes_right = None
        if self.lidar_axes_mode in ("ros", "ros2", "ros-like", "ros_like"):
            sensor_axes_right = _ROS_AXES_RIGHT
        elif self.lidar_axes_mode in ("carla", "unreal", "native", "auto"):
            sensor_axes_right = None

        return _tf_from_sensor_to_vehicle(
            vTl,
            flip_vehicle_y=self.flip_vehicle_y,
            opencv_camera_axes=False,
            sensor_axes_right=sensor_axes_right,
        )

    # -----------------------------
    # Spawners
    # -----------------------------

    def setup_camera(
        self,
        world: carla.World,
        ego: carla.Actor,
        camera_name: str,
        *,
        sensor_type: str = "rgb",
        attach_rigid: bool = True,
    ) -> carla.Actor:
        """Spawn one calibrated camera."""
        cfg = self.cameras[camera_name]
        width, height = int(cfg["image_size"][0]), int(cfg["image_size"][1])
        # Low-VRAM / debugging support: downscale camera render size without changing optics.
        # (FOV is computed from the *original* calibration; resolution can be reduced independently.)
        cam_scale = float(os.getenv("UP_CAMERA_SCALE", "1.0"))
        if cam_scale != 1.0:
            width = max(64, int(round(width * cam_scale)))
            height = max(64, int(round(height * cam_scale)))
        fov = _fov_from_K_undist(cfg["K_undistortion"], int(cfg["image_size"][0]))

        bp_lib = world.get_blueprint_library()
        bp_id = {
            "rgb": "sensor.camera.rgb",
            "seg": "sensor.camera.semantic_segmentation",
            "depth": "sensor.camera.depth",
        }.get(sensor_type, sensor_type)

        bp = bp_lib.find(bp_id)
        if bp is None:
            raise RuntimeError(f"CARLA blueprint missing: {bp_id}")

        if bp.has_attribute("image_size_x"):
            bp.set_attribute("image_size_x", str(width))
        if bp.has_attribute("image_size_y"):
            bp.set_attribute("image_size_y", str(height))
        if bp.has_attribute("fov"):
            bp.set_attribute("fov", str(float(fov)))
        if bp.has_attribute("sensor_tick"):
            # 0.0 = every tick. Use UP_SENSOR_TICK (e.g., 0.05 for 20Hz) to reduce load.
            bp.set_attribute("sensor_tick", os.getenv("UP_SENSOR_TICK", "0.0"))

        tf = self.get_camera_transform(camera_name)
        attachment_type = carla.AttachmentType.Rigid if attach_rigid else carla.AttachmentType.SpringArm

        actor = world.spawn_actor(bp, tf, attach_to=ego, attachment_type=attachment_type)

        if self.verbose:
            loc, rot = tf.location, tf.rotation
            print(
                f"📷 {sensor_type}:{camera_name} {width}x{height} fov={fov:.2f} "
                f"pos=({loc.x:.2f},{loc.y:.2f},{loc.z:.2f}) rpy=({rot.roll:.1f},{rot.pitch:.1f},{rot.yaw:.1f})"
            )
        return actor

    def setup_lidar(
        self,
        world: carla.World,
        ego: carla.Actor,
        lidar_name: str,
        *,
        attach_rigid: bool = True,
        defaults: Optional[Dict[str, str]] = None,
    ) -> carla.Actor:
        """Spawn one calibrated LiDAR."""
        bp_lib = world.get_blueprint_library()
        bp = bp_lib.find("sensor.lidar.ray_cast")
        if bp is None:
            raise RuntimeError("CARLA blueprint missing: sensor.lidar.ray_cast")

        # Reasonable defaults (override via defaults dict)
        d = {
            "range": "80",
            "rotation_frequency": "20",
            "channels": "64",
            "points_per_second": "200000",
            "upper_fov": "10",
            "lower_fov": "-30",
            "sensor_tick": "0.0",
        }
        if defaults:
            d.update({str(k): str(v) for k, v in defaults.items()})

        for k, v in d.items():
            if bp.has_attribute(k):
                bp.set_attribute(k, v)

        tf = self.get_lidar_transform(lidar_name)
        attachment_type = carla.AttachmentType.Rigid if attach_rigid else carla.AttachmentType.SpringArm
        actor = world.spawn_actor(bp, tf, attach_to=ego, attachment_type=attachment_type)

        if self.verbose:
            loc, rot = tf.location, tf.rotation
            print(
                f"📡 lidar:{lidar_name} pos=({loc.x:.2f},{loc.y:.2f},{loc.z:.2f}) "
                f"rpy=({rot.roll:.1f},{rot.pitch:.1f},{rot.yaw:.1f})"
            )
        return actor

    def setup_all_sensors(
        self,
        world: carla.World,
        ego: carla.Actor,
        *,
        add_segmentation: bool = False,
        add_depth: bool = False,
        include_lidars: bool = True,
        attach_rigid: bool = True,
    ) -> Dict[str, carla.Actor]:
        """Spawn all calibrated RGB cameras + LiDARs. Optionally add seg/depth mirrors."""
        out: Dict[str, carla.Actor] = {}

        # Optional camera whitelist to reduce VRAM (comma-separated names).
        whitelist = [c.strip() for c in os.getenv('UP_CAMERA_WHITELIST', '').split(',') if c.strip()]
        cam_names = sorted(self.cameras.keys())
        if whitelist:
            cam_names = [c for c in cam_names if c in whitelist]
            if self.verbose:
                print(f'📷 Camera whitelist active: {cam_names}')

        for cam_name in cam_names:
            out[cam_name] = self.setup_camera(world, ego, cam_name, sensor_type="rgb", attach_rigid=attach_rigid)
            if add_segmentation:
                out[f"seg_{cam_name}"] = self.setup_camera(world, ego, cam_name, sensor_type="seg", attach_rigid=attach_rigid)
            if add_depth:
                out[f"depth_{cam_name}"] = self.setup_camera(world, ego, cam_name, sensor_type="depth", attach_rigid=attach_rigid)

        include_lidars = bool(include_lidars) and (os.getenv('UP_INCLUDE_LIDARS', '1') != '0')
        if include_lidars:
            for lid_name in sorted(self.lidars.keys()):
                out[lid_name] = self.setup_lidar(world, ego, lid_name, attach_rigid=attach_rigid)

        return out

# -----------------------------------------------------------------------------
# Backward/forward compatibility alias
# -----------------------------------------------------------------------------
if 'DominikSensorSetup' not in globals():
    # In case the class was renamed in a local experiment, try common alternatives.
    _alt = globals().get('DominikSensorSetupFixed') or globals().get('DominikSensorRig')
    if _alt is not None:
        DominikSensorSetup = _alt  # type: ignore
