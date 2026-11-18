"""Regression tests for digest-bound CARLA mounting evidence in the submission mirror."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from ultimate_pipeline.sensors.transform_conventions import (
    camera_attachment_matrix_from_cTv,
    lidar_attachment_matrix_from_vTl,
    matrix_to_unreal_pose,
)
from ultimate_pipeline.carla_tools.thesis_sensor_rig import ThesisSensorRig
from ultimate_pipeline.tools.run_perception_safe import _rig_verification_contract_errors


_CALIB_PATH = Path(__file__).resolve().parents[1] / "sensors" / "calib_data.json"


def _valid_verification(sensor_name: str, sensor_type: str) -> dict:
    calibration = json.loads(_CALIB_PATH.read_text(encoding="utf-8"))
    source_name = sensor_name.removeprefix("rgb_").removeprefix("lidar_")
    source = calibration["cameras" if sensor_type == "camera" else "lidars"][source_name]
    matrix = (
        camera_attachment_matrix_from_cTv(source["cTv"])
        if sensor_type == "camera"
        else lidar_attachment_matrix_from_vTl(source["vTl"])
    )
    return {
        "cTv_inverted": False,
        "vTl_inverted": True,
        "use_K_undistortion_only": True,
        "sensor_contract": {
            "carla_attachment_semantics": "v2",
            "legacy_v1_flags_scope": "projection_backprojection_only",
            "camera_mounting": "S_vehicle @ inverse(cTv) @ C_CARLA_camera_to_OpenCV",
            "lidar_mounting": "S_vehicle @ vTl @ S_lidar",
            "calib_sha256": hashlib.sha256(_CALIB_PATH.read_bytes()).hexdigest(),
            "calib_path": str(_CALIB_PATH.resolve()),
            "live_reprojection_verified": False,
        },
        "sensors": {
            sensor_name: {
                "type": sensor_type,
                "mounting_ctv_inverted": sensor_type == "camera",
                "mounting_vtl_inverted": False,
                "mounting_matrix_sensor_to_vehicle_carla": matrix.tolist(),
            }
        },
        "applied_carla_transforms": {
            "sensors": {
                sensor_name: {"relative_to_vehicle": matrix_to_unreal_pose(matrix)}
            }
        },
    }


@pytest.mark.parametrize(
    ("sensor_name", "sensor_type"),
    (("rgb_front_left_camera", "camera"), ("lidar_middle_lidar", "lidar")),
)
def test_self_consistent_forged_mount_cannot_pass(
    sensor_name: str, sensor_type: str
) -> None:
    evidence = _valid_verification(sensor_name, sensor_type)
    forged = np.eye(4)
    evidence["sensors"][sensor_name]["mounting_matrix_sensor_to_vehicle_carla"] = forged.tolist()
    evidence["applied_carla_transforms"]["sensors"][sensor_name]["relative_to_vehicle"] = (
        matrix_to_unreal_pose(forged)
    )

    errors = _rig_verification_contract_errors(evidence)

    assert any("disagrees with digest-bound calibration" in error for error in errors)


def test_producer_digest_uses_the_loaded_calibration_snapshot(tmp_path: Path) -> None:
    source_bytes = _CALIB_PATH.read_bytes()
    selected_path = tmp_path / "calib.json"
    selected_path.write_bytes(source_bytes)
    rig = ThesisSensorRig(selected_path)
    loaded_digest = hashlib.sha256(source_bytes).hexdigest()

    selected_path.write_bytes(source_bytes + b"\n")
    spawned = rig.build_spawned_from_calib_defaults()
    receipt = rig.build_rig_verification(spawned).to_dict()

    assert receipt["sensor_contract"]["calib_sha256"] == loaded_digest
    errors = _rig_verification_contract_errors(receipt)
    assert "v2 calibration source digest does not match source file" in errors
