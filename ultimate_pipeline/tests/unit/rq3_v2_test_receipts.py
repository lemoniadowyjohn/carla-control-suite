"""Synthetic APPLIED_SENSOR_RIG/v2 fixtures for offline RQ3 contract tests.

These receipts exercise source validation only. They are not CARLA observations,
runtime evidence, or admitted scientific captures.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from ultimate_pipeline.sensors.applied_sensor_rig import (
    build_applied_sensor_rig_v2,
    canonical_sha256,
)
from ultimate_pipeline.sensors.transform_conventions import carla_ego_from_camera_from_cTv

ROOT = Path(__file__).resolve().parents[2]
CALIBRATION_PATH = ROOT / "sensors" / "calib_data.json"
CALIBRATION_BYTES = CALIBRATION_PATH.read_bytes()
CALIBRATION = json.loads(CALIBRATION_BYTES.decode("utf-8"))
CALIBRATION_SHA256 = hashlib.sha256(CALIBRATION_BYTES).hexdigest()
TEST_COMMIT = "a" * 40
_CAMERA = "front_left_camera"
_MOUNT = carla_ego_from_camera_from_cTv(CALIBRATION["cameras"][_CAMERA]["cTv"])


def make_synthetic_rq3_arm_receipt(
    arm: dict[str, Any], *, code_commit: str = TEST_COMMIT, label: str = "arm"
) -> dict[str, Any]:
    """Return a self-consistent, deliberately synthetic one-camera v2 receipt."""
    dataset_identity = str(arm.get("dataset_identity") or f"synthetic-{label}")
    dataset_sha = str(arm.get("dataset_artifact_sha256") or hashlib.sha256(dataset_identity.encode()).hexdigest())
    requested = {_CAMERA: _MOUNT.copy()}
    return build_applied_sensor_rig_v2(
        source_calibration_sha256=CALIBRATION_SHA256,
        code_commit=code_commit,
        requested_parent_relative_matrices=requested,
        ego_identity={"actor_id": 100 + (label == "auto"), "type_id": "vehicle.test"},
        sensor_identities={_CAMERA: {"actor_id": 200 + (label == "auto"), "type_id": "sensor.camera.rgb"}},
        blueprint_configuration={_CAMERA: {"image_size_x": "1920", "image_size_y": "1080", "fov": "90"}},
        effective_camera_configuration={
            _CAMERA: {
                "width_px": 1920,
                "height_px": 1080,
                "requested_K_undistortion": [[1000.0, 0.0, 1000.0], [0.0, 1000.0, 1000.0], [0.0, 0.0, 1.0]],
                "carla_nominal_K": [[1000.0, 0.0, 1000.0], [0.0, 1000.0, 1000.0], [0.0, 0.0, 1.0]],
            }
        },
        applied_parent_relative_matrices=requested,
        runtime_measurements={
            _CAMERA: {
                "frame_id": 1,
                "timestamp_s": 0.05,
                "dataset_identity": dataset_identity,
                "dataset_artifact_sha256": dataset_sha,
            }
        },
        verification_mode="online",
    )


def complete_synthetic_arm(arm: dict[str, Any], *, code_commit: str = TEST_COMMIT, label: str = "arm") -> dict[str, Any]:
    """Attach a valid fixture while retaining explicit values used by negatives."""
    result = dict(arm)
    result.setdefault("calibration_sha256", CALIBRATION_SHA256)
    result.setdefault("dataset_identity", f"synthetic-{label}")
    result.setdefault("dataset_artifact_sha256", hashlib.sha256(result["dataset_identity"].encode()).hexdigest())
    receipt = make_synthetic_rq3_arm_receipt(result, code_commit=code_commit, label=label)
    result.setdefault("sensor_rig_sha256", receipt["applied_configuration_sha256"])
    result.setdefault("runtime_sensor_rig_sha256", result["sensor_rig_sha256"])
    result["applied_sensor_rig_v2"] = receipt
    result["applied_sensor_rig_v2_sha256"] = canonical_sha256(receipt)
    return result
