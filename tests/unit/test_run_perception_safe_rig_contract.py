"""V2 applied-mount admission gate tests for the safe recorder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ultimate_pipeline.sensors.applied_sensor_rig import build_applied_sensor_rig_v2
from ultimate_pipeline.sensors.canonical_lidar_spec import resolve_active_lidars
from ultimate_pipeline.sensors.transform_conventions import (
    carla_ego_from_camera_from_cTv,
    carla_ego_from_lidar_from_vTl,
)

_CALIBRATION_PATH = (
    Path(__file__).resolve().parents[2] / "ultimate_pipeline" / "sensors" / "calib_data.json"
)
_CALIBRATION_BYTES = _CALIBRATION_PATH.read_bytes()
_CALIBRATION_SHA256 = hashlib.sha256(_CALIBRATION_BYTES).hexdigest()
_CALIBRATION = json.loads(_CALIBRATION_BYTES.decode("utf-8"))
_CAMERA_NAMES = tuple(sorted(_CALIBRATION.get("cameras") or {}))
_ACTIVE_LIDARS = resolve_active_lidars(_CALIBRATION, low_memory_profile=False)
_SENSOR_NAMES = _CAMERA_NAMES + tuple(spec.name for spec in _ACTIVE_LIDARS)

from ultimate_pipeline.tools.run_perception_safe import _rig_verification_contract_errors


def _camera_configuration(name: str) -> dict:
    camera = _CALIBRATION["cameras"][name]
    width, height = (int(value) for value in camera["image_size"])
    return {
        "width_px": width,
        "height_px": height,
        "requested_K_undistortion": [list(row) for row in camera["K_undistortion"]],
        "carla_nominal_K": [list(row) for row in camera["K"]],
    }


def _blueprint(name: str) -> dict:
    if name in _CAMERA_NAMES:
        width, height = (int(value) for value in _CALIBRATION["cameras"][name]["image_size"])
        return {"blueprint_id": "sensor.camera.rgb", "attributes": {"image_size_x": str(width), "image_size_y": str(height)}}
    return {"blueprint_id": "sensor.lidar.ray_cast", "attributes": {"range": "100"}}


def _valid_verification():
    mounts = {}
    for name in _CAMERA_NAMES:
        mounts[name] = carla_ego_from_camera_from_cTv(_CALIBRATION["cameras"][name]["cTv"])
    for spec in _ACTIVE_LIDARS:
        mounts[spec.name] = carla_ego_from_lidar_from_vTl(_CALIBRATION["lidars"][spec.name]["vTl"])

    requested = {name: mounts[name].copy() for name in _SENSOR_NAMES}
    ego_identity = {"actor_id": 11, "type_id": "vehicle.test"}
    sensor_identities = {
        name: {"actor_id": 100 + index, "type_id": ("sensor.camera.rgb" if name in _CAMERA_NAMES else "sensor.lidar.ray_cast")}
        for index, name in enumerate(_SENSOR_NAMES)
    }
    blueprint_configuration = {name: _blueprint(name) for name in _SENSOR_NAMES}
    effective_camera_configuration = {name: _camera_configuration(name) for name in _CAMERA_NAMES}
    runtime_measurements = {
        name: {
            "frame_id": 7,
            "timestamp_s": 0.35,
            "dataset_identity": "run:hash",
            "dataset_artifact_sha256": "c" * 64,
        }
        for name in _SENSOR_NAMES
    }
    receipt = build_applied_sensor_rig_v2(
        source_calibration_sha256=_CALIBRATION_SHA256,
        code_commit="b" * 40,
        requested_parent_relative_matrices=requested,
        ego_identity=ego_identity,
        sensor_identities=sensor_identities,
        blueprint_configuration=blueprint_configuration,
        effective_camera_configuration=effective_camera_configuration,
        applied_parent_relative_matrices=requested,
        runtime_measurements=runtime_measurements,
        verification_mode="online",
    )
    sensors_legacy = {name: {} for name in _SENSOR_NAMES}
    applied_transforms = {"sensors": {name: {"relative_to_vehicle": {"x": 0, "y": 0, "z": 0}} for name in _SENSOR_NAMES}}
    return {
        "schema_version": 2,
        "calibration_contract_version": "CARLA_SENSOR_MOUNTING/v2",
        "sensor_contract": {"calibration_contract_version": "CARLA_SENSOR_MOUNTING/v2"},
        "use_K_undistortion_only": True,
        "sensors": sensors_legacy,
        "applied_carla_transforms": applied_transforms,
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
    missing = _SENSOR_NAMES[0]
    del value["applied_carla_transforms"]["sensors"][missing]
    assert any(missing in error for error in _rig_verification_contract_errors(value))


def test_missing_v2_receipt_fails_closed():
    value = _valid_verification()
    del value["applied_sensor_rig_v2"]
    assert "applied_sensor_rig_v2_missing_or_wrong_schema" in _rig_verification_contract_errors(value)
