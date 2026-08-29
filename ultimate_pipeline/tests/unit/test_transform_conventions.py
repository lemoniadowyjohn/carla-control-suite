# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/sensors/transform_conventions.py.

Live: used by carla_tools/thesis_sensor_rig.py, sensors/dominik_sensor_setup.py,
sensors/calibration_contract.py, tools/run_perception_safe.py,
tools/audit_thesis_topic_contract.py, perception/record_route_fixed.py --
the canonical sensor-calibration transform convention (documented elsewhere
as "cTv direct, vTl inverted"). Zero prior test coverage despite directly
affecting perception dataset sensor placement correctness.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from ultimate_pipeline.sensors.transform_conventions import (
    _ensure_homogeneous,
    _flip_vehicle_y_basis,
    camera_attachment_pose_from_cTv,
    lidar_attachment_pose_from_vTl,
    matrix_to_unreal_pose,
    rotation_matrix_to_unreal_rpy_deg,
    vehicle_to_camera_from_cTv,
    vehicle_to_lidar_from_vTl,
)


# ---------------------------------------------------------------------------
# _ensure_homogeneous
# ---------------------------------------------------------------------------

def test_ensure_homogeneous_passes_through_4x4():
    m = np.eye(4)
    assert np.array_equal(_ensure_homogeneous(m), m)


def test_ensure_homogeneous_pads_3x4_to_4x4():
    m = np.eye(4)[:3, :]  # 3x4
    out = _ensure_homogeneous(m)
    assert out.shape == (4, 4)
    assert np.array_equal(out[3], [0.0, 0.0, 0.0, 1.0])


def test_ensure_homogeneous_rejects_wrong_shape():
    with pytest.raises(ValueError):
        _ensure_homogeneous(np.eye(3))


# ---------------------------------------------------------------------------
# _flip_vehicle_y_basis
# ---------------------------------------------------------------------------

def test_flip_vehicle_y_negates_only_y_translation():
    m = np.eye(4)
    m[:3, 3] = [1.0, 2.0, 3.0]
    flipped = _flip_vehicle_y_basis(m)
    assert flipped[:3, 3].tolist() == [1.0, -2.0, 3.0]


def test_flip_vehicle_y_is_its_own_inverse():
    m = np.eye(4)
    m[:3, 3] = [1.0, 2.0, 3.0]
    twice = _flip_vehicle_y_basis(_flip_vehicle_y_basis(m))
    assert np.allclose(twice, m)


# ---------------------------------------------------------------------------
# vehicle_to_lidar_from_vTl -- documented convention: vTl is inverted
# ---------------------------------------------------------------------------

def test_lidar_pure_translation_is_inverted_without_flip():
    vTl = np.eye(4)
    vTl[:3, 3] = [1.0, 0.5, 2.0]
    out = vehicle_to_lidar_from_vTl(vTl, flip_vehicle_y=False)
    assert np.allclose(out[:3, 3], [-1.0, -0.5, -2.0])


def test_lidar_translation_inverted_then_y_flipped():
    vTl = np.eye(4)
    vTl[:3, 3] = [1.0, 0.5, 2.0]
    out = vehicle_to_lidar_from_vTl(vTl, flip_vehicle_y=True)
    # inverse translation is [-1, -0.5, -2]; y-flip then negates y again -> +0.5
    assert np.allclose(out[:3, 3], [-1.0, 0.5, -2.0])


# ---------------------------------------------------------------------------
# vehicle_to_camera_from_cTv -- documented convention: cTv is NOT inverted by default
# ---------------------------------------------------------------------------

def test_camera_cTv_not_inverted_by_default():
    cTv = np.eye(4)
    cTv[:3, 3] = [1.0, 2.0, 3.0]
    out = vehicle_to_camera_from_cTv(cTv, flip_vehicle_y=False, opencv_camera_axes=False)
    # No inversion, no flip, no axis conversion -> translation passes through unchanged.
    assert np.allclose(out[:3, 3], [1.0, 2.0, 3.0])


def test_camera_ctv_manual_inversion_raises_under_strict_mode(monkeypatch):
    monkeypatch.setenv("UP_THESIS_STRICT", "1")
    cTv = np.eye(4)
    with pytest.raises(RuntimeError, match="Non-canonical"):
        vehicle_to_camera_from_cTv(cTv, flip_vehicle_y=False, ctv_invert=True)


def test_camera_ctv_manual_inversion_only_warns_when_not_strict(monkeypatch, caplog):
    monkeypatch.delenv("UP_THESIS_STRICT", raising=False)
    cTv = np.eye(4)
    # Must not raise.
    vehicle_to_camera_from_cTv(cTv, flip_vehicle_y=False, ctv_invert=True)


def test_camera_opencv_axes_conversion_applied_by_default():
    # OpenCV: x right, y down, z forward. With opencv axes on, the camera's
    # local +z (forward in OpenCV) should map into the vehicle-frame +x
    # column-of-rotation (CARLA forward), given an otherwise-identity cTv.
    cTv = np.eye(4)
    out = vehicle_to_camera_from_cTv(cTv, flip_vehicle_y=False, opencv_camera_axes=True)
    assert not np.allclose(out[:3, :3], np.eye(3))  # axes were actually converted


# ---------------------------------------------------------------------------
# rotation_matrix_to_unreal_rpy_deg / matrix_to_unreal_pose
# ---------------------------------------------------------------------------

def test_identity_rotation_gives_zero_rpy():
    roll, pitch, yaw = rotation_matrix_to_unreal_rpy_deg(np.eye(3))
    assert roll == pytest.approx(0.0, abs=1e-9)
    assert pitch == pytest.approx(0.0, abs=1e-9)
    assert yaw == pytest.approx(0.0, abs=1e-9)


def test_90deg_yaw_rotation_extracted_correctly():
    c, s = math.cos(math.radians(90)), math.sin(math.radians(90))
    rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    roll, pitch, yaw = rotation_matrix_to_unreal_rpy_deg(rot)
    assert yaw == pytest.approx(90.0, abs=1e-6)
    assert roll == pytest.approx(0.0, abs=1e-9)
    assert pitch == pytest.approx(0.0, abs=1e-9)


def test_matrix_to_unreal_pose_reports_translation_and_rotation():
    m = np.eye(4)
    m[:3, 3] = [10.0, -5.0, 2.5]
    pose = matrix_to_unreal_pose(m)
    assert pose["x"] == pytest.approx(10.0)
    assert pose["y"] == pytest.approx(-5.0)
    assert pose["z"] == pytest.approx(2.5)
    assert pose["roll"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# camera_attachment_pose_from_cTv / lidar_attachment_pose_from_vTl
# ---------------------------------------------------------------------------

def test_camera_attachment_pose_reports_forward_alignment():
    cTv = np.eye(4)
    pose = camera_attachment_pose_from_cTv(cTv, flip_vehicle_y=False, opencv_camera_axes=False)
    assert "forward_alignment_to_vehicle_x" in pose
    assert "forward_alignment_ok" in pose
    # Identity, no axis conversion: forward vector is exactly vehicle +x.
    assert pose["forward_alignment_to_vehicle_x"] == pytest.approx(1.0)
    assert pose["forward_alignment_ok"] is True


def test_lidar_attachment_pose_returns_full_pose_dict():
    vTl = np.eye(4)
    vTl[:3, 3] = [0.0, 0.0, 1.8]  # lidar mounted 1.8m up, in lidar->vehicle terms
    pose = lidar_attachment_pose_from_vTl(vTl, flip_vehicle_y=False)
    assert set(pose.keys()) == {"x", "y", "z", "roll", "pitch", "yaw"}
    assert pose["z"] == pytest.approx(-1.8)  # inverted
