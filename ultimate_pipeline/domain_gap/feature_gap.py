from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")  # headless backend: this system's default (tkagg) needs a display
import matplotlib.pyplot as plt
from scipy import stats

# ---------------------------------------------------------------------------
# Optional dependency: scikit-learn
# ---------------------------------------------------------------------------
# The original implementation imported:
#   from sklearn.metrics.pairwise import rbf_kernel
# which breaks environments where sklearn is not installed.
#
# We provide a NumPy fallback with identical semantics for this use case.
try:
    from sklearn.metrics.pairwise import rbf_kernel as _sk_rbf_kernel  # type: ignore
except Exception:  # pragma: no cover
    _sk_rbf_kernel = None


def rbf_kernel(X: np.ndarray, Y: np.ndarray, gamma: float) -> np.ndarray:
    """RBF (Gaussian) kernel: exp(-gamma * ||x-y||^2)."""
    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)

    if _sk_rbf_kernel is not None:
        return _sk_rbf_kernel(X, Y, gamma=gamma)

    # NumPy fallback: ||x-y||^2 = ||x||^2 + ||y||^2 - 2 x·y
    X_norm = np.sum(X * X, axis=1).reshape(-1, 1)  # (n,1)
    Y_norm = np.sum(Y * Y, axis=1).reshape(1, -1)  # (1,m)
    sq_dists = X_norm + Y_norm - 2.0 * (X @ Y.T)
    sq_dists = np.maximum(sq_dists, 0.0)  # numerical safety
    return np.exp(-gamma * sq_dists)


class FeatureDomainGap:
    """Unified feature-level domain gap analyzer (sklearn optional)."""

    def __init__(
        self,
        output_dir: str | Path = "./domain_gap_outputs",
        *,
        mmd_gamma: Optional[float] = None,
        eps: float = 1e-12,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.mmd_gamma = mmd_gamma
        self.eps = eps

    @staticmethod
    def _ensure_array(x: Any) -> np.ndarray:
        if isinstance(x, dict):
            x = list(x.values())
        arr = np.asarray(x, dtype=float)
        if arr.ndim == 0:
            arr = arr.reshape(1, 1)
        elif arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        return arr

    @staticmethod
    def _safe_mean(arr: np.ndarray) -> np.ndarray:
        if arr.size == 0:
            return np.zeros((arr.shape[1],))
        return arr.mean(axis=0)

    def mmd(self, X: Any, Y: Any) -> float:
        X = self._ensure_array(X)
        Y = self._ensure_array(Y)
        if len(X) == 0 or len(Y) == 0:
            return 0.0

        gamma = self.mmd_gamma if self.mmd_gamma is not None else (1.0 / max(X.shape[1], 1))

        K_xx = rbf_kernel(X, X, gamma=gamma)
        K_yy = rbf_kernel(Y, Y, gamma=gamma)
        K_xy = rbf_kernel(X, Y, gamma=gamma)

        mmd2 = K_xx.mean() + K_yy.mean() - 2.0 * K_xy.mean()
        return float(max(0.0, mmd2))

    def wasserstein(self, X: Any, Y: Any) -> float:
        X = self._ensure_array(X).ravel()
        Y = self._ensure_array(Y).ravel()
        if len(X) == 0 or len(Y) == 0:
            return 0.0
        return float(stats.wasserstein_distance(X, Y))

    def mean_gap(self, X: Any, Y: Any) -> float:
        X = self._ensure_array(X)
        Y = self._ensure_array(Y)
        mu_x = self._safe_mean(X)
        mu_y = self._safe_mean(Y)
        return float(np.linalg.norm(mu_x - mu_y))

    def compute(self, source: Any, target: Any) -> Dict[str, float]:
        return {
            "mmd": self.mmd(source, target),
            "wasserstein": self.wasserstein(source, target),
            "mean_gap": self.mean_gap(source, target),
        }

    def visualize(
        self,
        source: Any,
        target: Any,
        *,
        label_source: str = "source",
        label_target: str = "target",
        feature_index: int = 0,
        bins: int = 40,
        out_path: Optional[str | Path] = None,
        show: bool = False,
    ) -> Optional[str]:
        X = self._ensure_array(source)
        Y = self._ensure_array(target)

        fi = min(feature_index, X.shape[1] - 1, Y.shape[1] - 1)
        xs = X[:, fi]
        ys = Y[:, fi]

        plt.figure(figsize=(10, 5))
        plt.hist(xs, bins=bins, alpha=0.6, label=label_source, density=True)
        plt.hist(ys, bins=bins, alpha=0.6, label=label_target, density=True)
        plt.xlabel(f"Feature {fi}")
        plt.ylabel("Density")
        plt.title("Feature Distribution Comparison")
        plt.legend()
        plt.tight_layout()

        if out_path:
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(out_path, dpi=200)
            plt.close()
            return str(out_path)

        if show:
            plt.show()
        else:
            plt.close()
        return None


# Backwards-compatible alias
FeatureGap = FeatureDomainGap
