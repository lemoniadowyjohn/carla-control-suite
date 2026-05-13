from __future__ import annotations

import numpy as np


def _as_2d(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x.reshape(-1, 1)
    if x.ndim != 2:
        raise ValueError(f"Expected 2D features, got shape={x.shape}")
    return x


def apply_coral(Xs: np.ndarray, Xt: np.ndarray, *, eps: float = 1e-6) -> tuple[np.ndarray, np.ndarray]:
    """CORAL alignment: match target covariance by transforming source."""
    Xs = _as_2d(Xs)
    Xt = _as_2d(Xt)

    mu_s = Xs.mean(axis=0, keepdims=True)
    mu_t = Xt.mean(axis=0, keepdims=True)

    Xs0 = Xs - mu_s
    Xt0 = Xt - mu_t

    Cs = np.cov(Xs0, rowvar=False) + eps * np.eye(Xs.shape[1])
    Ct = np.cov(Xt0, rowvar=False) + eps * np.eye(Xt.shape[1])

    ws, vs = np.linalg.eigh(Cs)
    ws = np.maximum(ws, eps)
    Cs_inv_sqrt = (vs * (1.0 / np.sqrt(ws))) @ vs.T

    wt, vt = np.linalg.eigh(Ct)
    wt = np.maximum(wt, eps)
    Ct_sqrt = (vt * np.sqrt(wt)) @ vt.T

    A = Cs_inv_sqrt @ Ct_sqrt
    Xs_coral = Xs0 @ A + mu_t
    return Xs_coral.astype(np.float32), Xt.astype(np.float32)
