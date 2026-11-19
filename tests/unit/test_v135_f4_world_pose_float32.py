"""F4 float32 precision/oracle tests at realistic world poses (V135, test-only).

Characterizes numeric error envelopes for observed_parent_relative_mount() and
_residuals() when CARLA-like world transforms are float32-quantized at large
translations. Does not change acceptance tolerances or claim live runtime
evidence. Source-requested vs trusted mount comparison (2e-6 in applied_sensor_rig
validation) is distinct from observed float32 runtime reconstruction.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from ultimate_pipeline.sensors.applied_sensor_rig import (
    ANGULAR_RESIDUAL_LIMIT_DEG,
    POSITION_RESIDUAL_LIMIT_M,
    _residuals,
    _rigid_matrix,
    observed_parent_relative_mount,
)


class _FakeCarlaTransform:
    def __init__(self, matrix: np.ndarray):
        # Simulate CARLA float32-backed world transform values.
        self._matrix = np.asarray(matrix, dtype=np.float32).astype(np.float64)

    def get_matrix(self):
        return self._matrix.copy()


def _rot_z(deg: float) -> np.ndarray:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)


def _rot_y(deg: float) -> np.ndarray:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=np.float64)


def _rot_x(deg: float) -> np.ndarray:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=np.float64)


def _pose(tx, ty, tz, R=None):
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = np.eye(3) if R is None else R
    T[:3, 3] = [tx, ty, tz]
    return T


def _relative_mount(tx, ty, tz, R=None):
    return _pose(tx, ty, tz, R)


@pytest.mark.parametrize("world_t", [0.0, 1.0e3, 1.0e4])
@pytest.mark.parametrize(
    "ego_R",
    [
        np.eye(3),
        _rot_z(33.0),
        _rot_z(33.0) @ _rot_y(-4.0) @ _rot_x(2.0),
    ],
)
def test_observed_mount_float32_quantization_envelope(world_t, ego_R):
    # Known sensor mount relative to ego (typical camera offset).
    mount = _relative_mount(0.35, -0.12, 1.45, _rot_z(5.0) @ _rot_y(-1.0))
    ego = _pose(world_t, -world_t * 0.3, 12.0, ego_R)
    sensor = ego @ mount
    observed = observed_parent_relative_mount(
        _FakeCarlaTransform(ego), _FakeCarlaTransform(sensor)
    )
    residual = _residuals(mount, observed)
    # Quantify: should remain well within runtime residual limits for these cases.
    assert residual["position_m"] <= POSITION_RESIDUAL_LIMIT_M
    assert residual["angle_deg"] <= ANGULAR_RESIDUAL_LIMIT_DEG
    # Record envelope implicitly via strict-but-safe bounds at large coordinates.
    if world_t >= 1.0e4:
        assert residual["position_m"] < 5e-3
        assert residual["angle_deg"] < 5e-2


def test_near_zero_rotation_residual_stable():
    mount = _relative_mount(0.2, 0.0, 1.2, _rot_z(0.001) @ _rot_y(0.0005))
    ego = _pose(5000.0, 5000.0, 0.0, _rot_z(91.0))
    sensor = ego @ mount
    observed = observed_parent_relative_mount(
        _FakeCarlaTransform(ego), _FakeCarlaTransform(sensor)
    )
    residual = _residuals(mount, observed)
    assert residual["position_m"] < 2e-3
    assert residual["angle_deg"] < 2e-2


def test_large_rotation_rollover_angle_computed_safely():
    # ~179 degrees rotation (near rollover region for naive acos formulations).
    mount = _relative_mount(0.1, 0.05, 1.3, _rot_z(179.0))
    ego = _pose(1000.0, -2000.0, 5.0, _rot_z(-45.0))
    sensor = ego @ mount
    observed = observed_parent_relative_mount(
        _FakeCarlaTransform(ego), _FakeCarlaTransform(sensor)
    )
    residual = _residuals(mount, observed)
    assert math.isfinite(residual["angle_deg"])
    assert residual["angle_deg"] < 1.0  # float32 quantization, not a 179deg error


@pytest.mark.parametrize(
    "dpos,dang,should_exceed_pos,should_exceed_ang",
    [
        (0.009, 0.0, False, False),   # just inside position boundary
        (0.011, 0.0, True, False),    # just outside position boundary
        (0.0, 0.09, False, False),    # just inside angle boundary
        (0.0, 0.11, False, True),     # just outside angle boundary
    ],
)
def test_boundary_0_01m_0_1deg_behavior(dpos, dang, should_exceed_pos, should_exceed_ang):
    req = _relative_mount(0.3, 0.0, 1.4, np.eye(3))
    obs = _relative_mount(0.3 + dpos, 0.0, 1.4, _rot_z(dang))
    residual = _residuals(req, obs)
    assert (residual["position_m"] > POSITION_RESIDUAL_LIMIT_M) is should_exceed_pos
    assert (residual["angle_deg"] > ANGULAR_RESIDUAL_LIMIT_DEG) is should_exceed_ang


def test_source_requested_vs_trusted_tolerance_is_distinct_from_runtime():
    # 2e-6 is the exact source-calibration mount match tolerance in validation;
    # runtime observed residual limits are 0.01m/0.1deg (different contract).
    assert POSITION_RESIDUAL_LIMIT_M == 0.01
    assert ANGULAR_RESIDUAL_LIMIT_DEG == 0.1
    base = _relative_mount(0.2, -0.1, 1.0, np.eye(3))
    tiny = base.copy()
    tiny[0, 3] += 1e-6
    residual = _residuals(base, tiny)
    assert residual["position_m"] < 2e-6  # within exact-source class


@pytest.mark.parametrize(
    "bad_matrix",
    [
        np.array([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float),  # reflection
        np.array([[2, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float),  # nonrigid scale
    ],
)
def test_reflected_and_nonrigid_matrices_rejected(bad_matrix):
    good = np.eye(4)
    with pytest.raises(ValueError):
        _rigid_matrix(bad_matrix, label="bad")
    with pytest.raises(ValueError):
        _residuals(good, bad_matrix)
    with pytest.raises(ValueError):
        _residuals(bad_matrix, good)


@pytest.mark.parametrize(
    "bad_value",
    [
        np.array([[1, 0, 0, np.nan], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float),
        np.array([[1, 0, 0, np.inf], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float),
    ],
)
def test_nan_inf_rejected(bad_value):
    with pytest.raises(ValueError):
        _rigid_matrix(bad_value, label="bad")


def test_invalid_homogeneous_row_rejected():
    bad = np.eye(4)
    bad[3, 0] = 1.0
    with pytest.raises(ValueError):
        _rigid_matrix(bad, label="bad")
