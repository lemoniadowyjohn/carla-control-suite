#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SensorVisualizer (FIXED + compatible)
------------------------------------

Visualizes Dominik's calibrated sensors in CARLA:

- Camera frustums based on K_undistortion + image_size
- LiDAR cone / rays based on vTl

✅ FIXES vs your version:
- Uses the *same* calibration semantics as the FIXED dominik_sensor_setup:
    * cTv is VEHICLE->CAMERA  ➜ inverted internally via cTv_to_carla_transform()
    * vTl is LiDAR->VEHICLE   ➜ handled via vTl_to_carla_transform()
- Corrects the frustum ray directions:
    * K_undistortion produces rays in OpenCV camera frame (x right, y down, z forward)
    * We convert those rays into CARLA camera local frame (x forward, y right, z up)
- Backwards compatible:
    * If your environment still has matrix_to_transform(), we can fall back.

Usage:
    viz = SensorVisualizer(world, SETTINGS.SENSOR_CALIB_JSON)
    viz.draw_all(ego)

Tip:
- Call draw_all() repeatedly (e.g., each tick) to keep frustums visible.
"""

import json
import math
from pathlib import Path
from typing import Dict, Any, Optional

import carla
import numpy as np


# ---------------------------------------------------------------------
# Import the *fixed* conversion functions (preferred),
# but remain compatible with older code that has matrix_to_transform().
# ---------------------------------------------------------------------
try:
    from ultimate_pipeline.sensors.dominik_sensor_setup import (
        cTv_to_carla_transform,
        vTl_to_carla_transform,
    )
    _HAS_FIXED_SETUP = True
except Exception:
    _HAS_FIXED_SETUP = False
    cTv_to_carla_transform = None  # type: ignore
    vTl_to_carla_transform = None  # type: ignore

try:
    from ultimate_pipeline.sensors.dominik_sensor_setup import matrix_to_transform  # legacy
except Exception:
    matrix_to_transform = None  # type: ignore


# OpenCV camera axes -> CARLA camera axes
# OpenCV: x right, y down, z forward
# CARLA:  x forward, y right, z up
_OPENCV_CAM_TO_CARLA_CAM = np.array(
    [
        [0.0, 0.0, 1.0],   # carla_x = cv_z
        [1.0, 0.0, 0.0],   # carla_y = cv_x
        [0.0, -1.0, 0.0],  # carla_z = -cv_y
    ],
    dtype=float,
)


class SensorVisualizer:
    def __init__(
        self,
        world: carla.World,
        calib_file: str,
        *,
        # Must match DominikSensorSetup defaults if you want perfect agreement
        flip_vehicle_y: bool = True,
        opencv_camera_axes: bool = True,
        # viz params
        line_lifetime: float = 0.2,
        line_thickness: float = 0.05,
        cam_far: float = 25.0,
        cam_near: float = 0.5,
        lidar_range: float = 40.0,
        draw_labels: bool = True,
    ):
        """
        :param world: CARLA world instance
        :param calib_file: path to calib_data.json
        :param flip_vehicle_y: match dominik_sensor_setup (robotics +Y left -> CARLA +Y right)
        :param opencv_camera_axes: match dominik_sensor_setup (OpenCV cam axes -> CARLA cam axes)
        :param line_lifetime: debug line lifetime in seconds
        :param line_thickness: debug line thickness
        :param cam_far: far plane distance for frustum (m)
        :param cam_near: near plane distance for frustum (m)
        :param lidar_range: visualization ray range (m)
        :param draw_labels: draw sensor name labels
        """
        self.world = world
        self.debug = world.debug

        self.flip_vehicle_y = flip_vehicle_y
        self.opencv_camera_axes = opencv_camera_axes

        self.line_lifetime = float(line_lifetime)
        self.line_thickness = float(line_thickness)
        self.cam_far = float(cam_far)
        self.cam_near = float(cam_near)
        self.lidar_range = float(lidar_range)
        self.draw_labels = bool(draw_labels)

        calib_path = Path(calib_file)
        if not calib_path.exists():
            raise FileNotFoundError(f"Calibration file not found: {calib_path}")

        with open(calib_path, "r", encoding="utf-8") as f:
            self.calib: Dict[str, Any] = json.load(f)

        self.cameras: Dict[str, Any] = self.calib.get("cameras", {})
        self.lidars: Dict[str, Any] = self.calib.get("lidars", {})

        print("🎯 SensorVisualizer loaded")
        print(f"   📷 Cameras: {list(self.cameras.keys())}")
        print(f"   📡 LiDARs: {list(self.lidars.keys())}")
        print(f"   ⚙ flip_vehicle_y={self.flip_vehicle_y}, opencv_camera_axes={self.opencv_camera_axes}")
        if not _HAS_FIXED_SETUP:
            print("   ⚠ Using legacy transform fallback (matrix_to_transform). "
                  "For correct frustums, prefer the FIXED dominik_sensor_setup module.")

    # ------------------------------------------------------------------
    # PUBLIC: DRAW ALL
    # ------------------------------------------------------------------
    def draw_all(self, ego: carla.Actor):
        """Draw all camera frustums + lidar rays for the given ego vehicle."""
        for cam_name in self.cameras.keys():
            self.draw_camera_frustum(ego, cam_name)

        for lidar_name in self.lidars.keys():
            self.draw_lidar_rays(ego, lidar_name)

    # ------------------------------------------------------------------
    # CAMERA FRUSTUM
    # ------------------------------------------------------------------
    def draw_camera_frustum(self, ego: carla.Actor, cam_name: str):
        """
        Draw frustum for a camera using:
          - K_undistortion (intrinsics)
          - image_size
          - cTv (vehicle->camera, inverted internally when using fixed setup)
        """
        cfg = self.cameras.get(cam_name)
        if cfg is None:
            return

        width, height = int(cfg["image_size"][0]), int(cfg["image_size"][1])
        K = np.array(cfg["K_undistortion"], dtype=float)
        K_inv = np.linalg.inv(K)

        # Image plane corners in pixel coords (homogeneous)
        corners_px = [
            np.array([0.0, 0.0, 1.0]),
            np.array([float(width), 0.0, 1.0]),
            np.array([float(width), float(height), 1.0]),
            np.array([0.0, float(height), 1.0]),
        ]

        # Sensor relative transform (vehicle->sensor attachment transform for CARLA)
        cam_rel = self._camera_rel_transform(cfg)

        ego_tf = ego.get_transform()

        cam_origin_world = self._to_world(ego_tf, cam_rel, carla.Location(0.0, 0.0, 0.0))

        near_points_world = []
        far_points_world = []

        for pix in corners_px:
            # Ray direction in OpenCV camera frame
            ray_cv = K_inv @ pix
            ray_cv = ray_cv / (np.linalg.norm(ray_cv) + 1e-12)

            # Convert ray to CARLA camera local axes if setup uses OpenCV camera axes mapping
            # (this MUST match how the camera was attached in dominik_sensor_setup)
            if self.opencv_camera_axes:
                ray_cam = _OPENCV_CAM_TO_CARLA_CAM @ ray_cv
            else:
                # If you disabled axis conversion in setup, keep raw ray definition
                ray_cam = ray_cv

            ray_cam = ray_cam / (np.linalg.norm(ray_cam) + 1e-12)

            # In CARLA camera local frame, axes are (x forward, y right, z up)
            p_near_cam = carla.Location(
                x=float(ray_cam[0] * self.cam_near),
                y=float(ray_cam[1] * self.cam_near),
                z=float(ray_cam[2] * self.cam_near),
            )
            p_far_cam = carla.Location(
                x=float(ray_cam[0] * self.cam_far),
                y=float(ray_cam[1] * self.cam_far),
                z=float(ray_cam[2] * self.cam_far),
            )

            near_points_world.append(self._to_world(ego_tf, cam_rel, p_near_cam))
            far_points_world.append(self._to_world(ego_tf, cam_rel, p_far_cam))

        color = carla.Color(0, 255, 0)

        # Lines from origin to near plane corners
        for p in near_points_world:
            self.debug.draw_line(
                cam_origin_world, p,
                thickness=self.line_thickness,
                color=color,
                life_time=self.line_lifetime,
            )

        # Near plane rectangle
        for i in range(4):
            a = near_points_world[i]
            b = near_points_world[(i + 1) % 4]
            self.debug.draw_line(a, b, thickness=self.line_thickness, color=color, life_time=self.line_lifetime)

        # Far plane rectangle
        for i in range(4):
            a = far_points_world[i]
            b = far_points_world[(i + 1) % 4]
            self.debug.draw_line(a, b, thickness=self.line_thickness, color=color, life_time=self.line_lifetime)

        # Connect near to far
        for a, b in zip(near_points_world, far_points_world):
            self.debug.draw_line(a, b, thickness=self.line_thickness, color=color, life_time=self.line_lifetime)

        # Origin marker + label
        self._draw_origin_marker(cam_origin_world, color=color, label=f"CAM:{cam_name}")

    # ------------------------------------------------------------------
    # LIDAR RAYS
    # ------------------------------------------------------------------
    def draw_lidar_rays(self, ego: carla.Actor, lidar_name: str, n_rays: int = 32):
        """
        Sketch LiDAR cone as multiple rays in the horizontal plane.
        Uses vTl (LiDAR->Vehicle) converted to a CARLA attachment transform.
        """
        cfg = self.lidars.get(lidar_name)
        if cfg is None:
            return

        lid_rel = self._lidar_rel_transform(cfg)
        ego_tf = ego.get_transform()

        origin_world = self._to_world(ego_tf, lid_rel, carla.Location(0.0, 0.0, 0.0))
        color = carla.Color(255, 255, 0)

        for i in range(int(n_rays)):
            ang = 2.0 * math.pi * float(i) / float(n_rays)
            # Assume LiDAR local frame roughly matches CARLA (x forward, y right, z up).
            # If your LiDAR frame differs, you can add a mapping here.
            p_lid = carla.Location(
                x=math.cos(ang) * self.lidar_range,
                y=math.sin(ang) * self.lidar_range,
                z=0.0,
            )
            p_world = self._to_world(ego_tf, lid_rel, p_lid)
            self.debug.draw_line(
                origin_world, p_world,
                thickness=self.line_thickness,
                color=color,
                life_time=self.line_lifetime,
            )

        self._draw_origin_marker(origin_world, color=color, label=f"LIDAR:{lidar_name}")

    # ------------------------------------------------------------------
    # INTERNAL: SENSOR RELATIVE TRANSFORMS
    # ------------------------------------------------------------------
    def _camera_rel_transform(self, cfg: Dict[str, Any]) -> carla.Transform:
        """
        Returns camera transform relative to ego vehicle, consistent with dominik_sensor_setup.

        Preferred: cTv_to_carla_transform(cTv, flip_vehicle_y=?, opencv_camera_axes=?)
        Fallback:  matrix_to_transform(cTv)  (legacy; not correct if cTv is vehicle->camera)
        """
        if _HAS_FIXED_SETUP and cTv_to_carla_transform is not None:
            return cTv_to_carla_transform(
                cfg["cTv"],
                flip_vehicle_y=self.flip_vehicle_y,
                opencv_camera_axes=self.opencv_camera_axes,
            )

        if matrix_to_transform is None:
            raise RuntimeError("No transform conversion available. "
                               "Install/update ultimate_pipeline.sensors.dominik_sensor_setup")
        # Legacy fallback (may be wrong depending on semantics of cTv in your old code)
        return matrix_to_transform(cfg["cTv"])

    def _lidar_rel_transform(self, cfg: Dict[str, Any]) -> carla.Transform:
        """Same pattern as camera, but for vTl."""
        if _HAS_FIXED_SETUP and vTl_to_carla_transform is not None:
            return vTl_to_carla_transform(
                cfg["vTl"],
                flip_vehicle_y=self.flip_vehicle_y,
            )

        if matrix_to_transform is None:
            raise RuntimeError("No transform conversion available. "
                               "Install/update ultimate_pipeline.sensors.dominik_sensor_setup")
        return matrix_to_transform(cfg["vTl"])

    # ------------------------------------------------------------------
    # INTERNAL: COMPOSE TRANSFORMS
    # ------------------------------------------------------------------
    @staticmethod
    def _to_world(
        ego_tf: carla.Transform,
        sensor_rel_tf: carla.Transform,
        point_sensor_frame: carla.Location,
    ) -> carla.Location:
        """
        Convert point from sensor local frame -> world:
            p_vehicle = sensor_rel_tf.transform(p_sensor)
            p_world   = ego_tf.transform(p_vehicle)
        """
        p_vehicle = sensor_rel_tf.transform(point_sensor_frame)
        return ego_tf.transform(p_vehicle)

    def _draw_origin_marker(self, origin_world: carla.Location, *, color: carla.Color, label: str):
        """Draw a small vertical marker and optional label at sensor origin."""
        up = carla.Location(origin_world.x, origin_world.y, origin_world.z + 0.35)
        self.debug.draw_line(
            origin_world,
            up,
            thickness=self.line_thickness * 1.5,
            color=color,
            life_time=self.line_lifetime,
        )
        if self.draw_labels:
            self.debug.draw_string(
                up,
                label,
                draw_shadow=False,
                color=color,
                life_time=self.line_lifetime,
            )
