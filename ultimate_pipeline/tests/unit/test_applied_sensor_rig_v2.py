from __future__ import annotations

import numpy as np
import pytest

from ultimate_pipeline.sensors.applied_sensor_rig import (
    bind_recorder_dataset_v2,
    build_applied_sensor_rig_v2,
    observed_parent_relative_mount,
    validate_applied_sensor_rig_v2,
)
from ultimate_pipeline.sensors.transform_conventions import carla_attachment_pose_from_matrix


def _carla_transform(matrix):
    import carla

    pose = carla_attachment_pose_from_matrix(matrix)
    return carla.Transform(
        carla.Location(x=pose["x"], y=pose["y"], z=pose["z"]),
        carla.Rotation(roll=pose["roll"], pitch=pose["pitch"], yaw=pose["yaw"]),
    )


def _valid_receipt():
    requested = np.eye(4)
    requested[:3, 3] = [-0.4, 0.03, 1.2]
    ego_world = np.eye(4)
    ego_world[:3, 3] = [100.0, -50.0, 0.5]
    sensor_world = ego_world @ requested
    observed = observed_parent_relative_mount(
        _carla_transform(ego_world), _carla_transform(sensor_world)
    )
    return build_applied_sensor_rig_v2(
        source_calibration_sha256="a" * 64,
        code_commit="b" * 40,
        requested_parent_relative_matrices={"front_camera": requested},
        ego_identity={"actor_id": 101, "type_id": "vehicle.tesla.model3"},
        sensor_identities={"front_camera": {"actor_id": 202, "type_id": "sensor.camera.rgb"}},
        blueprint_configuration={"front_camera": {"image_size_x": "1280", "fov": "90"}},
        effective_camera_configuration={
            "front_camera": {
                "width_px": 1280,
                "height_px": 720,
                "requested_K_undistortion": [[640, 0, 640], [0, 640, 360], [0, 0, 1]],
                "carla_nominal_K": [[640, 0, 640], [0, 640, 360], [0, 0, 1]],
            }
        },
        applied_parent_relative_matrices={"front_camera": observed},
        runtime_measurements={
            "front_camera": {
                "frame_id": 777,
                "timestamp_s": 38.85,
                "dataset_identity": "run-2026-11-18-arm-manual",
                "dataset_artifact_sha256": "c" * 64,
            }
        },
        verification_mode="online",
    )


def test_observed_parent_mount_is_reconstructed_from_world_transforms():
    receipt = _valid_receipt()
    assert receipt["applied_parent_relative_matrices"] is not None
    assert receipt["verification_status"] == "online_observation_claim_consistent_unattested"
    assert receipt["attestation_status"] == "UNATTESTED_SELF_REPORTED"
    assert validate_applied_sensor_rig_v2(receipt, require_live=True, expected_source_calibration_sha256="a" * 64) == []


def test_source_only_or_missing_runtime_observation_cannot_pass_live_acceptance():
    receipt = build_applied_sensor_rig_v2(
        source_calibration_sha256="a" * 64,
        code_commit="b" * 40,
        requested_parent_relative_matrices={"front_camera": np.eye(4)},
        ego_identity=None,
        sensor_identities={},
        blueprint_configuration={},
        effective_camera_configuration={},
        verification_mode="offline_source_only",
    )
    errors = validate_applied_sensor_rig_v2(receipt, require_live=True, expected_source_calibration_sha256="a" * 64)
    assert "live_verification_required" in errors
    assert "observed_applied_mounts_missing_or_incomplete" in errors
    assert "runtime_measurements_missing_or_incomplete" in errors


def test_receipt_rejects_stale_sensor_identity_digest_and_missing_dataset_binding():
    receipt = _valid_receipt()
    receipt["sensor_identities"]["front_camera"]["actor_id"] = 303
    errors = validate_applied_sensor_rig_v2(receipt, require_live=True, expected_source_calibration_sha256="a" * 64)
    assert "identity_binding_digest_mismatch" in errors

    receipt = _valid_receipt()
    del receipt["runtime_measurements"]["front_camera"]["dataset_artifact_sha256"]
    errors = validate_applied_sensor_rig_v2(receipt, require_live=True, expected_source_calibration_sha256="a" * 64)
    assert "front_camera:dataset_artifact_sha256_missing_or_invalid" in errors


def test_receipt_rejects_missing_sensor_and_reflected_mount():
    receipt = _valid_receipt()
    del receipt["applied_parent_relative_matrices"]["front_camera"]
    assert "observed_applied_mounts_missing_or_incomplete" in validate_applied_sensor_rig_v2(
        receipt, require_live=True, expected_source_calibration_sha256="a" * 64
    )
    reflected = np.eye(4)
    reflected[0, 0] = -1
    with pytest.raises(ValueError, match="reflected"):
        build_applied_sensor_rig_v2(
            source_calibration_sha256="a" * 64,
            code_commit="b" * 40,
            requested_parent_relative_matrices={"bad": reflected},
            ego_identity={"actor_id": 1},
            sensor_identities={},
            blueprint_configuration={},
            effective_camera_configuration={},
            verification_mode="online",
        )


def test_recorder_dataset_binding_requires_and_hashes_real_common_artifacts(tmp_path):
    import hashlib
    import json
    from pathlib import Path

    receipt = _valid_receipt()
    sensor_names = list(receipt["requested_parent_relative_matrices"])
    artifact_bindings = {}
    for name in sensor_names:
        payload = f"captured:{name}:frame-777".encode("ascii")
        directory = tmp_path / "rgb" / name
        directory.mkdir(parents=True)
        artifact_path = directory / "00000777.png"
        artifact_path.write_bytes(payload)
        artifact_bindings[name] = {
            "777": {
                "write_status": "WRITTEN",
                "callback_frame_id": 777,
                "filename_frame_id": 777,
                "sim_timestamp": 38.85,
                "output_path": str(artifact_path),
                "output_sha256": hashlib.sha256(payload).hexdigest(),
            }
        }
    manifest = {
        "sensors": [{"name": name, "actor_id": 202, "type_id": "sensor.camera.rgb"} for name in sensor_names],
        "artifact_bindings": artifact_bindings,
        "frame_correspondence": {
            "schema": "FRAME_CORRESPONDENCE/v1",
            "common_frame_ids": [777],
            "duplicates_by_sensor": {},
        },
    }
    manifest_path = tmp_path / "recorder_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    bound, errors = bind_recorder_dataset_v2(receipt, manifest_path)
    assert errors == []
    assert validate_applied_sensor_rig_v2(bound, require_live=True, expected_source_calibration_sha256="a" * 64) == []
    assert bound["runtime_measurements"]["front_camera"]["frame_id"] == 777
    assert bound["runtime_measurements"]["front_camera"]["timestamp_s"] == 38.85
    assert bound["runtime_measurements"]["front_camera"]["dataset_artifact_sha256"]

    artifact_path = Path(artifact_bindings["front_camera"]["777"]["output_path"])
    artifact_path.write_bytes(b"tampered")
    unbound, errors = bind_recorder_dataset_v2(receipt, manifest_path)
    assert unbound == receipt
    assert any("sha256_mismatch" in error for error in errors)


def test_recorder_binding_rejects_replacement_actor_with_same_sensor_name(tmp_path):
    import hashlib
    import json

    receipt = _valid_receipt()
    payload = b"captured by replacement actor"
    frame_path = tmp_path / "00000777.png"
    frame_path.write_bytes(payload)
    manifest = {
        "sensors": [{"name": "front_camera", "actor_id": 999, "type_id": "sensor.camera.rgb"}],
        "artifact_bindings": {"front_camera": {"777": {
            "write_status": "WRITTEN", "callback_frame_id": 777,
            "filename_frame_id": 777, "sim_timestamp": 38.85,
            "output_path": str(frame_path), "output_sha256": hashlib.sha256(payload).hexdigest(),
        }}},
        "frame_correspondence": {
            "schema": "FRAME_CORRESPONDENCE/v1", "common_frame_ids": [777],
            "duplicates_by_sensor": {},
        },
    }
    manifest_path = tmp_path / "recorder_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _, errors = bind_recorder_dataset_v2(receipt, manifest_path)
    assert "front_camera:recorder_actor_identity_mismatch" in errors


def test_dataset_measurement_mutation_invalidates_receipt_digest():
    receipt = _valid_receipt()
    receipt["runtime_measurements"]["front_camera"]["dataset_identity"] = "stale-run"
    assert "receipt_digest_mismatch" in validate_applied_sensor_rig_v2(receipt, require_live=True, expected_source_calibration_sha256="a" * 64)


def test_resealed_receipt_with_untrusted_calibration_digest_is_rejected():
    from ultimate_pipeline.sensors.applied_sensor_rig import seal_applied_sensor_rig_v2
    receipt = _valid_receipt()
    receipt["source_calibration_sha256"] = "d" * 64
    receipt = seal_applied_sensor_rig_v2(receipt)
    assert validate_applied_sensor_rig_v2(receipt, require_live=True, expected_source_calibration_sha256="a" * 64) == ["source_calibration_sha256_mismatch"]


def test_live_receipt_requires_trusted_calibration_digest():
    assert "trusted_source_calibration_sha256_required" in validate_applied_sensor_rig_v2(_valid_receipt(), require_live=True)


def test_self_hashes_never_claim_independent_runtime_attestation():
    from ultimate_pipeline.sensors.applied_sensor_rig import seal_applied_sensor_rig_v2

    receipt = _valid_receipt()
    receipt["attestation_status"] = "INDEPENDENTLY_ATTESTED"
    resealed = seal_applied_sensor_rig_v2(receipt)
    assert resealed["attestation_status"] == "UNATTESTED_SELF_REPORTED"
    assert resealed["verification_status"] == "online_observation_claim_consistent_unattested"
    assert validate_applied_sensor_rig_v2(
        resealed, require_live=True, expected_source_calibration_sha256="a" * 64
    ) == []
