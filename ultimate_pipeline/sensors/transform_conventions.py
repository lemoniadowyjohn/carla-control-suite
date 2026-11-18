"""Explicit calibration-to-CARLA mounting transforms.

The source calibration uses a right-handed vehicle FLU frame (forward, left,
up), OpenCV optical camera frames (right, down, forward), and LiDAR-to-vehicle
``vTl`` matrices. CARLA attachment poses use the CARLA parent/sensor frame
(forward, right, up). All translations are metres and matrices are column-vector
homogeneous transforms ``T_target_from_source``.

The authoritative functions below return the CARLA child sensor pose relative
to the CARLA ego parent. Compatibility functions are intentionally thin and
reject options that would select a different convention.
"""
from __future__ import annotations

import math
import warnings
from typing import Any, Dict, Tuple

import numpy as np

CALIBRATION_CONTRACT_VERSION = "CARLA_SENSOR_MOUNTING/v2"
SOURCE_VEHICLE_FRAME = "vehicle_flu"
SOURCE_CAMERA_FRAME = "camera_opencv_optical"
SOURCE_LIDAR_FRAME = "lidar"
CARLA_PARENT_FRAME = "carla_ego_forward_right_up"
CARLA_CAMERA_FRAME = "carla_camera_forward_right_up"
CARLA_LIDAR_FRAME = "carla_lidar_forward_right_up"
TRANSLATION_UNIT = "metre"

# Coordinate basis changes. A reflection is applied on both sides of each
# rotation, so the resulting rigid rotations remain proper (determinant +1).
_FLU_TO_CARLA_FRU = np.diag([1.0, -1.0, 1.0, 1.0])
_CARLA_CAMERA_TO_OPENCV_OPTICAL = np.eye(4, dtype=float)
_CARLA_CAMERA_TO_OPENCV_OPTICAL[:3, :3] = np.array(
    [[0.0, 1.0, 0.0], [0.0, 0.0, -1.0], [1.0, 0.0, 0.0]], dtype=float
)
OPENCV_CAM_TO_CARLA = _CARLA_CAMERA_TO_OPENCV_OPTICAL[:3, :3].T.copy()


def _checked_source_rigid_transform(value: Any, *, label: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=float)
    if matrix.shape == (3, 4):
        matrix = np.vstack((matrix, [0.0, 0.0, 0.0, 1.0]))
    if matrix.shape != (4, 4):
        raise ValueError(f"{label} must be a 4x4 or 3x4 transform")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{label} contains non-finite values")
    if not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-9, rtol=0):
        raise ValueError(f"{label} has an invalid homogeneous row")
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6, rtol=0):
        raise ValueError(f"{label} rotation is not orthonormal")
    determinant = float(np.linalg.det(rotation))
    if not math.isclose(determinant, 1.0, abs_tol=1e-6, rel_tol=0):
        raise ValueError(f"{label} rotation is reflected or nonrigid (det={determinant})")
    return matrix


def _vehicle_flu_from_camera_optical(cTv_vehicle_to_camera: Any) -> np.ndarray:
    """Return ``T_vehicle_flu_from_camera_optical`` from authoritative ``cTv``."""
    camera_optical_from_vehicle_flu = _checked_source_rigid_transform(
        cTv_vehicle_to_camera, label="cTv (camera_optical_from_vehicle_flu)"
    )
    rotation = camera_optical_from_vehicle_flu[:3, :3]
    translation = camera_optical_from_vehicle_flu[:3, 3]
    result = np.eye(4, dtype=float)
    result[:3, :3] = rotation.T
    result[:3, 3] = -(rotation.T @ translation)
    return result


def carla_ego_from_camera_from_cTv(cTv_vehicle_to_camera: Any) -> np.ndarray:
    """Return ``T_carla_ego_from_carla_camera`` for CARLA sensor attachment.

    Derivation: ``S @ inverse(cTv) @ M`` where S converts vehicle FLU to CARLA
    FRU and M converts CARLA camera axes to OpenCV optical axes. Uses the
    rigid-transform inverse, not a general matrix inverse.
    """
    camera_from_vehicle_flu = _checked_source_rigid_transform(
        cTv_vehicle_to_camera, label="cTv (camera_optical_from_vehicle_flu)"
    )
    vehicle_flu_from_camera_optical = _vehicle_flu_from_camera_optical(
        camera_from_vehicle_flu
    )
    result = (
        _FLU_TO_CARLA_FRU
        @ vehicle_flu_from_camera_optical
        @ _CARLA_CAMERA_TO_OPENCV_OPTICAL
    )
    return _checked_source_rigid_transform(
        result, label="T_carla_ego_from_carla_camera"
    )


def carla_ego_from_lidar_from_vTl(vTl_vehicle_from_lidar: Any) -> np.ndarray:
    """Return ``T_carla_ego_from_carla_lidar`` from source ``vTl``.

    Both source vehicle FLU and LiDAR coordinate basis are converted to CARLA
    FRU explicitly: ``S @ vTl @ S``. Translation components are in metres.
    """
    vehicle_flu_from_lidar = _checked_source_rigid_transform(
        vTl_vehicle_from_lidar, label="vTl (vehicle_flu_from_lidar)"
    )
    result = _FLU_TO_CARLA_FRU @ vehicle_flu_from_lidar @ _FLU_TO_CARLA_FRU
    return _checked_source_rigid_transform(
        result, label="T_carla_ego_from_carla_lidar"
    )


def carla_rotation_matrix_to_rpy_deg(rotation: Any) -> Tuple[float, float, float]:
    """Extract CARLA ``(roll,pitch,yaw)`` degrees from CARLA's basis matrix.

    CARLA 0.9.16's ``Transform.get_matrix()`` uses a left-handed basis where
    positive pitch raises forward-vector z and positive roll lowers right-vector
    z. This sign convention is intentionally different from common RH ZYX
    extraction formulas.
    """
    matrix = np.asarray(rotation, dtype=float)
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
        raise ValueError("CARLA rotation must be a finite 3x3 matrix")
    if not np.allclose(matrix.T @ matrix, np.eye(3), atol=1e-6, rtol=0):
        raise ValueError("CARLA rotation matrix must be orthonormal")
    if not math.isclose(float(np.linalg.det(matrix)), 1.0, abs_tol=1e-6, rel_tol=0):
        raise ValueError("CARLA rotation matrix must be proper")
    pitch = math.atan2(float(matrix[2, 0]), math.hypot(float(matrix[0, 0]), float(matrix[1, 0])))
    if abs(math.cos(pitch)) < 1e-8:
        roll = 0.0
        yaw = math.atan2(-float(matrix[0, 1]), float(matrix[1, 1]))
    else:
        roll = math.atan2(-float(matrix[2, 1]), float(matrix[2, 2]))
        yaw = math.atan2(float(matrix[1, 0]), float(matrix[0, 0]))
    return tuple(math.degrees(value) for value in (roll, pitch, yaw))


def carla_attachment_pose_from_matrix(T_carla_parent_from_carla_sensor: Any) -> Dict[str, float]:
    matrix = _checked_source_rigid_transform(
        T_carla_parent_from_carla_sensor, label="CARLA parent_from_sensor mount"
    )
    roll, pitch, yaw = carla_rotation_matrix_to_rpy_deg(matrix[:3, :3])
    return {
        "x": float(matrix[0, 3]), "y": float(matrix[1, 3]), "z": float(matrix[2, 3]),
        "roll": float(roll), "pitch": float(pitch), "yaw": float(yaw),
    }


# Compatibility names. Options that would change the v2 frame semantics fail
# closed; the historical y-flip flag is accepted only as a deprecated no-op.
def vehicle_to_camera_from_cTv(
    cTv: Any, *, flip_vehicle_y: bool = False,
    opencv_camera_axes: bool | None = None, ctv_invert: bool | None = None,
) -> np.ndarray:
    if ctv_invert:
        raise ValueError("v2 mounting always derives the camera pose from inverse(cTv)")
    if opencv_camera_axes is False:
        raise ValueError("v2 camera mounting requires the declared OpenCV optical frame")
    if flip_vehicle_y:
        warnings.warn("flip_vehicle_y is deprecated; v2 applies both frame basis conversions", DeprecationWarning)
    return carla_ego_from_camera_from_cTv(cTv)


def vehicle_to_lidar_from_vTl(vTl: Any, *, flip_vehicle_y: bool = False) -> np.ndarray:
    if flip_vehicle_y:
        warnings.warn("flip_vehicle_y is deprecated; v2 applies both frame basis conversions", DeprecationWarning)
    return carla_ego_from_lidar_from_vTl(vTl)


def rotation_matrix_to_unreal_rpy_deg(rotation: Any) -> Tuple[float, float, float]:
    """Deprecated alias for CARLA 0.9.16 matrix extraction."""
    return carla_rotation_matrix_to_rpy_deg(rotation)


def matrix_to_unreal_pose(matrix: Any) -> Dict[str, float]:
    """Deprecated alias for explicit CARLA parent-from-sensor mount conversion."""
    return carla_attachment_pose_from_matrix(matrix)


def camera_attachment_pose_from_cTv(
    cTv: Any, *, flip_vehicle_y: bool = False,
    opencv_camera_axes: bool | None = None, ctv_invert: bool | None = None,
    forward_alignment_min: float | None = None,
) -> Dict[str, Any]:
    if forward_alignment_min not in (None, 0.5):
        raise ValueError("forward_alignment_min is diagnostic-only and cannot redefine v2 orientation")
    matrix = carla_ego_from_camera_from_cTv(cTv)
    pose = carla_attachment_pose_from_matrix(matrix)
    forward = matrix[:3, 0]
    pose.update({
        "forward_vehicle_x": float(forward[0]),
        "forward_vehicle_y": float(forward[1]),
        "forward_vehicle_z": float(forward[2]),
        "mount_rotation_valid": True,
        "mount_matrix": matrix.tolist(),
        "contract_version": CALIBRATION_CONTRACT_VERSION,
    })
    return pose


def lidar_attachment_pose_from_vTl(vTl: Any, *, flip_vehicle_y: bool = False) -> Dict[str, float]:
    matrix = carla_ego_from_lidar_from_vTl(vTl)
    pose = carla_attachment_pose_from_matrix(matrix)
    pose["mount_matrix"] = matrix.tolist()
    pose["contract_version"] = CALIBRATION_CONTRACT_VERSION
    return pose
