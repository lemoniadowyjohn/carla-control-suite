from __future__ import annotations

import math

import pytest

from tests.opendrive_geometry.adapters import NON_BUGGY_ADAPTERS
from tests.opendrive_geometry.analytical import arc_pose_at
from tests.opendrive_geometry.fixtures import make_fixture

NEAR_ZERO_CURVATURES = [
    0.0,
    1e-15,
    -1e-15,
    1e-14,
    -1e-14,
    1e-13,
    -1e-13,
    1e-12,
    -1e-12,
    1e-11,
    -1e-11,
    1e-10,
    -1e-10,
    1e-9,
    -1e-9,
]

S_VALUES = [0.0, 50.0, 100.0]


def _adapter_treats_as_line(adapter, k):
    eps = getattr(adapter, "eps", None)
    if eps is None:
        return False
    if abs(k) < eps:
        return True
    if abs(k) == eps and adapter.name in ("elevation_gap", "geo_alignment"):
        return True
    return False


@pytest.mark.parametrize("adapter", NON_BUGGY_ADAPTERS)
@pytest.mark.parametrize("k", NEAR_ZERO_CURVATURES)
@pytest.mark.parametrize("s", S_VALUES)
def test_near_zero_curvature(adapter, k, s):
    length = 100.0
    fx = make_fixture(length=length, curvature=k)
    expected = arc_pose_at(fx, s)
    result = adapter.evaluate(fx.x, fx.y, fx.hdg, fx.length, k, s)
    if abs(k) < 1e-15:
        tol = 1e-12
    elif _adapter_treats_as_line(adapter, k):
        tol = max(1e-12, abs(k) * s + 1e-12)
    else:
        tol = 1e-12
    for field, exp_val, res_val in [("x", expected.x, result.x), ("y", expected.y, result.y), ("hdg", expected.hdg, result.hdg)]:
        assert abs(res_val - exp_val) < tol, (
            f"{adapter.name} (eps={adapter.eps}) k={k:.0e} s={s}: "
            f"{field} {res_val} != {exp_val} (tol={tol:.0e})"
        )

