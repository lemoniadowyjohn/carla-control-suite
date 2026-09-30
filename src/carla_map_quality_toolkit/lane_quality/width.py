from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LaneWidthMetrics:
    mean_abs_deviation_m: float
    p95_abs_deviation_m: float
    max_abs_deviation_m: float
    violation_fraction: float


def compare_width_profiles(
    observed_widths: np.ndarray,
    reference_widths: np.ndarray,
    tolerance_m: float = 0.15,
) -> LaneWidthMetrics:
    observed = np.asarray(observed_widths, dtype=float)
    reference = np.asarray(reference_widths, dtype=float)
    if observed.shape != reference.shape or observed.ndim != 1 or len(observed) == 0:
        raise ValueError("width profiles must be non-empty 1D arrays with equal shape")
    if tolerance_m < 0:
        raise ValueError("tolerance_m must be non-negative")
    deviation = np.abs(observed - reference)
    return LaneWidthMetrics(
        mean_abs_deviation_m=float(np.mean(deviation)),
        p95_abs_deviation_m=float(np.percentile(deviation, 95)),
        max_abs_deviation_m=float(np.max(deviation)),
        violation_fraction=float(np.mean(deviation > tolerance_m)),
    )
