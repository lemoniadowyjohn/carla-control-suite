import math

import numpy as np

from carla_map_quality_toolkit.alignment import SE2Transform, estimate_se2


def test_recover_known_se2_transform() -> None:
    source = np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 2.0], [1.0, 3.0]])
    truth = SE2Transform(angle_rad=math.radians(7.0), tx=4.0, ty=-2.5)
    target = truth.apply(source)
    fitted, rmse = estimate_se2(source, target)
    assert abs(fitted.angle_rad - truth.angle_rad) < 1e-10
    assert abs(fitted.tx - truth.tx) < 1e-10
    assert abs(fitted.ty - truth.ty) < 1e-10
    assert rmse < 1e-10
