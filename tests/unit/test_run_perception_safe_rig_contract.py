"""V2 applied-mount admission gate tests for the safe recorder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from ultimate_pipeline.sensors.applied_sensor_rig import build_applied_sensor_rig_v2
from ultimate_pipeline.sensors.transform_conventions import carla_ego_from_camera_from_cTv

_CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "ultimate_pipeline" / "sensors" / "calib_data.json"
_CALIBRATION_BYTES = _CALIBRATION_PATH.read_bytes()
_CALIBRATION_SHA256 = hashlib.sha256(_CALIBRATION_BYTES).hexdigest()
_CALIBRATION = json.loads(_CALIBRATION_BYTES.decode("utf-8"))
_CAMERA_NAME = "front_left_camera"
from ultimate_pipeline.tools.run_perception_safe import _rig_verification_contract_errors


def _valid_verification():
    mount = carla_ego_from_camera_from_cTv(_CALIBRATION["cameras"][_CAMERA_NAME]["cTv"])
    receipt = build_applied_sensor_rig_v2(
        source_calibration_sha256=_CALIBRATION_SHA256,
        code_commit="b" * 40,
        requested_parent_relative_matrices={_CAMERA_NAME: mount},
        ego_identity={"actor_id": 11, "type_id": "vehicle.test"},
        sensor_identities={_CAMERA_NAME: {"actor_id": 12, "type_id": "sensor.camera.rgb"}},
        blueprint_configuration={_CAMERA_NAME: {"blueprint_id": "sensor.camera.rgb", "attributes": {}}},
        effective_camera_configuration={_CAMERA_NAME: {
            "width_px": 640, "height_px": 480,
            "requested_K_undistortion": [[320, 0, 320], [0, 320, 240], [0, 0, 1]],
            "carla_nominal_K": [[320, 0, 320], [0, 320, 240], [0, 0, 1]],
        }},
        applied_parent_relative_matrices={_CAMERA_NAME: mount},
        runtime_measurements={_CAMERA_NAME: {"frame_id": 7, "timestamp_s": 0.35, "dataset_identity": "run:hash", "dataset_artifact_sha256": "c" * 64}},
        verification_mode="online",
    )
    return {
        "schema_version": 2,
        "calibration_contract_version": "CARLA_SENSOR_MOUNTING/v2",
        "sensor_contract": {"calibration_contract_version": "CARLA_SENSOR_MOUNTING/v2"},
        "use_K_undistortion_only": True,
        "sensors": {_CAMERA_NAME: {}},
        "applied_carla_transforms": {"sensors": {_CAMERA_NAME: {"relative_to_vehicle": {"x": 0, "y": 0, "z": 0}}}},
        "applied_sensor_rig_v2": receipt,
    }


def test_valid_live_v2_receipt_passes():
    assert _rig_verification_contract_errors(
        _valid_verification(), expected_source_calibration_sha256=_CALIBRATION_SHA256
    ) == []


def test_resealed_receipt_cannot_choose_its_own_calibration_digest():
    value = _valid_verification()
    value["applied_sensor_rig_v2"]["source_calibration_sha256"] = "d" * 64
    from ultimate_pipeline.sensors.applied_sensor_rig import seal_applied_sensor_rig_v2
    value["applied_sensor_rig_v2"] = seal_applied_sensor_rig_v2(value["applied_sensor_rig_v2"])
    errors = _rig_verification_contract_errors(
        value, expected_source_calibration_sha256=_CALIBRATION_SHA256
    )
    assert "source_calibration_sha256_mismatch" in errors


def test_thesis_validator_uses_repository_calibration_not_status_path(tmp_path):
    import hashlib
    from ultimate_pipeline.tools.validate_thesis_run import (
        _trusted_calibration_sha_from_status,
    )

    canonical = tmp_path / "ultimate_pipeline" / "sensors" / "calib_data.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b'{"frozen":"source"}')
    digest = hashlib.sha256(canonical.read_bytes()).hexdigest()
    status = {"calib_path_resolved": str(canonical), "calib_sha256": digest}
    assert _trusted_calibration_sha_from_status(status, repo_root=tmp_path) == (digest, None)

    forged = tmp_path / "forged-calibration.json"
    forged.write_bytes(b'{"attacker":"source"}')
    status["calib_path_resolved"] = str(forged)
    expected, error = _trusted_calibration_sha_from_status(status, repo_root=tmp_path)
    assert expected is None
    assert error == "perception_status calibration path is not the repository authority"


def test_v1_receipt_cannot_be_promoted_by_legacy_flags():
    value = _valid_verification()
    value["schema_version"] = 1
    value["cTv_inverted"] = False
    value["vTl_inverted"] = True
    assert "legacy_v1_rig_receipt_not_admissible" in _rig_verification_contract_errors(value)


def test_source_only_receipt_fails_live_acceptance():
    value = _valid_verification()
    value["applied_sensor_rig_v2"]["verification_mode"] = "offline_source_only"
    errors = _rig_verification_contract_errors(value)
    assert "live_verification_required" in errors
    assert "receipt_digest_mismatch" in errors


def test_missing_applied_sensor_is_named():
    value = _valid_verification()
    del value["applied_carla_transforms"]["sensors"][_CAMERA_NAME]
    assert any(_CAMERA_NAME in error for error in _rig_verification_contract_errors(value))


def test_missing_v2_receipt_fails_closed():
    value = _valid_verification()
    del value["applied_sensor_rig_v2"]
    assert "applied_sensor_rig_v2_missing_or_wrong_schema" in _rig_verification_contract_errors(value)
