import numpy as np

from carla_map_quality_toolkit.metrics import directed_hausdorff, symmetric_hausdorff


def test_hausdorff_known_offset() -> None:
    a = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])
    b = a + np.array([0.0, 0.25])
    assert abs(directed_hausdorff(a, b) - 0.25) < 1e-12
    assert abs(symmetric_hausdorff(a, b) - 0.25) < 1e-12
