"""Independent CARLA 0.9.16 mounting oracle copied from Claude QA V128.

Expected poses are literal values emitted by oracle_scripts/cal/oracle/real_oracle.py
using the installed CARLA client Transform.get_matrix() (no server). The oracle
uses raw calib_data.json; these tests intentionally do not derive expected poses
with the repository transform converter.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from ultimate_pipeline.sensors.calibration_contract import canonical_calib_path
from ultimate_pipeline.sensors.transform_conventions import (
    carla_attachment_pose_from_matrix,
    carla_ego_from_camera_from_cTv,
    carla_ego_from_lidar_from_vTl,
)


# Position (m), CARLA pitch/yaw/roll (degrees), and CARLA forward/right/up
# vectors copied from the independent real_oracle_out.json matrices.
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


def test_source_calibration_and_active_sensor_set_are_frozen():
    data = canonical_calib_path().read_bytes()
    assert hashlib.sha256(data).hexdigest() == EXPECTED_SHA256
    calibration = json.loads(data)
    actual = set(calibration["cameras"]) | {"middle_lidar"}
    assert actual == set(ORACLE)
    assert "middle_lidar_old" not in actual


def test_raw_calibration_matches_independent_carla_0916_oracle():
    data = json.loads(canonical_calib_path().read_text(encoding="utf-8"))
    actual = {}
    for name, camera in data["cameras"].items():
        actual[name] = carla_ego_from_camera_from_cTv(camera["cTv"])
    actual["middle_lidar"] = carla_ego_from_lidar_from_vTl(data["lidars"]["middle_lidar"]["vTl"])

    assert set(actual) == set(ORACLE)
    for name, mount in actual.items():
        expected_position, expected_pyr, expected_forward = ORACLE[name]
        np.testing.assert_allclose(mount[:3, 3], expected_position, atol=1e-3, rtol=0)
        pose = carla_attachment_pose_from_matrix(mount)
        np.testing.assert_allclose(
            [pose["pitch"], pose["yaw"], pose["roll"]], expected_pyr, atol=0.01, rtol=0
        )
        np.testing.assert_allclose(mount[:3, 0], expected_forward, atol=1e-3, rtol=0)
        assert math.isclose(float(np.linalg.det(mount[:3, :3])), 1.0, abs_tol=1e-6)


def test_camera_names_agree_with_independent_forward_directions():
    for name, (_, _, forward) in ORACLE.items():
        if name == "middle_lidar":
            continue
        x, y, _ = forward
        if name.startswith("front_"):
            assert x > 0.0
        elif name.startswith("back_"):
            assert x < 0.0
        if "left" in name:
            assert y < 0.0  # CARLA right axis is +Y.
        elif "right" in name:
            assert y > 0.0
