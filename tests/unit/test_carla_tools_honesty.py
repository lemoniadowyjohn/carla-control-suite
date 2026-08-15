from __future__ import annotations

import math

import numpy as np
import pytest


def test_fixed_tm_strict_no_carla_raises(monkeypatch):
    from ultimate_pipeline.carla_tools import fixed_traffic_manager as ftm

    monkeypatch.setattr(ftm, "CARLA_AVAILABLE", False)
    monkeypatch.setenv("UP_THESIS_STRICT", "1")
    monkeypatch.delenv("UP_ALLOW_MOCK_TRAFFIC_MANAGER", raising=False)

    with pytest.raises(RuntimeError, match="CARLA unavailable"):
        ftm.create_traffic_manager()


def test_fixed_tm_no_carla_requires_explicit_mock_flag(monkeypatch):
    from ultimate_pipeline.carla_tools import fixed_traffic_manager as ftm

    monkeypatch.setattr(ftm, "CARLA_AVAILABLE", False)
    monkeypatch.delenv("UP_THESIS_STRICT", raising=False)
    monkeypatch.delenv("UP_ALLOW_MOCK_TRAFFIC_MANAGER", raising=False)

    with pytest.raises(RuntimeError, match="UP_ALLOW_MOCK_TRAFFIC_MANAGER"):
        ftm.create_traffic_manager()


def test_fixed_tm_dev_mock_emits_not_evidence_marker(monkeypatch, capsys):
    from ultimate_pipeline.carla_tools import fixed_traffic_manager as ftm

    monkeypatch.setattr(ftm, "CARLA_AVAILABLE", False)
    monkeypatch.delenv("UP_THESIS_STRICT", raising=False)
    monkeypatch.setenv("UP_ALLOW_MOCK_TRAFFIC_MANAGER", "1")

    tm = ftm.create_traffic_manager()
    assert getattr(tm, "is_mock", False) is True
    assert tm.initialize(None, None) is True
    assert tm.spawn_vehicles(3) == 0
    assert tm.spawn_pedestrians(2) == 0
    status = tm.get_traffic_status()

    captured = capsys.readouterr().out
    assert "MOCK - NOT REAL EVIDENCE" in captured
    assert status["mock"] is True
    assert status["evidence_valid"] is False


def _rzyx(*, roll: float = 0.0, pitch: float = 0.0, yaw: float = 0.0) -> np.ndarray:
    r = math.radians(roll)
    p = math.radians(pitch)
    y = math.radians(yaw)
    rx = np.array(
        [[1.0, 0.0, 0.0], [0.0, math.cos(r), -math.sin(r)], [0.0, math.sin(r), math.cos(r)]]
    )
    ry = np.array(
        [[math.cos(p), 0.0, math.sin(p)], [0.0, 1.0, 0.0], [-math.sin(p), 0.0, math.cos(p)]]
    )
    rz = np.array(
        [[math.cos(y), -math.sin(y), 0.0], [math.sin(y), math.cos(y), 0.0], [0.0, 0.0, 1.0]]
    )
    return rz @ ry @ rx


def test_sensor_rig_rotation_extraction_known_zyx_angles(monkeypatch):
    monkeypatch.setenv("UP_SILENCE_DEPRECATIONS", "1")
    from ultimate_pipeline.carla_tools.sensor_rig import rotation_matrix_to_carla_euler_degrees

    matrix = np.eye(4)
    matrix[:3, :3] = _rzyx(roll=7.0, pitch=-11.0, yaw=23.0)
    pitch, yaw, roll = rotation_matrix_to_carla_euler_degrees(matrix)

    assert abs(pitch - (-11.0)) < 1e-6
    assert abs(yaw - 23.0) < 1e-6
    assert abs(roll - 7.0) < 1e-6


def test_sensor_rig_rotation_extraction_rejects_bad_shape_under_strict(monkeypatch):
    monkeypatch.setenv("UP_SILENCE_DEPRECATIONS", "1")
    from ultimate_pipeline.carla_tools.sensor_rig import rotation_matrix_to_carla_euler_degrees

    monkeypatch.setenv("UP_THESIS_STRICT", "1")
    with pytest.raises(ValueError, match="4x4"):
        rotation_matrix_to_carla_euler_degrees(np.eye(3))
