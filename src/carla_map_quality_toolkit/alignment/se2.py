from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SE2Transform:
    angle_rad: float
    tx: float
    ty: float

    @property
    def rotation(self) -> np.ndarray:
        c, s = math.cos(self.angle_rad), math.sin(self.angle_rad)
        return np.array([[c, -s], [s, c]], dtype=float)

    def apply(self, points: np.ndarray) -> np.ndarray:
        arr = np.asarray(points, dtype=float)
        return arr @ self.rotation.T + np.array([self.tx, self.ty])

    def inverse(self) -> "SE2Transform":
        r_t = self.rotation.T
        t_inv = -(r_t @ np.array([self.tx, self.ty]))
        return SE2Transform(-self.angle_rad, float(t_inv[0]), float(t_inv[1]))


def estimate_se2(source: np.ndarray, target: np.ndarray) -> tuple[SE2Transform, float]:
    """Deterministic least-squares rigid 2D alignment for paired points."""
    src = np.asarray(source, dtype=float)
    dst = np.asarray(target, dtype=float)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 2:
        raise ValueError("source and target must both have shape (N, 2)")
    if len(src) < 2:
        raise ValueError("at least two point correspondences are required")

    src_centroid = src.mean(axis=0)
    dst_centroid = dst.mean(axis=0)
    src0, dst0 = src - src_centroid, dst - dst_centroid
    covariance = src0.T @ dst0
    u, _, vt = np.linalg.svd(covariance)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
    translation = dst_centroid - rotation @ src_centroid
    angle = math.atan2(rotation[1, 0], rotation[0, 0])
    transform = SE2Transform(angle, float(translation[0]), float(translation[1]))
    residuals = transform.apply(src) - dst
    rmse = float(np.sqrt(np.mean(np.sum(residuals**2, axis=1))))
    return transform, rmse
