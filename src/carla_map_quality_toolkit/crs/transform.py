from __future__ import annotations

import numpy as np
from pyproj import Transformer


def transform_points(points: np.ndarray, source_crs: str, target_crs: str) -> np.ndarray:
    """Transform Nx2 coordinates with axis order pinned to x/y (lon/lat)."""
    arr = np.asarray(points, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError("points must have shape (N, 2)")
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    x, y = transformer.transform(arr[:, 0], arr[:, 1])
    return np.column_stack([x, y])


def roundtrip_max_error(points: np.ndarray, source_crs: str, target_crs: str) -> float:
    forward = transform_points(points, source_crs, target_crs)
    restored = transform_points(forward, target_crs, source_crs)
    return float(np.linalg.norm(restored - np.asarray(points, dtype=float), axis=1).max())
