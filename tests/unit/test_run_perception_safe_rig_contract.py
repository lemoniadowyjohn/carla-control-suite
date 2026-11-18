"""ultimate_pipeline/tools/run_perception_safe.py::_rig_verification_contract_errors --
validates the sensor-rig calibration contract (cTv/vTl inversion conventions, per-sensor
applied-transform completeness) that gates whether captured perception evidence is trustworthy.
The thesis itself cites this as a contribution ("sensor-rig capability proofs under a unified,
mathematically verified calibration contract"). run_perception_safe.py is 6,576 lines and mostly
CARLA-dependent -- this pass targets only this one pure, safety-critical function rather than
attempting broad coverage of the whole file (found via the orphaned-.pyc sweep: 8 different
test_run_perception_safe*.py variants existed at some point, none currently on this branch).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from ultimate_pipeline.tools.run_perception_safe import _rig_verification_contract_errors
from ultimate_pipeline.carla_tools.thesis_sensor_rig import ThesisSensorRig
from ultimate_pipeline.sensors.transform_conventions import (
    camera_attachment_matrix_from_cTv,
    lidar_attachment_matrix_from_vTl,
    matrix_to_unreal_pose,
)

_CALIB_PATH = Path(__file__).resolve().parents[2] / "ultimate_pipeline" / "sensors" / "calib_data.json"
_CALIB_SHA256 = hashlib.sha256(_CALIB_PATH.read_bytes()).hexdigest()


def _valid_verification(sensor_names=("rgb_front_left_camera",)):
    calibration = json.loads(_CALIB_PATH.read_text(encoding="utf-8"))
    sensors = {}
    applied_sensors = {}
    for name in sensor_names:
        is_lidar = "lidar" in name
        sensor_type = "lidar" if is_lidar else "camera"
        source_name = name.removeprefix("lidar_").removeprefix("rgb_").removeprefix("seg_")
        source = calibration["lidars" if is_lidar else "cameras"][source_name]
        matrix = (
            lidar_attachment_matrix_from_vTl(source["vTl"])
            if is_lidar
            else camera_attachment_matrix_from_cTv(source["cTv"])
        )
        sensors[name] = {
            "type": sensor_type,
            "mounting_ctv_inverted": not is_lidar,
            "mounting_vtl_inverted": False,
            "mounting_matrix_sensor_to_vehicle_carla": matrix.tolist(),
        }
        applied_sensors[name] = {"relative_to_vehicle": matrix_to_unreal_pose(matrix)}
    return {
        "cTv_inverted": False,
        "vTl_inverted": True,
        "use_K_undistortion_only": True,
        "sensors": sensors,
        "sensor_contract": {
            "legacy_v1_flags_scope": "projection_backprojection_only",
            "carla_attachment_semantics": "v2",
            "camera_mounting": "S_vehicle @ inverse(cTv) @ C_CARLA_camera_to_OpenCV",
            "lidar_mounting": "S_vehicle @ vTl @ S_lidar",
            "calib_sha256": _CALIB_SHA256,
            "calib_path": str(_CALIB_PATH.resolve()),
            "live_reprojection_verified": False,
        },
        "applied_carla_transforms": {"sensors": applied_sensors},
    }


def test_fully_valid_contract_has_no_errors():
    assert _rig_verification_contract_errors(_valid_verification()) == []


def test_self_consistent_forged_camera_mount_is_rejected():
    v = _valid_verification()
    forged = np.eye(4).tolist()
    v["sensors"]["rgb_front_left_camera"]["mounting_matrix_sensor_to_vehicle_carla"] = forged
    v["applied_carla_transforms"]["sensors"]["rgb_front_left_camera"]["relative_to_vehicle"] = (
        matrix_to_unreal_pose(np.eye(4))
    )

    errors = _rig_verification_contract_errors(v)

    assert any("disagrees with digest-bound calibration" in error for error in errors)


def test_self_consistent_forged_lidar_mount_is_rejected():
    v = _valid_verification(sensor_names=("lidar_middle_lidar",))
    forged = np.eye(4).tolist()
    v["sensors"]["lidar_middle_lidar"]["mounting_matrix_sensor_to_vehicle_carla"] = forged
    v["applied_carla_transforms"]["sensors"]["lidar_middle_lidar"]["relative_to_vehicle"] = (
        matrix_to_unreal_pose(np.eye(4))
    )

    errors = _rig_verification_contract_errors(v)

    assert any("disagrees with digest-bound calibration" in error for error in errors)


def test_producer_digest_is_bound_to_bytes_used_to_load_mounts(tmp_path):
    source_bytes = _CALIB_PATH.read_bytes()
    selected_path = tmp_path / "calib.json"
    selected_path.write_bytes(source_bytes)
    rig = ThesisSensorRig(selected_path)
    loaded_digest = hashlib.sha256(source_bytes).hexdigest()

    # A formatting-only edit changes the file identity without changing the
    # sensor matrices already held by the rig instance.
    selected_path.write_bytes(source_bytes + b"\n")
    spawned = rig.build_spawned_from_calib_defaults()
    receipt = rig.build_rig_verification(spawned).to_dict()

    assert receipt["sensor_contract"]["calib_sha256"] == loaded_digest
    errors = _rig_verification_contract_errors(receipt)
    assert "v2 calibration source digest does not match source file" in errors


def test_calibration_digest_must_match_source_file():
    v = _valid_verification()
    v["sensor_contract"]["calib_sha256"] = "0" * 64
    errors = _rig_verification_contract_errors(v)
    assert "v2 calibration source digest does not match source file" in errors


def test_calibration_source_path_is_required():
    v = _valid_verification()
    del v["sensor_contract"]["calib_path"]
    errors = _rig_verification_contract_errors(v)
    assert "v2 calibration source path is missing or invalid" in errors


def test_mounting_convention_strings_are_authoritative():
    v = _valid_verification()
    v["sensor_contract"]["camera_mounting"] = "wrong camera convention"
    v["sensor_contract"]["lidar_mounting"] = "wrong lidar convention"
    errors = _rig_verification_contract_errors(v)
    assert "v2 camera mounting convention is missing or invalid" in errors
    assert "v2 LiDAR mounting convention is missing or invalid" in errors


def test_ctv_inverted_true_is_an_error():
    v = _valid_verification()
    v["cTv_inverted"] = True
    errors = _rig_verification_contract_errors(v)
    assert "legacy v1 cTv_inverted must be explicitly false" in errors


def test_ctv_inverted_missing_is_an_error():
    v = _valid_verification()
    del v["cTv_inverted"]
    errors = _rig_verification_contract_errors(v)
    assert "legacy v1 cTv_inverted must be explicitly false" in errors


def test_ctv_inverted_accepts_lowercase_key_fallback():
    v = _valid_verification()
    del v["cTv_inverted"]
    v["ctv_inverted"] = False  # lowercase fallback key
    errors = _rig_verification_contract_errors(v)
    assert "legacy v1 cTv_inverted must be explicitly false" not in errors


def test_vtl_inverted_false_is_an_error():
    v = _valid_verification()
    v["vTl_inverted"] = False
    errors = _rig_verification_contract_errors(v)
    assert "legacy v1 vTl_inverted must be explicitly true" in errors


def test_vtl_inverted_accepts_lowercase_key_fallback():
    v = _valid_verification()
    del v["vTl_inverted"]
    v["vtl_inverted"] = True
    errors = _rig_verification_contract_errors(v)
    assert "legacy v1 vTl_inverted must be explicitly true" not in errors


def test_use_k_undistortion_only_not_true_is_an_error():
    v = _valid_verification()
    v["use_K_undistortion_only"] = False
    errors = _rig_verification_contract_errors(v)
    assert "use_K_undistortion_only must be true" in errors


def test_sensors_missing_is_an_error():
    v = _valid_verification()
    del v["sensors"]
    errors = _rig_verification_contract_errors(v)
    assert "sensors must be a non-empty object" in errors


def test_sensors_empty_dict_is_an_error():
    v = _valid_verification()
    v["sensors"] = {}
    errors = _rig_verification_contract_errors(v)
    assert "sensors must be a non-empty object" in errors


def test_applied_carla_transforms_missing_is_an_error():
    v = _valid_verification()
    del v["applied_carla_transforms"]
    errors = _rig_verification_contract_errors(v)
    assert "applied_carla_transforms missing or invalid" in errors


def test_applied_transforms_sensors_missing_is_an_error():
    v = _valid_verification()
    v["applied_carla_transforms"] = {}
    errors = _rig_verification_contract_errors(v)
    assert "applied_carla_transforms.sensors missing or invalid" in errors


def test_sensor_missing_from_applied_transforms_names_it_in_the_error():
    v = _valid_verification(sensor_names=("rgb_front_left_camera", "lidar_middle_lidar"))
    del v["applied_carla_transforms"]["sensors"]["lidar_middle_lidar"]
    errors = _rig_verification_contract_errors(v)
    assert any("lidar_middle_lidar" in e for e in errors)
    assert not any("rgb_front_left_camera" in e for e in errors)


def test_sensor_missing_relative_to_vehicle_is_an_error():
    v = _valid_verification()
    del v["applied_carla_transforms"]["sensors"]["rgb_front_left_camera"]["relative_to_vehicle"]
    errors = _rig_verification_contract_errors(v)
    assert any("relative_to_vehicle" in e and "rgb_front_left_camera" in e for e in errors)


def test_multiple_independent_errors_all_accumulate():
    v = {
        "cTv_inverted": True, "vTl_inverted": False, "use_K_undistortion_only": False,
        "sensors": {}, "applied_carla_transforms": None,
    }
    errors = _rig_verification_contract_errors(v)
    # cTv, vTl, use_K, sensors, applied_carla_transforms, and (since resetting
    # applied_carla_transforms to {} still lacks a "sensors" key) applied_carla_transforms.
    # sensors -- 6 independent violations, none short-circuits the rest.
    assert any("cTv_inverted" in error for error in errors)
    assert any("vTl_inverted" in error for error in errors)
    assert any("sensors must be a non-empty object" in error for error in errors)
    assert any("applied_carla_transforms" in error for error in errors)


def test_missing_v2_semantics_and_improper_mounting_are_rejected():
    v = _valid_verification()
    v["sensor_contract"].pop("carla_attachment_semantics")
    v["sensors"]["rgb_front_left_camera"]["mounting_matrix_sensor_to_vehicle_carla"][0][0] = -1.0
    errors = _rig_verification_contract_errors(v)
    assert any("versioned v2" in error for error in errors)
    assert any("mounting matrix" in error for error in errors)
