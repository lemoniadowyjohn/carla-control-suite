# ultimate_pipeline/domain_gap/qms.py

from __future__ import annotations
from typing import Dict, Optional


class QualityOfMapScore:
    """
    Quality of Map Score (QMS)

    A single scalar in [0, 1] summarizing overall map quality.

    Interpretation:
        1.0 → perfect match to reference (manual / ground truth)
        0.0 → unusable / extremely divergent map

    Combines normalized *gap metrics* where:
        0.0 = no gap (ideal)
        1.0 = very large gap (worst case)

    IMPORTANT:
        All input metrics must already be normalized to [0, 1].
    """

    # ------------------------------------------------------------------
    # Weight definition
    # ------------------------------------------------------------------
    #
    # Weights reflect *perception relevance* and *geometric primacy*:
    #   - curvature & lane widths strongly affect routing + perception
    #   - intersections matter for topology & behavior
    #   - elevation is secondary but non-negligible
    #
    WEIGHTS: Dict[str, float] = {
        "lane_width_gap": 0.20,
        "curvature_gap": 0.25,
        "building_density_gap": 0.20,
        "road_length_ratio": 0.10,
        "intersection_gap": 0.15,
        "elevation_gap": 0.10,
    }

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    @staticmethod
    def compute(
        metrics: Dict[str, float],
        *,
        strict: bool = False,
    ) -> float:
        """
        Compute the Quality-of-Map Score.

        Parameters
        ----------
        metrics:
            Dictionary of normalized gap metrics in [0,1].

        strict:
            If True:
                missing metrics raise an exception.
            If False (default):
                missing metrics are ignored and weights re-normalized.

        Returns
        -------
        float
            QMS score in [0,1], higher = better.
        """

        score = 0.0
        weight_sum = 0.0

        for key, weight in QualityOfMapScore.WEIGHTS.items():
            if key not in metrics:
                if strict:
                    raise KeyError(f"Missing required metric: '{key}'")
                continue

            gap = metrics[key]

            # Clamp defensively (protect against numerical drift)
            gap = max(0.0, min(1.0, float(gap)))

            # Convert gap → quality contribution
            quality = 1.0 - gap

            score += weight * quality
            weight_sum += weight

        if weight_sum == 0.0:
            return 0.0

        return score / weight_sum

    # ------------------------------------------------------------------
    # Diagnostics / Explainability
    # ----------------------------------------------------------------
