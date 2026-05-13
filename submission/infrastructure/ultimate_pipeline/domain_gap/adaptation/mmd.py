from __future__ import annotations

import numpy as np


def _as_2d(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x.reshape(-1, 1)
    if x.ndim != 2:
        raise ValueError(f"Expected 2D features, got shape={x.shape}")
    return x


def apply_mmd(Xs: np.ndarray, Xt: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Lightweight mean-matching alignment (MMD-inspired baseline)."""
    Xs = _as_2d(Xs)
    Xt = _as_2d(Xt)
    mu_s = Xs.mean(axis=0, keepdims=True)
    mu_t = Xt.mean(axis=0, keepdims=True)
    Xs_shift = Xs - mu_s + mu_t
    return Xs_shift.astype(np.float32), Xt.astype(np.float32)
