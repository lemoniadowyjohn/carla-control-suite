"""Coordinate frames: explicit, versioned, and never silently normalised.

The repository carries **four** incompatible transform conventions across
``sensors/transform_conventions.py``, ``attach_sensors_safe.py``,
``dominik_sensor_setup.py``, ``tools/calibrate_sensors_in_carla.py`` and
``carla_tools/sensor_rig.py``. The single most dangerous divergence is an Euler
**tuple-order trap**: ``transform_conventions.py:103-132`` uses
``(yaw, pitch, roll)`` while ``sensor_rig.py:30-51`` uses
``(pitch, yaw, roll)``.

This module therefore:

* names every frame and matrix explicitly;
* uses a single right-handed 4x4 convention;
* **rejects ambiguous input** rather than silently normalising it;
* converts to the CARLA optical frame explicitly.

Note: the upstream ``transform_conventions.py:164`` uses ``assert`` for its
forward-alignment guard. That is stripped under ``python -O``, so the GUI must
raise explicitly instead of asserting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np

__all__ = [
    "AMBIGUOUS_EULER_ORDERS", "EulerOrder", "FrameId", "TransformError",
    "AmbiguousConvention", "identity", "flip_y_conjugation", "vehicle_to_camera",
    "vehicle_to_lidar", "compose", "invert", "euler_zyx_to_matrix",
    "matrix_to_euler_zyx", "matrix_to_rpy_deg", "detected_euler_order",
    "ensure_finite", "OpenCVAdjustment", "apply_opencv_adjustment",
]


class TransformError(ValueError):
    """A transform could not be validated. Never silently clamped."""


class AmbiguousConvention(TransformError):
    """Input did not state which convention it uses."""


class EulerOrder:
    """Explicit Euler tuple orders. Mixing them silently is the bug."""

    YAW_PITCH_ROLL = "yaw_pitch_roll"
    PITCH_YAW_ROLL = "pitch_yaw_roll"
    ROLL_PITCH_YAW = "roll_pitch_yaw"


#: Orders seen in this repository. Deliberately NOT interchangeable.
AMBIGUOUS_EULER_ORDERS: tuple[str, ...] = (
    EulerOrder.YAW_PITCH_ROLL,     # transform_conventions.py:103-132
    EulerOrder.PITCH_YAW_ROLL,     # carla_tools/sensor_rig.py:30-51
    EulerOrder.ROLL_PITCH_YAW,
)


class FrameId:
    """Verified frame identifiers."""

    VEHICLE = "vehicle"          # CARLA world / vehicle frame
    CAMERA_OPTICAL = "camera_optical"   # x right, y down, z forward
    CAMERA_IMU = "camera_imu"     # x forward, y right, z up (sensor body)
    LIDAR = "lidar"
    MAP = "map"
    WORLD = "world"


def identity() -> np.ndarray:
    return np.eye(4, dtype=float)


def ensure_finite(matrix: Iterable[Iterable[float]], name: str = "matrix") -> np.ndarray:
    """Reject non-finite transforms.

    ``dominik_sensor_setup.py`` silently clamps a NaN translation to ``z=1.8``.
    The GUI must **not** do that: a NaN is an error, reported, never repaired.
    """
    array = np.asarray(matrix, dtype=float)
    if array.shape[-2:] != (4, 4):
        raise TransformError(f"{name} must be 4x4, got {array.shape}")
    if not np.all(np.isfinite(array)):
        raise TransformError(f"{name} contains non-finite values (NaN/inf); "
                             "refusing to clamp")
    return array


#: The vehicle-to-optical flip: CARLA vehicle is x-forward/y-right/z-up while
#: the optical camera frame is x-right/y-down/z-forward.
#: Vehicle (x forward, y right, z up) -> optical (z forward, x right, -y up).
#: This matrix is SYMMETRIC and therefore an involution (F @ F == I), which is
#: what makes the conjugation F T F idempotent.
_F = np.array([
    [0.0, 0.0, 1.0, 0.0],
    [0.0, -1.0, 0.0, 0.0],
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
], dtype=float)


def flip_y_conjugation(matrix: Iterable[Iterable[float]]) -> np.ndarray:
    """``F @ T @ F`` -- the vehicle Y basis flip.

    ``_F`` is a symmetric involution (``F @ F == I``), so applying this twice
    returns the original transform exactly. That idempotence is what vector
    TV-04 checks.
    """
    transform = ensure_finite(matrix, "T")
    return _F @ transform @ _F


def vehicle_to_camera(camera_to_vehicle: Iterable[Iterable[float]]) -> np.ndarray:
    """``cTv`` used directly: the input already is the vehicle<-camera matrix."""
    return ensure_finite(camera_to_vehicle, "cTv").copy()


def vehicle_to_lidar(vehicle_to_lidar: Iterable[Iterable[float]], *,
                     flip_vehicle_y: bool = False) -> np.ndarray:
    transform = ensure_finite(vehicle_to_lidar, "vTl")
    return flip_y_conjugation(transform) if flip_vehicle_y else transform.copy()


def compose(*matrices: Iterable[Iterable[float]]) -> np.ndarray:
    out = identity()
    for index, matrix in enumerate(matrices):
        out = out @ ensure_finite(matrix, f"M{index}")
    return out


def invert(matrix: Iterable[Iterable[float]]) -> np.ndarray:
    transform = ensure_finite(matrix, "M")
    try:
        return np.linalg.inv(transform)
    except np.linalg.LinAlgError as exc:
        raise TransformError(f"matrix is singular and cannot be inverted: {exc}") from exc


def euler_zyx_to_matrix(yaw_deg: float, pitch_deg: float, roll_deg: float) -> np.ndarray:
    """ZYX intrinsic order: R = Rz(yaw) @ Ry(pitch) @ Rx(roll)."""
    yaw, pitch, roll = (math.radians(v) for v in (yaw_deg, pitch_deg, roll_deg))
    rz = np.array([[math.cos(yaw), -math.sin(yaw), 0.0],
                   [math.sin(yaw), math.cos(yaw), 0.0],
                   [0.0, 0.0, 1.0]])
    ry = np.array([[math.cos(pitch), 0.0, math.sin(pitch)],
                   [0.0, 1.0, 0.0],
                   [-math.sin(pitch), 0.0, math.cos(pitch)]])
    rx = np.array([[1.0, 0.0, 0.0],
                   [0.0, math.cos(roll), -math.sin(roll)],
                   [0.0, math.sin(roll), math.cos(roll)]])
    rotation = rz @ ry @ rx
    out = identity()
    out[:3, :3] = rotation
    return out


def matrix_to_euler_zyx(rotation: np.ndarray) -> tuple[float, float, float]:
    """Extract (yaw, pitch, roll) in degrees. Handles the gimbal-lock branch."""
    sy = math.sqrt(rotation[0, 0] ** 2 + rotation[1, 0] ** 2)
    if sy > 1e-12:
        # R = Rz(yaw) Ry(pitch) Rx(roll):
        #   R[0,0] = cos(y)cos(p)   R[1,0] = sin(y)cos(p)  -> yaw
        #   R[2,0] = -sin(p)                               -> pitch
        #   R[2,1] = cos(p)sin(r)   R[2,2] = cos(p)cos(r)  -> roll
        yaw = math.atan2(rotation[1, 0], rotation[0, 0])
        pitch = math.atan2(-rotation[2, 0], sy)
        roll = math.atan2(rotation[2, 1], rotation[2, 2])
    else:
        # Gimbal lock (cos(pitch) == 0): pitch is +/-90 deg and yaw/roll are not
        # separable. Return pitch from the remaining entries rather than NaN.
        pitch = math.atan2(-rotation[2, 0], sy)
        yaw = 0.0
        roll = 0.0
    return (math.degrees(yaw), math.degrees(pitch), math.degrees(roll))


def matrix_to_rpy_deg(matrix: np.ndarray) -> tuple[float, float, float]:
    """Unreal roll/pitch/yaw in degrees, from a 4x4 homogeneous matrix."""
    return matrix_to_euler_zyx(np.asarray(matrix, dtype=float)[:3, :3])


def detected_euler_order(site: str) -> str:
    """Resolve the Euler order for a named upstream site.

    Unknown sites raise :class:`AmbiguousConvention` rather than defaulting --
    guessing an order here is exactly the silent-normalisation bug.
    """
    known = {
        "transform_conventions.py": EulerOrder.YAW_PITCH_ROLL,
        "sensor_rig.py": EulerOrder.PITCH_YAW_ROLL,
    }
    for suffix, order in known.items():
        if site.endswith(suffix):
            return order
    raise AmbiguousConvention(
        f"no verified Euler order for {site!r}; declare it explicitly "
        f"(known orders: {list(AMBIGUOUS_EULER_ORDERS)})"
    )


@dataclass(frozen=True)
class OpenCVAdjustment:
    """The documented vehicle/optical rotation applied to a plain identity."""

    rotation: tuple[tuple[float, float, float], ...]

    def as_matrix(self) -> np.ndarray:
        return np.array(self.rotation, dtype=float)


#: Matches the documented rotation block for the OpenCV right-multiply case.
OPENCV_VEHICLE_TO_OPTICAL_ROTATION = OpenCVAdjustment((
    (0.0, 0.0, 1.0),
    (1.0, 0.0, 0.0),
    (0.0, -1.0, 0.0),
))


def apply_opencv_adjustment(transform: Iterable[Iterable[float]],
                           adjustment: OpenCVAdjustment = OPENCV_VEHICLE_TO_OPTICAL_ROTATION,
                           *, right_multiply: bool = True) -> np.ndarray:
    """Right-multiply (or left-multiply) by the documented optical rotation."""
    base = ensure_finite(transform, "T")
    block = adjustment.as_matrix()
    if right_multiply:
        out = base.copy()
        out[:3, :3] = base[:3, :3] @ block
        return out
    out = base.copy()
    out[:3, :3] = block @ base[:3, :3]
    return out