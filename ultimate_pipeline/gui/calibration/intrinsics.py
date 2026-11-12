"""Camera intrinsics, extrinsics and reprojection -- measured or nothing.

Three rules that the documentation is emphatic about:

* **``K_undistortion`` is the only intrinsics oracle.** A ``K`` present in a
  fixture must appear in ``ignored_sources`` and must never influence the output
  (``calibration_contract.py:63-82``, `:74`).
* **Distortion is ignored.** CARLA applies no distortion, so the output states
  ``distortion_in_carla == "none"`` and never uses ``D`` (``:20-21``).
* **FOV comes from ``fx`` and width only.** A vertical FOV must never be
  reported (``:55-60``).

Reprojection metrics are produced **only when observed pixels exist**. Without
observed pixels the metric is ``None`` -- never a plausible-looking number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

__all__ = [
    "IntrinsicsError", "parse_image_size", "fov_deg_from_fx",
    "effective_camera_intrinsics", "compose_extrinsics", "invert_extrinsics",
    "reprojection_residual", "ReprojectionReport", "lidar_points_to_camera",
]


class IntrinsicsError(ValueError):
    """Calibration data is missing, malformed or ambiguous."""


def parse_image_size(value: Any) -> tuple[int, int]:
    """Accept both the dict form and the list form of ``image_size``.

    The list form is accepted but warned about, because ``sensor_rig.py:76``
    requires the dict form.
    """
    if isinstance(value, dict):
        try:
            width, height = int(value["width"]), int(value["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IntrinsicsError(f"image_size dict is missing width/height: {exc}") from exc
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            width, height = int(value[0]), int(value[1])
        except (TypeError, ValueError) as exc:
            raise IntrinsicsError(f"image_size list is not integral: {value!r}") from exc
    else:
        raise IntrinsicsError(f"unsupported image_size format: {value!r}")
    if width <= 0 or height <= 0:
        raise IntrinsicsError(f"image_size must be positive, got ({width}, {height})")
    return width, height


def fov_deg_from_fx(fx: float, width_px: int) -> float:
    """Horizontal FOV from focal length and width. Never from ``fy``."""
    if fx <= 0:
        raise IntrinsicsError(f"fx must be positive, got {fx}")
    if width_px <= 0:
        raise IntrinsicsError(f"width must be positive, got {width_px}")
    return math.degrees(2.0 * math.atan(width_px / (2.0 * fx)))


def _ensure_k(matrix: Any, name: str = "K_undistortion") -> np.ndarray:
    array = np.asarray(matrix, dtype=float)
    if array.shape != (3, 3):
        raise IntrinsicsError(f"{name} must be 3x3, got {array.shape}")
    if not np.all(np.isfinite(array)):
        raise IntrinsicsError(f"{name} contains non-finite values")
    if array[0, 0] <= 0:
        raise IntrinsicsError(f"{name} fx must be positive")
    return array


def effective_camera_intrinsics(camera: dict) -> dict:
    """Resolve effective intrinsics from ``K_undistortion`` only.

    ``K`` is recorded as ignored. ``D`` is recorded as ignored because CARLA
    applies no distortion.
    """
    if "K_undistortion" not in camera:
        raise IntrinsicsError("camera calibration missing K_undistortion")
    if "image_size" not in camera:
        raise IntrinsicsError("camera calibration missing image_size")

    k = _ensure_k(camera["K_undistortion"])
    width, height = parse_image_size(camera["image_size"])

    ignored: list[str] = []
    if "K" in camera:
        ignored.append("K")
    if "D" in camera:
        ignored.append("D")

    return {
        "source": "K_undistortion_ideal_pinhole",
        "width": width,
        "height": height,
        "fx": float(k[0, 0]),
        "fy": float(k[1, 1]),
        "cx": float(k[0, 2]),
        "cy": float(k[1, 2]),
        "horizontal_fov_deg": fov_deg_from_fx(float(k[0, 0]), width),
        "distortion_in_carla": "none",
        "ignored_sources": ignored,
        "K": k.tolist(),
    }


def compose_extrinsics(*matrices: Sequence[Sequence[float]]) -> np.ndarray:
    """Compose 4x4 extrinsics left-to-right."""
    out = np.eye(4, dtype=float)
    for index, matrix in enumerate(matrices):
        array = np.asarray(matrix, dtype=float)
        if array.shape != (4, 4):
            raise IntrinsicsError(f"extrinsic M{index} must be 4x4, got {array.shape}")
        if not np.all(np.isfinite(array)):
            raise IntrinsicsError(f"extrinsic M{index} contains non-finite values")
        out = out @ array
    return out


def invert_extrinsics(matrix: Sequence[Sequence[float]]) -> np.ndarray:
    array = np.asarray(matrix, dtype=float)
    if array.shape != (4, 4):
        raise IntrinsicsError(f"extrinsic must be 4x4, got {array.shape}")
    try:
        return np.linalg.inv(array)
    except np.linalg.LinAlgError as exc:
        raise IntrinsicsError(f"extrinsic is singular: {exc}") from exc


def project_points(points_camera: np.ndarray, k: np.ndarray) -> np.ndarray:
    """Project 3D optical-frame points to pixels via the intrinsics matrix."""
    pts = np.asarray(points_camera, dtype=float).reshape(-1, 3)
    # Row-vector convention: the 3D point (X, Y, Z) is multiplied by K directly,
    # giving (u*Z, v*Z, Z). A 4x3 homogeneous form would need a 4x4 K, which does
    # not exist here.
    projected = pts @ np.asarray(k, dtype=float)
    depth = projected[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        u = projected[:, 0] / depth
        v = projected[:, 1] / depth
    return np.stack([u, v], axis=1)


@dataclass(frozen=True)
class ReprojectionReport:
    """Reprojection metrics. ``None`` when no observed pixels exist."""

    reprojection_residual_px: float | None
    mean_reprojection_residual_px: float | None
    max_reprojection_residual_px: float | None
    n_points: int
    reason: str = ""

    @property
    def measured(self) -> bool:
        return self.reprojection_residual_px is not None

    def as_dict(self) -> dict:
        return {"reprojection_residual_px": self.reprojection_residual_px,
                "mean_residual_px": self.mean_reprojection_residual_px,
                "max_residual_px": self.max_reprojection_residual_px,
                "n_points": self.n_points, "measured": self.measured,
                "reason": self.reason}


def reprojection_residual(points_camera: np.ndarray,
                         observed_pixels: np.ndarray | None,
                         k: np.ndarray) -> ReprojectionReport:
    """Reprojection error, or an explicit *not measured* report.

    With no observed pixels the metrics stay ``None``. Producing a plausible
    number here would be the exact failure the calibration workbench must avoid.
    """
    pts = np.asarray(points_camera, dtype=float).reshape(-1, 3)
    if observed_pixels is None:
        return ReprojectionReport(None, None, None, 0,
                                  "no observed pixels: metric NOT MEASURED")
    observed = np.asarray(observed_pixels, dtype=float).reshape(-1, 2)
    if observed.shape[0] == 0:
        return ReprojectionReport(None, None, None, 0,
                                  "observed pixel set is empty: NOT MEASURED")
    if observed.shape[0] != pts.shape[0]:
        return ReprojectionReport(None, None, None, 0,
                                  f"count mismatch: {pts.shape[0]} points vs "
                                  f"{observed.shape[0]} observed pixels")

    projected = project_points(pts, k)
    deltas = np.linalg.norm(projected - observed, axis=1)
    return ReprojectionReport(
        reprojection_residual_px=float(deltas.mean()),
        mean_reprojection_residual_px=float(deltas.mean()),
        max_reprojection_residual_px=float(deltas.max()),
        n_points=int(pts.shape[0]),
        reason="measured against observed pixels",
    )


def lidar_points_to_camera(points_lidar: np.ndarray,
                           v_t_l: np.ndarray,
                           l_t_c: np.ndarray) -> np.ndarray:
    """LiDAR -> vehicle -> camera (optical frame) point conversion."""
    pts = np.asarray(points_lidar, dtype=float).reshape(-1, 3)
    l_t_v = np.asarray(invert_extrinsics(v_t_l), dtype=float)
    c_t_l = np.asarray(invert_extrinsics(l_t_c), dtype=float)
    vehicle = pts @ l_t_v[:3, :3].T + l_t_v[:3, 3]
    camera = vehicle @ c_t_l[:3, :3].T + c_t_l[:3, 3]
    return camera

