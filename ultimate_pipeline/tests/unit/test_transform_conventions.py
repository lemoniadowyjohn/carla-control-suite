"""Regression tests for explicit CARLA_SENSOR_MOUNTING/v2 frame semantics."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from ultimate_pipeline.sensors.transform_conventions import (
    CALIBRATION_CONTRACT_VERSION,
    carla_attachment_pose_from_matrix,
    carla_ego_from_camera_from_cTv,
    carla_ego_from_lidar_from_vTl,
    carla_rotation_matrix_to_rpy_deg,
    camera_attachment_pose_from_cTv,
    vehicle_to_camera_from_cTv,
)


ROOT = Path(__file__).resolve().parents[2]
CALIB = json.loads((ROOT / "sensors" / "calib_data.json").read_text(encoding="utf-8"))
ORACLE = json.loads(
    (ROOT / "tests" / "fixtures" / "v127" / "sensor_frame_oracle.json").read_text(
        encoding="utf-8"
    )
)
S4 = np.diag([1.0, -1.0, 1.0, 1.0])
CARLA_CAMERA_TO_OPENCV = np.eye(4)
CARLA_CAMERA_TO_OPENCV[:3, :3] = np.array(
    [[0.0, 1.0, 0.0], [0.0, 0.0, -1.0], [1.0, 0.0, 0.0]]
)


def _oracle_mount(name: str, modality: str) -> np.ndarray:
    row = ORACLE[name]
    source_from_sensor = np.eye(4)
    source_from_sensor[:3, :3] = np.asarray(row["R"], dtype=float)
    source_from_sensor[:3, 3] = np.asarray(row["pos"], dtype=float)
    if modality == "camera":
        return S4 @ source_from_sensor @ CARLA_CAMERA_TO_OPENCV
    return S4 @ source_from_sensor @ S4


@pytest.mark.parametrize("name", sorted(CALIB["cameras"]))
def test_all_camera_mounts_match_independent_full_matrix_oracle(name):
    actual = carla_ego_from_camera_from_cTv(CALIB["cameras"][name]["cTv"])
    expected = _oracle_mount(name, "camera")
    assert np.allclose(actual, expected, atol=2e-5, rtol=0), name
    assert np.linalg.det(actual[:3, :3]) == pytest.approx(1.0, abs=1e-7)
    assert np.allclose(actual[:3, :3].T @ actual[:3, :3], np.eye(3), atol=1e-7)


@pytest.mark.parametrize("name", sorted(CALIB["lidars"]))
def test_all_declared_lidar_mounts_match_independent_full_matrix_oracle(name):
    actual = carla_ego_from_lidar_from_vTl(CALIB["lidars"][name]["vTl"])
    expected = _oracle_mount(name, "lidar")
    assert np.allclose(actual, expected, atol=2e-5, rtol=0), name
    assert np.linalg.det(actual[:3, :3]) == pytest.approx(1.0, abs=1e-7)


def test_independently_reconstructed_wrong_candidates_are_rejected_by_oracle():
    ctv = np.asarray(CALIB["cameras"]["front_left_camera"]["cTv"], dtype=float)
    vtl = np.asarray(CALIB["lidars"]["middle_lidar"]["vTl"], dtype=float)
    expected_camera = _oracle_mount("front_left_camera", "camera")
    expected_lidar = _oracle_mount("middle_lidar", "lidar")
    wrong_camera_direct = S4 @ ctv @ CARLA_CAMERA_TO_OPENCV
    wrong_camera_single_handedness = ctv.copy()
    wrong_lidar_inverse = S4 @ np.linalg.inv(vtl) @ S4
    assert np.max(np.abs(wrong_camera_direct - expected_camera)) > 1e-2
    assert np.max(np.abs(wrong_camera_single_handedness - expected_camera)) > 1e-2
    assert np.max(np.abs(wrong_lidar_inverse - expected_lidar)) > 1e-2


def test_required_source_position_oracles_and_explicit_carla_basis_conversion():
    camera_source = np.asarray(ORACLE["front_left_camera"]["pos"])
    lidar_source = np.asarray(ORACLE["middle_lidar"]["pos"])
    assert camera_source == pytest.approx(
        [-0.23655050256222285, +0.027298066529018734, 1.0096191828547874], abs=1e-9
    )
    assert lidar_source == pytest.approx(
        [-0.4920734, -0.00429731, 1.24068573], abs=1e-8
    )
    camera = carla_ego_from_camera_from_cTv(CALIB["cameras"]["front_left_camera"]["cTv"])
    lidar = carla_ego_from_lidar_from_vTl(CALIB["lidars"]["middle_lidar"]["vTl"])
    assert camera[:3, 3] == pytest.approx([-0.236550502562, -0.027298066529, 1.009619182855], abs=1e-9)
    assert lidar[:3, 3] == pytest.approx([-0.4920734, +0.00429731, 1.24068573], abs=1e-8)


def test_reflected_nonorthogonal_nonfinite_and_malformed_source_transforms_fail_closed():
    valid = np.eye(4)
    reflected = valid.copy()
    reflected[1, 1] = -1
    scaled = valid.copy()
    scaled[0, 0] = 1.01
    nonfinite = valid.copy()
    nonfinite[0, 3] = np.nan
    for invalid in (reflected, scaled, nonfinite, np.eye(3)):
        with pytest.raises(ValueError):
            carla_ego_from_camera_from_cTv(invalid)
        with pytest.raises(ValueError):
            carla_ego_from_lidar_from_vTl(invalid)


def test_unsupported_legacy_convention_switches_are_rejected():
    with pytest.raises(ValueError, match="inverse"):
        vehicle_to_camera_from_cTv(np.eye(4), ctv_invert=True)
    with pytest.raises(ValueError, match="OpenCV"):
        vehicle_to_camera_from_cTv(np.eye(4), opencv_camera_axes=False)


def test_rotation_extraction_uses_carla_positive_pitch_and_roll_signs():
    import carla

    for roll, pitch, yaw in ((0, 51, 0), (51, 0, 0), (120, -35, 87), (180, 20, -90)):
        source = carla.Transform(carla.Location(), carla.Rotation(roll=roll, pitch=pitch, yaw=yaw))
        matrix = np.asarray(source.get_matrix(), dtype=float)[:3, :3]
        extracted = carla_rotation_matrix_to_rpy_deg(matrix)
        reconstructed = carla.Transform(
            carla.Location(), carla.Rotation(roll=extracted[0], pitch=extracted[1], yaw=extracted[2])
        )
        assert np.allclose(
            np.asarray(reconstructed.get_matrix(), dtype=float)[:3, :3],
            matrix,
            atol=2e-6,
            rtol=0,
        ), (roll, pitch, yaw, extracted)

    positive_pitch = carla.Rotation(pitch=51).get_forward_vector()
    positive_roll = carla.Rotation(roll=51).get_right_vector()
    assert positive_pitch.z > 0
    assert positive_roll.z < 0


def test_carla_0916_rotation_matrix_reconstruction_randomized_client_only():
    import carla

    rng = np.random.default_rng(127)
    worst = 0.0
    for _ in range(200):
        roll = float(rng.uniform(-180.0, 180.0))
        pitch = float(rng.uniform(-89.0, 89.0))
        yaw = float(rng.uniform(-180.0, 180.0))
        source = carla.Transform(
            carla.Location(),
            carla.Rotation(roll=roll, pitch=pitch, yaw=yaw),
        )
        source_matrix = np.asarray(source.get_matrix(), dtype=float)[:3, :3]
        rr, rp, ry = carla_rotation_matrix_to_rpy_deg(source_matrix)
        reconstructed = carla.Transform(
            carla.Location(), carla.Rotation(roll=rr, pitch=rp, yaw=ry)
        )
        error = float(
            np.max(
                np.abs(
                    np.asarray(reconstructed.get_matrix(), dtype=float)[:3, :3]
                    - source_matrix
                )
            )
        )
        worst = max(worst, error)
        assert error < 2e-6, (roll, pitch, yaw, error)
    assert worst < 2e-6


def test_carla_0916_matrix_reconstruction_matches_all_mounts_and_basis_vectors():
    import carla

    names = [(n, "camera", carla_ego_from_camera_from_cTv(row["cTv"])) for n, row in CALIB["cameras"].items()]
    names += [(n, "lidar", carla_ego_from_lidar_from_vTl(row["vTl"])) for n, row in CALIB["lidars"].items()]
    max_matrix_error = 0.0
    max_axis_angle_deg = 0.0
    for name, modality, expected in names:
        pose = carla_attachment_pose_from_matrix(expected)
        transform = carla.Transform(
            carla.Location(x=pose["x"], y=pose["y"], z=pose["z"]),
            carla.Rotation(roll=pose["roll"], pitch=pose["pitch"], yaw=pose["yaw"]),
        )
        reconstructed = np.asarray(transform.get_matrix(), dtype=float)
        matrix_error = float(np.max(np.abs(reconstructed - expected)))
        max_matrix_error = max(max_matrix_error, matrix_error)
        assert matrix_error < 2e-6, (name, modality, matrix_error)
        basis = (transform.rotation.get_forward_vector(), transform.rotation.get_right_vector(), transform.rotation.get_up_vector())
        for col, vector in enumerate(basis):
            observed_axis = np.array([vector.x, vector.y, vector.z], dtype=float)
            expected_axis = expected[:3, col]
            cross_norm = float(np.linalg.norm(np.cross(observed_axis, expected_axis)))
            dot = float(np.clip(observed_axis @ expected_axis, -1.0, 1.0))
            angle = math.degrees(math.atan2(cross_norm, dot))
            max_axis_angle_deg = max(max_axis_angle_deg, angle)
            assert angle < 0.01, (name, modality, col, angle)
    assert max_matrix_error < 2e-6
    assert max_axis_angle_deg < 0.01


@pytest.mark.parametrize("angle", [51, 90, 120, 180])
@pytest.mark.parametrize("axis", ["roll", "pitch", "yaw"])
def test_position_sanitizers_never_clamp_valid_sensor_rotation(axis, angle):
    import carla
    from ultimate_pipeline.carla_tools.thesis_sensor_rig import _sanitize_transform
    from ultimate_pipeline.sensors.dominik_sensor_setup import _sanitize_transform_dict

    values = {"x": 0.2, "y": -0.3, "z": 1.1, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}
    values[axis] = float(angle)
    pose, changed = _sanitize_transform_dict(values)
    assert changed == []
    assert pose[axis] == pytest.approx(float(angle))
    sanitized = _sanitize_transform(
        carla.Transform(
            carla.Location(x=values["x"], y=values["y"], z=values["z"]),
            carla.Rotation(roll=values["roll"], pitch=values["pitch"], yaw=values["yaw"]),
        )
    )
    assert getattr(sanitized.rotation, axis) == pytest.approx(float(angle))


def test_position_sanitizers_reject_invalid_values_instead_of_substituting_zero():
    import carla
    from ultimate_pipeline.carla_tools.thesis_sensor_rig import _sanitize_transform
    from ultimate_pipeline.sensors.dominik_sensor_setup import _sanitize_transform_dict

    with pytest.raises(ValueError, match="missing"):
        _sanitize_transform_dict({"x": 1.0})
    bad = {"x": 0.0, "y": 0.0, "z": 1.0, "roll": float("nan"), "pitch": 0.0, "yaw": 0.0}
    with pytest.raises(ValueError, match="non-finite"):
        _sanitize_transform_dict(bad)
    with pytest.raises(ValueError, match="exceeds 50"):
        _sanitize_transform_dict({**bad, "roll": 0, "x": 51})
    with pytest.raises(ValueError, match="non-finite"):
        _sanitize_transform(carla.Transform(carla.Location(), carla.Rotation(pitch=float("nan"))))
    with pytest.raises(ValueError, match="exceeds"):
        _sanitize_transform(carla.Transform(carla.Location(x=51), carla.Rotation(pitch=180)))


def test_deprecated_pose_adapter_reports_explicit_v2_mount():
    pose = camera_attachment_pose_from_cTv(CALIB["cameras"]["front_left_camera"]["cTv"])
    assert pose["contract_version"] == CALIBRATION_CONTRACT_VERSION
    assert np.allclose(
        pose["mount_matrix"],
        carla_ego_from_camera_from_cTv(CALIB["cameras"]["front_left_camera"]["cTv"]),
        atol=1e-10,
        rtol=0,
    )


@pytest.mark.parametrize(
    "name,modality",
    [(name, "camera") for name in sorted(CALIB["cameras"])]
    + [("middle_lidar", "lidar")],
)
def test_three_sensor_spawn_adapters_emit_identical_carla_mounts(tmp_path, name, modality):
    import carla
    from ultimate_pipeline.carla_tools.thesis_sensor_rig import _pose_to_carla_transform
    from ultimate_pipeline.sensors.attach_sensors_safe import _carla_transform_from_vehicle_to_sensor
    from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup

    calib_path = ROOT / "sensors" / "calib_data.json"
    setup = DominikSensorSetup(str(calib_path))
    if modality == "camera":
        source = CALIB["cameras"][name]["cTv"]
        expected = carla_ego_from_camera_from_cTv(source)
        dom_pose = setup._parse_camera_transform(CALIB["cameras"][name])
        attach_tf = _carla_transform_from_vehicle_to_sensor(source, camera_optical_frame=True)
    else:
        source = CALIB["lidars"][name]["vTl"]
        expected = carla_ego_from_lidar_from_vTl(source)
        dom_pose = setup._parse_lidar_transform(CALIB["lidars"][name])
        attach_tf = _carla_transform_from_vehicle_to_sensor(source, camera_optical_frame=False)
    dom_tf = carla.Transform(
        carla.Location(x=dom_pose["x"], y=dom_pose["y"], z=dom_pose["z"]),
        carla.Rotation(roll=dom_pose["roll"], pitch=dom_pose["pitch"], yaw=dom_pose["yaw"]),
    )
    thesis_tf, _ = _pose_to_carla_transform(carla_attachment_pose_from_matrix(expected))
    for actual in (dom_tf, thesis_tf, attach_tf):
        assert np.allclose(np.asarray(actual.get_matrix()), expected, atol=2e-6, rtol=0)


@pytest.mark.parametrize(
    "name,modality",
    [(name, "camera") for name in sorted(CALIB["cameras"])]
    + [(name, "lidar") for name in sorted(CALIB["lidars"])],
)
def test_generated_map_sensor_spawns_use_authoritative_v2_mount(name, modality):
    import carla
    from ultimate_pipeline.carla_tools.evaluate_generated_map import (
        camera_transform_from_cTv,
        lidar_transform_from_vTl,
    )

    if modality == "camera":
        source = CALIB["cameras"][name]["cTv"]
        expected = carla_ego_from_camera_from_cTv(source)
        actual = camera_transform_from_cTv(source)
    else:
        source = CALIB["lidars"][name]["vTl"]
        expected = carla_ego_from_lidar_from_vTl(source)
        actual = lidar_transform_from_vTl(source)
    assert isinstance(actual, carla.Transform)
    assert np.allclose(np.asarray(actual.get_matrix()), expected, atol=2e-6, rtol=0)


def test_generated_map_sensor_spawns_reject_unsupported_frame_overrides():
    from ultimate_pipeline.carla_tools.evaluate_generated_map import (
        camera_transform_from_cTv,
        lidar_transform_from_vTl,
    )

    with pytest.raises(ValueError, match="only CARLA_SENSOR_MOUNTING/v2"):
        camera_transform_from_cTv(CALIB["cameras"]["front_left_camera"]["cTv"], flip_vehicle_y=False)
    with pytest.raises(ValueError, match="only CARLA_SENSOR_MOUNTING/v2"):
        camera_transform_from_cTv(
            CALIB["cameras"]["front_left_camera"]["cTv"], opencv_camera_axes=False
        )
    with pytest.raises(ValueError, match="only CARLA_SENSOR_MOUNTING/v2"):
        lidar_transform_from_vTl(CALIB["lidars"]["middle_lidar"]["vTl"], flip_vehicle_y=False)


@pytest.mark.parametrize(
    "module_name",
    ["ultimate_pipeline.sensors.sweep_calib_setups", "ultimate_pipeline.tools.sweep_calib_setups"],
)
def test_calibration_sweep_matrix_conversion_preserves_carla_rotation(module_name):
    import importlib
    import carla

    module = importlib.import_module(module_name)
    source = carla.Transform(
        carla.Location(x=1.25, y=-0.75, z=2.0),
        carla.Rotation(roll=51.0, pitch=-37.0, yaw=120.0),
    )
    actual = module.mat4_to_carla_transform(source.get_matrix())
    assert np.allclose(actual.get_matrix(), source.get_matrix(), atol=2e-6, rtol=0)


@pytest.mark.parametrize(
    "module_name",
    ["ultimate_pipeline.sensors.sweep_calib_setups", "ultimate_pipeline.tools.sweep_calib_setups"],
)
def test_calibration_sweep_matrix_conversion_rejects_reflections(module_name):
    import importlib

    module = importlib.import_module(module_name)
    reflected = np.eye(4)
    reflected[1, 1] = -1.0
    with pytest.raises(ValueError, match="reflected or nonrigid"):
        module.mat4_to_carla_transform(reflected.tolist())


@pytest.mark.parametrize(
    "name,modality",
    [(name, "camera") for name in sorted(CALIB["cameras"])]
    + [("middle_lidar", "lidar")],
)
def test_visual_calibration_spawn_adapter_matches_authoritative_mount(name, modality):
    import carla
    from ultimate_pipeline.tools.visual_check_calib_setup import (
        camera_transform_from_cTv,
        lidar_transform_from_vTl,
    )

    if modality == "camera":
        source = CALIB["cameras"][name]["cTv"]
        expected = carla_ego_from_camera_from_cTv(source)
        actual = camera_transform_from_cTv(source)
    else:
        source = CALIB["lidars"][name]["vTl"]
        expected = carla_ego_from_lidar_from_vTl(source)
        actual = lidar_transform_from_vTl(source)
    assert isinstance(actual, carla.Transform)
    assert np.allclose(actual.get_matrix(), expected, atol=2e-6, rtol=0)


def test_dominik_matrix_pose_adapter_uses_carla_0916_rotation_extraction():
    import carla
    from ultimate_pipeline.sensors.dominik_sensor_setup import _matrix_to_transform

    source = carla.Transform(
        carla.Location(x=-0.4, y=0.3, z=1.2),
        carla.Rotation(roll=120.0, pitch=51.0, yaw=-90.0),
    )
    pose = _matrix_to_transform(np.asarray(source.get_matrix(), dtype=float))
    rebuilt = carla.Transform(
        carla.Location(x=pose["x"], y=pose["y"], z=pose["z"]),
        carla.Rotation(roll=pose["roll"], pitch=pose["pitch"], yaw=pose["yaw"]),
    )
    assert np.allclose(rebuilt.get_matrix(), source.get_matrix(), atol=2e-6, rtol=0)
