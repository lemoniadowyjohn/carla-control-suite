# ultimate_pipeline/domain_gap/correlator.py

from __future__ import annotations
from typing import Dict, List, Tuple
import numpy as np

class MetricCorrelator:
    """
    Correlate structural metrics with perception metrics.
    """

    @staticmethod
    def corr(x: List[float], y: List[float]) -> float:
        if len(x) < 2:
            return 0.0
        return float(np.corrcoef(x, y)[0, 1])

    @staticmethod
    def correlate_tile_metrics(
        tile_gap: Dict[str, Dict[str, float]],
        tile_perf: Dict[str, float],
        metric: str
    ) -> float:
        xs = []
        ys = []

        for tile_id, gaps in tile_gap.items():
            if metric not in gaps:
                continue
            if tile_id not in tile_perf:
                continue

            xs.append(gaps[metric])
            ys.append(tile_perf[tile_id])

        return MetricCorrelator.corr(xs, ys)
