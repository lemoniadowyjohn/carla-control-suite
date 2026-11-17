"""Regression tests: camera/LiDAR source transforms are not CARLA mounting poses.

The calibration vehicle and LiDAR axes are interpreted as right-handed FLU.
CARLA/Unreal axes are left-handed forward/right/up; camera optical coordinates
are OpenCV right/down/forward. These tests are purely geometric; they do NOT
constitute a live calibration or camera reprojection acceptance.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ultimate_pipeline.sensors.transform_conventions import (
    camera_attachment_matrix_from_cTv,
    lidar_attachment_matrix_from_vTl,
    camera_attachment_pose_from_cTv,
    lidar_attachment_pose_from_vTl,
    matrix_to_unreal_pose,
)

ROOT = Path(__file__).resolve().parents[2]
CALIB = ROOT / "ultimate_pipeline" / "sensors" / "calib_data.json"
FLIP = np.diag([1.0, -1.0, 1.0, 1.0])
CARLA_CAMERA_TO_OPENCV = np.eye(4)
CARLA_CAMERA_TO_OPENCV[:3, :3] = np.array(
    [[0., 1., 0.], [0., 0., -1.], [1., 0., 0.]]
)


def _calib():
    return json.loads(CALIB.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", [
    "front_left_camera", "front_right_camera", "back_left_camera",
    "back_right_camera", "left_camera", "right_camera",
])
def test_mounting_camera_poses_are_proper_and_projection_consistent(name):
    ctv = np.asarray(_calib()["cameras"][name]["cTv"], dtype=float)
    mount = camera_attachment_matrix_from_cTv(ctv)
    assert np.isclose(np.linalg.det(mount[:3, :3]), 1.0, atol=1e-6)
    np.testing.assert_allclose(
        ctv @ FLIP @ mount @ np.linalg.inv(CARLA_CAMERA_TO_OPENCV),
        np.eye(4), atol=1e-6,
    )
    # All six source calibrations place their cameras above the vehicle origin.
    assert 0.5 < mount[2, 3] < 2.5
    pose = camera_attachment_pose_from_cTv(
        ctv, flip_vehicle_y=False, opencv_camera_axes=True, ctv_invert=False
    )
    assert pose["z"] == pytest.approx(float(mount[2, 3]), abs=1e-6)
    assert pose["x"] == pytest.approx(float(mount[0, 3]), abs=1e-6)


def test_camera_left_right_correct_after_handedness_conversion():
    cam = _calib()["cameras"]
    left = camera_attachment_matrix_from_cTv(cam["left_camera"]["cTv"])
    right = camera_attachment_matrix_from_cTv(cam["right_camera"]["cTv"])
    assert left[1, 3] < 0.0  # CARLA +Y is right
    assert right[1, 3] > 0.0
    assert left[0, 0] < 0.5
    assert right[0, 0] < 0.5


def test_lidar_attachment_preserves_source_height_and_proper_rotation():
    vtl = np.asarray(_calib()["lidars"]["middle_lidar"]["vTl"], dtype=float)
    mount = lidar_attachment_matrix_from_vTl(vtl)
    assert float(mount[2, 3]) == pytest.approx(1.24068573)
    assert np.isclose(np.linalg.det(mount[:3, :3]), 1.0, atol=1e-5)
    np.testing.assert_allclose(FLIP @ mount @ FLIP, vtl, atol=1e-6)
    pose = lidar_attachment_pose_from_vTl(vtl, flip_vehicle_y=False)
    assert pose["z"] == pytest.approx(1.24068573)


def test_reflection_or_nonrigid_calibration_rejected():
    invalid = np.eye(4)
    invalid[1, 1] = -1
    with pytest.raises(ValueError, match="improper rotation"):
        camera_attachment_matrix_from_cTv(invalid)
    with pytest.raises(ValueError, match="improper rotation"):
        lidar_attachment_matrix_from_vTl(invalid)

    bad = np.eye(4)
    bad[0, 0] = 2
    with pytest.raises(ValueError, match="nonorthogonal"):
        camera_attachment_matrix_from_cTv(bad)


def test_legacy_flip_flag_is_noop_and_optical_basis_is_mandatory():
    ctv = np.asarray(_calib()["cameras"]["left_camera"]["cTv"])
    canonical = camera_attachment_pose_from_cTv(ctv, flip_vehicle_y=False)
    compat = camera_attachment_pose_from_cTv(ctv, flip_vehicle_y=True)
    for field in ("x", "y", "z", "roll", "pitch", "yaw"):
        assert compat[field] == pytest.approx(canonical[field])
    with pytest.raises(ValueError, match="cannot be disabled"):
        camera_attachment_pose_from_cTv(
            ctv, flip_vehicle_y=False, opencv_camera_axes=False
        )
