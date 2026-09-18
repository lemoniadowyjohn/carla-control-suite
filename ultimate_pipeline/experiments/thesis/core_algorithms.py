"""Core algorithms used by thesis experiments (small, self-contained).

This module exists to keep experiment scripts import-stable even when optional
ML stacks are not installed.
"""

from __future__ import annotations

import numpy as np


def _as_2d(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x.reshape(-1, 1)
    if x.ndim != 2:
        raise ValueError(f"Expected 2D features, got shape={x.shape}")
    return x


def coral_loss(Xs: np.ndarray, Xt: np.ndarray, *, eps: float = 1e-6) -> float:
    """CORAL loss: Frobenius distance between covariances."""
    Xs = _as_2d(Xs)
    Xt = _as_2d(Xt)
    Cs = np.cov(Xs, rowvar=False) + eps * np.eye(Xs.shape[1])
    Ct = np.cov(Xt, rowvar=False) + eps * np.eye(Xt.shape[1])
    diff = Cs - Ct
    return float(np.mean(diff * diff))


def _rbf_kernel(X: np.ndarray, Y: np.ndarray, *, gamma: float | None = None) -> np.ndarray:
    X = _as_2d(X)
    Y = _as_2d(Y)
    # Median heuristic if gamma not provided
    if gamma is None:
        # Subsample for speed
        xs = X[: min(256, len(X))]
        ys = Y[: min(256, len(Y))]
        d2 = np.sum((xs[:, None, :] - ys[None, :, :]) ** 2, axis=-1)
        med = np.median(d2)
        gamma = 1.0 / (2.0 * med + 1e-9) if med > 0 else 1.0
    d2 = np.sum((X[:, None, :] - Y[None, :, :]) ** 2, axis=-1)
    return np.exp(-gamma * d2)


def mmd_loss(Xs: np.ndarray, Xt: np.ndarray, *, gamma: float | None = None) -> float:
    """Unbiased MMD^2 with an RBF kernel (small, stable implementation)."""
    Xs = _as_2d(Xs)
    Xt = _as_2d(Xt)
    Kxx = _rbf_kernel(Xs, Xs, gamma=gamma)
    Kyy = _rbf_kernel(Xt, Xt, gamma=gamma)
    Kxy = _rbf_kernel(Xs, Xt, gamma=gamma)

    # remove diagonal for unbiased estimate
    np.fill_diagonal(Kxx, 0.0)
    np.fill_diagonal(Kyy, 0.0)

    m = max(len(Xs), 1)
    n = max(len(Xt), 1)

    term_x = Kxx.sum() / (m * (m - 1) + 1e-9)
    term_y = Kyy.sum() / (n * (n - 1) + 1e-9)
    term_xy = 2.0 * Kxy.mean()
    return float(term_x + term_y - term_xy)


def apply_coral(Xs: np.ndarray, Xt: np.ndarray, *, eps: float = 1e-6) -> tuple[np.ndarray, np.ndarray]:
    """Transform source features to match target covariance (CORAL)."""
    Xs = _as_2d(Xs)
    Xt = _as_2d(Xt)

    mu_s = Xs.mean(axis=0, keepdims=True)
    mu_t = Xt.mean(axis=0, keepdims=True)

    Xs0 = Xs - mu_s
    Xt0 = Xt - mu_t

    Cs = np.cov(Xs0, rowvar=False) + eps * np.eye(Xs.shape[1])
    Ct = np.cov(Xt0, rowvar=False) + eps * np.eye(Xt.shape[1])

    # Cs^{-1/2}
    ws, vs = np.linalg.eigh(Cs)
    ws = np.maximum(ws, eps)
    Cs_inv_sqrt = (vs * (1.0 / np.sqrt(ws)) ) @ vs.T

    # Ct^{1/2}
    wt, vt = np.linalg.eigh(Ct)
    wt = np.maximum(wt, eps)
    Ct_sqrt = (vt * np.sqrt(wt)) @ vt.T

    A = Cs_inv_sqrt @ Ct_sqrt
    Xs_coral = Xs0 @ A + mu_t
    return Xs_coral.astype(np.float32), Xt.astype(np.float32)


def apply_mmd(Xs: np.ndarray, Xt: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Very small 'MMD-style' alignment (mean matching).

    Full kernel mean matching is heavier; for our use (robustness + thesis
    experiments), mean matching is a decent baseline and keeps this repo
    dependency-light.
    """
    Xs = _as_2d(Xs)
    Xt = _as_2d(Xt)
    mu_s = Xs.mean(axis=0, keepdims=True)
    mu_t = Xt.mean(axis=0, keepdims=True)
    Xs_shift = Xs - mu_s + mu_t
    return Xs_shift.astype(np.float32), Xt.astype(np.float32)
