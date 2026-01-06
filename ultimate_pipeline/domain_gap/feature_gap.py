from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import numpy as np
import matplotlib.pyplot as plt
from scipy import stats
from sklearn.metrics.pairwise import rbf_kernel


class FeatureDomainGap:
    """
    Unified feature-level domain gap analyzer.

    Provides multiple complementary metrics:
        - MMD (Maximum Mean Discrepancy, kernel-based)
        - Wasserstein distance (distributional shift)
        - Mean feature distance (first-order statistics)

    Design goals:
        - deterministic
        - robust to small / degenerate inputs
        - usable in ablation studies & HPC sweeps
        - interpretable for thesis examiners
    """

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def __init__(
        self,
        output_dir: str | Path = "./domain_gap_outputs",
        *,
        mmd_gamma: Optional[float] = None,
        eps: float = 1e-12,
    ):
        """
        Parameters
        ----------
        output_dir:
            Where visualizations will be saved

        mmd_gamma:
            RBF kernel gamma. If None, chosen automatically.

        eps:
            Numerical stability constant
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.mmd_gamma = mmd_gamma
        self.eps = eps

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_array(x: Any) -> np.ndarray:
        """
        Convert input to a 2D numpy array.

        Supported inputs:
            - list
            - tuple
            - numpy array
            - dict (values used)
        """
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

    # ------------------------------------------------------------------
    # Core metrics
    # ------------------------------------------------------------------

    def mmd(self, X: Any, Y: Any) -> float:
        """
        Maximum Mean Discrepancy with RBF kernel.

        Returns a non-negative scalar.
        """
        X = self._ensure_array(X)
        Y = self._ensure_array(Y)

        if len(X) == 0 or len(Y) == 0:
            return 0.0

        # Automatic gamma heuristic if not provided
        if self.mmd_gamma is None:
            gamma = 1.0 / max(X.shape[1], 1)
        else:
            gamma = self.mmd_gamma

        K_xx = rbf_kernel(X, X, gamma=gamma)
        K_yy = rbf_kernel(Y, Y, gamma=gamma)
        K_xy = rbf_kernel(X, Y, gamma=gamma)

        mmd2 = K_xx.mean() + K_yy.mean() - 2.0 * K_xy.mean()

        # Numerical safety
        return float(max(0.0, mmd2))

    def wasserstein(self, X: Any, Y: Any) -> float:
        """
        1D Wasserstein distance (Earth Mover's Distance).

        If inputs are multi-dimensional, they are flattened.
        """
        X = self._ensure_array(X).ravel()
        Y = self._ensure_array(Y).ravel()

        if len(X) == 0 or len(Y) == 0:
            return 0.0

        return float(stats.wasserstein_distance(X, Y))

    def mean_gap(self, X: Any, Y: Any) -> float:
        """
        Euclidean distance between feature means.
        """
        X = self._ensure_array(X)
        Y = self._ensure_array(Y)

        mu_x = self._safe_mean(X)
        mu_y = self._safe_mean(Y)

        return float(np.linalg.norm(mu_x - mu_y))

    # ------------------------------------------------------------------
    # Unified interface
    # ------------------------------------------------------------------

    def compute(
        self,
        source: Any,
        target: Any,
    ) -> Dict[str, float]:
        """
        Compute all feature-level domain gap metrics.
        """
        return {
            "mmd": self.mmd(source, target),
            "wasserstein": self.wasserstein(source, target),
            "mean_gap": self.mean_gap(source, target),
        }

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------

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
        """
        Plot feature distribution comparison.

        Parameters
        ----------
        feature_index:
            Which feature dimension to plot (if multi-dim)

        show:
            If True, calls plt.show()
        """
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
