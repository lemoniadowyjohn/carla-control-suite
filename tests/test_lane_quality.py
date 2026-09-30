import numpy as np

from carla_map_quality_toolkit.lane_quality import compare_width_profiles


def test_lane_width_metrics_and_violation_fraction() -> None:
    ref = np.array([3.5, 3.5, 3.5, 3.5])
    obs = np.array([3.5, 3.6, 3.7, 3.5])
    metrics = compare_width_profiles(obs, ref, tolerance_m=0.15)
    assert abs(metrics.max_abs_deviation_m - 0.2) < 1e-12
    assert metrics.violation_fraction == 0.25
