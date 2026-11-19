"""F2 calibration adversarial oracle (V135, test-only).

Compares source calibration-derived mounts against the frozen independent
CARLA 0.9.16 oracle values copied from
tests/unit/test_calibration_independent_oracle.py. Oracle expectations are
literal values (never recomputed from the conversion helper). Mutations are
applied to source cTv/vTl inputs and must be detected (rejected or diverge
from the literal oracle). This is mathematical/transform consistency evidence
only; it does NOT constitute physical placement proof.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from ultimate_pipeline.sensors.calibration_contract import canonical_calib_path
from ultimate_pipeline.sensors.transform_conventions import (
    carla_attachment_pose_from_matrix,
    carla_ego_from_camera_from_cTv,
    carla_ego_from_lidar_from_vTl,
)

# Literal independent oracle copied from calibration_independent_oracle.py
# (real_oracle_out.json / CARLA 0.9.16 Transform.get_matrix(), no server).
ORACLE = {
    "back_left_camera": ((-0.5388611397777358, -0.2631893997338302, 1.0718703874486006), (0.01544035322517583, -162.2254684574427, 0.629589336007815), (-0.9522651482377785, -0.30527203414253, 0.0002694849981884796)),
    "left_camera": ((-0.4999548739693182, -0.6973344544446333, 0.9008052347847882), (0.06700618365383686, -91.7004901160345, 0.17784502699072127), (-0.02967477416471678, -0.9995589227748803, 0.0011694782573767409)),
    "front_left_camera": ((-0.23655050256222285, -0.027298066529018734, 1.0096191828547874), (1.5032907697774553, -20.885326232183058, 0.1758982024241827), (0.9339742402070143, -0.3563760328772288, 0.026234363350747296)),
    "front_right_camera": ((-0.4289313244823816, -0.022945953345353653, 1.1019697899709158), (0.2025709240686571, 18.95697755841441, 0.2475133554697216), (0.945756861702275, 0.32485605831758474, 0.0035355222281414113)),
    "right_camera": ((-0.6220107931269805, 0.6428943079758415, 0.8679538168973812), (-0.42174187492117854, 89.79731362029901, 0.1745224586868356), (0.0035374414629851447, 0.9999666526143507, -0.007360717841800901)),
    "back_right_camera": ((0.29447339730973365, -0.22058083332513145, 1.0065038118451608), (0.62183546005185, 159.56252943336798, -0.6830495621073278), (-0.9369986413673767, 0.34916437595742933, 0.010852863122173088)),
    "middle_lidar": ((-0.4920734, 0.00429731, 1.24068573), (0.17105050128399174, 90.66813962297327, -0.2837316978159381), (-0.01166092, 0.99992755, 0.00298539)),
}
EXPECTED_SHA256 = "d3ff2660b11ca56d16c6185e82d1b4c7fa94c5db27bb3469558442d79f4e97d9"


def _load_calibration() -> dict:
    return json.loads(canonical_calib_path().read_text(encoding="utf-8"))


def _derived_mounts(calibration: dict) -> dict[str, np.ndarray]:
    mounts = {}
    for name, camera in calibration["cameras"].items():
        mounts[name] = carla_ego_from_camera_from_cTv(camera["cTv"])
    mounts["middle_lidar"] = carla_ego_from_lidar_from_vTl(
        calibration["lidars"]["middle_lidar"]["vTl"]
    )
    return mounts


def _matches_oracle(name: str, mount: np.ndarray, pos_atol: float = 1e-3, ang_atol: float = 0.01) -> bool:
    expected_position, expected_pyr, expected_forward = ORACLE[name]
    if not np.allclose(mount[:3, 3], expected_position, atol=pos_atol, rtol=0):
        return False
    pose = carla_attachment_pose_from_matrix(mount)
    if not np.allclose([pose["pitch"], pose["yaw"], pose["roll"]], expected_pyr, atol=ang_atol, rtol=0):
        return False
    if not np.allclose(mount[:3, 0], expected_forward, atol=1e-3, rtol=0):
        return False
    return True


def test_positive_frozen_calibration_matches_literal_oracle():
    data = canonical_calib_path().read_bytes()
    assert hashlib.sha256(data).hexdigest() == EXPECTED_SHA256
    calibration = json.loads(data)
    mounts = _derived_mounts(calibration)
    assert set(mounts) == set(ORACLE)
    for name, mount in mounts.items():
        assert _matches_oracle(name, mount), f"{name} diverged from literal oracle"
        assert math.isclose(float(np.linalg.det(mount[:3, :3])), 1.0, abs_tol=1e-6)


_CAMERA_NAMES = [name for name in ORACLE if name != "middle_lidar"]


@pytest.mark.parametrize("camera_name", sorted(_CAMERA_NAMES))
def test_camera_axis_inversion_detected(camera_name):
    cal = _load_calibration()
    ctv = np.array(cal["cameras"][camera_name]["cTv"], dtype=float)
    # Invert optical forward axis in source camera frame (corrupts cTv meaning).
    ctv[:3, 2] *= -1.0
    cal["cameras"][camera_name]["cTv"] = ctv.tolist()
    try:
        mount = carla_ego_from_camera_from_cTv(cal["cameras"][camera_name]["cTv"])
    except Exception:
        return  # fail-closed rejection is acceptable detection
    assert not _matches_oracle(camera_name, mount)


def test_camera_left_right_swapped_detected():
    cal = _load_calibration()
    left_ctv = cal["cameras"]["left_camera"]["cTv"]
    right_ctv = cal["cameras"]["right_camera"]["cTv"]
    cal["cameras"]["left_camera"]["cTv"] = right_ctv
    cal["cameras"]["right_camera"]["cTv"] = left_ctv
    mounts = _derived_mounts(cal)
    assert not _matches_oracle("left_camera", mounts["left_camera"])
    assert not _matches_oracle("right_camera", mounts["right_camera"])


@pytest.mark.parametrize("camera_name", ["front_left_camera", "right_camera"])
def test_camera_reflected_handedness_rejected_or_detected(camera_name):
    cal = _load_calibration()
    ctv = np.array(cal["cameras"][camera_name]["cTv"], dtype=float)
    # Reflect one axis of the rotation block -> det becomes -1 (nonrigid/reflected).
    ctv[:3, 0] *= -1.0
    cal["cameras"][camera_name]["cTv"] = ctv.tolist()
    with pytest.raises(Exception):
        carla_ego_from_camera_from_cTv(cal["cameras"][camera_name]["cTv"])


@pytest.mark.parametrize("camera_name", ["front_left_camera", "back_left_camera"])
def test_camera_wrong_yaw_pitch_roll_sign_effect_detected(camera_name):
    cal = _load_calibration()
    ctv = np.array(cal["cameras"][camera_name]["cTv"], dtype=float)
    # Negate off-diagonal rotation terms to emulate sign-flipped angular components
    # in the source transform while preserving a valid rotation structure attempt.
    rot = ctv[:3, :3].copy()
    mutated = rot.copy()
    mutated[0, 1] = -mutated[0, 1]
    mutated[1, 0] = -mutated[1, 0]
    mutated[0, 2] = -mutated[0, 2]
    mutated[2, 0] = -mutated[2, 0]
    ctv[:3, :3] = mutated
    cal["cameras"][camera_name]["cTv"] = ctv.tolist()
    try:
        mount = carla_ego_from_camera_from_cTv(cal["cameras"][camera_name]["cTv"])
    except Exception:
        return
    assert not _matches_oracle(camera_name, mount)


@pytest.mark.parametrize("camera_name", ["front_right_camera", "left_camera"])
def test_camera_clamped_transform_detected(camera_name):
    cal = _load_calibration()
    ctv = np.array(cal["cameras"][camera_name]["cTv"], dtype=float)
    # Clamp/zero translation to simulate a degenerate clamped mount.
    ctv[:3, 3] = 0.0
    cal["cameras"][camera_name]["cTv"] = ctv.tolist()
    mount = carla_ego_from_camera_from_cTv(cal["cameras"][camera_name]["cTv"])
    assert not _matches_oracle(camera_name, mount)


def test_back_right_camera_anomaly_detected():
    cal = _load_calibration()
    # Swap back_right orientation intent with front_right while keeping position,
    # producing a wrong facing direction for the rear-right sensor.
    br = np.array(cal["cameras"]["back_right_camera"]["cTv"], dtype=float)
    fr = np.array(cal["cameras"]["front_right_camera"]["cTv"], dtype=float)
    br[:3, :3] = fr[:3, :3]
    cal["cameras"]["back_right_camera"]["cTv"] = br.tolist()
    mount = carla_ego_from_camera_from_cTv(cal["cameras"]["back_right_camera"]["cTv"])
    assert not _matches_oracle("back_right_camera", mount)
    # Literal oracle says back_right faces rearward (negative forward x).
    assert ORACLE["back_right_camera"][2][0] < 0.0


@pytest.mark.parametrize("offset", [[0.10, 0.0, 0.0], [0.0, 0.10, 0.0], [0.0, 0.0, 0.10]])
def test_vehicle_origin_offset_detected(offset):
    cal = _load_calibration()
    name = "front_left_camera"
    ctv = np.array(cal["cameras"][name]["cTv"], dtype=float)
    # Misapply a vehicle-origin offset in the source translation.
    ctv[:3, 3] = ctv[:3, 3] + np.array(offset, dtype=float)
    cal["cameras"][name]["cTv"] = ctv.tolist()
    mount = carla_ego_from_camera_from_cTv(cal["cameras"][name]["cTv"])
    assert not _matches_oracle(name, mount)


def test_middle_lidar_translation_mutation_detected():
    cal = _load_calibration()
    vtl = np.array(cal["lidars"]["middle_lidar"]["vTl"], dtype=float)
    vtl[2, 3] += 0.20  # lift LiDAR mount
    cal["lidars"]["middle_lidar"]["vTl"] = vtl.tolist()
    mount = carla_ego_from_lidar_from_vTl(cal["lidars"]["middle_lidar"]["vTl"])
    assert not _matches_oracle("middle_lidar", mount)


def test_middle_lidar_reflected_handedness_rejected():
    cal = _load_calibration()
    vtl = np.array(cal["lidars"]["middle_lidar"]["vTl"], dtype=float)
    vtl[:3, 1] *= -1.0
    cal["lidars"]["middle_lidar"]["vTl"] = vtl.tolist()
    with pytest.raises(Exception):
        carla_ego_from_lidar_from_vTl(cal["lidars"]["middle_lidar"]["vTl"])
