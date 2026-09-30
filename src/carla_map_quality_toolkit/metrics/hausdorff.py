from __future__ import annotations

import numpy as np


def _validate(points: np.ndarray) -> np.ndarray:
    arr = np.asarray(points, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2 or len(arr) == 0:
        raise ValueError("point set must have shape (N, 2) and be non-empty")
    return arr


def directed_hausdorff(a: np.ndarray, b: np.ndarray) -> float:
    """Discrete directed Hausdorff distance for 2D point sets."""
    aa, bb = _validate(a), _validate(b)
    diff = aa[:, None, :] - bb[None, :, :]
    distances = np.sqrt(np.sum(diff**2, axis=2))
    return float(np.max(np.min(distances, axis=1)))


def symmetric_hausdorff(a: np.ndarray, b: np.ndarray) -> float:
    return max(directed_hausdorff(a, b), directed_hausdorff(b, a))
