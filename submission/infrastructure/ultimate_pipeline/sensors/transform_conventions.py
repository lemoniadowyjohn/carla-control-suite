from __future__ import annotations

import logging
import math
import os
from typing import Any, Dict, Tuple

import numpy as np

log = logging.getLogger(__name__)

# OpenCV camera axes -> CARLA/Unreal camera axes
# OpenCV: x right, y down, z forward
# CARLA:  x forward, y right, z up
OPENCV_CAM_TO_CARLA = np.array(
    [
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
        [0.0, -1.0, 0.0],
    ],
    dtype=float,
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in ("1", "true", "yes", "on", "y")


def _ensure_homogeneous(matrix: Any) -> np.ndarray:
    """Force a 4x4 homogeneous matrix."""
    arr = np.asarray(matrix, dtype=float)
    if arr.shape == (3, 4):
        arr = np.vstack([arr, [0.0, 0.0, 0.0, 1.0]])
    if arr.shape != (4, 4):
        raise ValueError(f"Expected 4x4 or 3x4 matrix, got {arr.shape}")
    return arr


def _flip_vehicle_y_basis(matrix: np.ndarray) -> np.ndarray:
    """Apply a full basis flip on Y (left/right) to the full 4x4."""
    flip = np.diag([1.0, -1.0, 1.0, 1.0])
    return flip @ matrix @ flip


def _guard_manual_ctv_inversion_request(*, do_invert: bool, ctv_invert: bool | None) -> None:
    if not bool(do_invert):
        return

    source = "caller argument ctv_invert=True" if ctv_invert is not None else "env UP_CAMERA_CTV_INVERT"
    message = (
        "Non-canonical camera cTv inversion requested via "
        f"{source}. Thesis contract requires direct Vehicle->Camera usage (no inversion)."
    )
    if _env_bool("UP_THESIS_STRICT", False):
        raise RuntimeError(message)
    log.warning(message)


def vehicle_to_camera_from_cTv(
    cTv: np.ndarray,
    *,
    flip_vehicle_y: bool,
    opencv_camera_axes: bool | None = None,
    ctv_invert: bool | None = None,
) -> np.ndarray:
    """Return vehicle->camera attachment transform with canonical axis handling."""
    T_vehicle_camera = _ensure_homogeneous(cTv)

    # Thesis default: do NOT invert cTv. Explicit opt-in only.
    do_invert = _env_bool("UP_CAMERA_CTV_INVERT", False) if ctv_invert is None else bool(ctv_invert)
    _guard_manual_ctv_inversion_request(do_invert=do_invert, ctv_invert=ctv_invert)
    if do_invert:
        T_vehicle_camera = np.linalg.inv(T_vehicle_camera)

    if flip_vehicle_y:
        T_vehicle_camera = _flip_vehicle_y_basis(T_vehicle_camera)

    # Default ON: treat camera axes as OpenCV and convert once for CARLA attachment.
    use_opencv_axes = (
        _env_bool("UP_CAMERA_OPENCV_AXES", True)
        if opencv_camera_axes is None
        else _env_bool("UP_CAMERA_OPENCV_AXES", bool(opencv_camera_axes))
    )
    if use_opencv_axes:
        T_vehicle_camera = T_vehicle_camera.copy()
        T_vehicle_camera[:3, :3] = T_vehicle_camera[:3, :3] @ OPENCV_CAM_TO_CARLA

    return T_vehicle_camera


def vehicle_to_lidar_from_vTl(vTl: np.ndarray, *, flip_vehicle_y: bool) -> np.ndarray:
    """Return vehicle->lidar for CARLA attachment (vTl is lidar->vehicle)."""
    T_lidar_vehicle = _ensure_homogeneous(vTl)
    T_vehicle_lidar = np.linalg.inv(T_lidar_vehicle)
    if flip_vehicle_y:
        T_vehicle_lidar = _flip_vehicle_y_basis(T_vehicle_lidar)
    return T_vehicle_lidar


def rotation_matrix_to_unreal_rpy_deg(rotation: np.ndarray) -> Tuple[float, float, float]:
    """Convert a 3x3 rotation matrix to Unreal roll/pitch/yaw in degrees."""
    rot = np.asarray(rotation, dtype=float)
    sy = math.sqrt(rot[0, 0] ** 2 + rot[1, 0] ** 2)
    singular = sy < 1e-6

    if not singular:
        roll = math.atan2(rot[2, 1], rot[2, 2])
        pitch = math.atan2(-rot[2, 0], sy)
        yaw = math.atan2(rot[1, 0], rot[0, 0])
    else:
        roll = math.atan2(-rot[1, 2], rot[1, 1])
        pitch = math.atan2(-rot[2, 0], sy)
        yaw = 0.0

    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)


def matrix_to_unreal_pose(matrix: np.ndarray) -> Dict[str, float]:
    """Convert a 4x4 transform to CARLA/Unreal pose fields."""
    mat = _ensure_homogeneous(matrix)
    roll, pitch, yaw = rotation_matrix_to_unreal_rpy_deg(mat[:3, :3])
    return {
        "x": float(mat[0, 3]),
        "y": float(mat[1, 3]),
        "z": float(mat[2, 3]),
        "roll": float(roll),
        "pitch": float(pitch),
        "yaw": float(yaw),
    }


def camera_attachment_pose_from_cTv(
    cTv: np.ndarray,
    *,
    flip_vehicle_y: bool,
    opencv_camera_axes: bool | None = None,
    ctv_invert: bool | None = None,
    forward_alignment_min: float = 0.5,
) -> Dict[str, Any]:
    """
    Build CARLA-ready camera pose fields + forward-vector alignment diagnostics.
    """
    T_vehicle_camera = vehicle_to_camera_from_cTv(
        cTv,
        flip_vehicle_y=flip_vehicle_y,
        opencv_camera_axes=opencv_camera_axes,
        ctv_invert=ctv_invert,
    )
    pose = matrix_to_unreal_pose(T_vehicle_camera)

    forward_vehicle = np.asarray(T_vehicle_camera[:3, 0], dtype=float)
    norm = float(np.linalg.norm(forward_vehicle))
    if norm > 1e-9:
        forward_vehicle = forward_vehicle / norm
    forward_alignment = float(
        np.dot(forward_vehicle, np.asarray([1.0, 0.0, 0.0], dtype=float))
    )

    alignment_ok = True
    try:
        assert forward_alignment >= float(forward_alignment_min)
    except AssertionError:
        alignment_ok = False

    pose["forward_vehicle_x"] = float(forward_vehicle[0])
    pose["forward_vehicle_y"] = float(forward_vehicle[1])
    pose["forward_vehicle_z"] = float(forward_vehicle[2])
    pose["forward_alignment_to_vehicle_x"] = float(forward_alignment)
    pose["forward_alignment_ok"] = bool(alignment_ok)
    return pose


def lidar_attachment_pose_from_vTl(vTl: np.ndarray, *, flip_vehicle_y: bool) -> Dict[str, float]:
    """Build CARLA-ready LiDAR pose fields from vTl."""
    T_vehicle_lidar = vehicle_to_lidar_from_vTl(vTl, flip_vehicle_y=flip_vehicle_y)
    return matrix_to_unreal_pose(T_vehicle_lidar)
