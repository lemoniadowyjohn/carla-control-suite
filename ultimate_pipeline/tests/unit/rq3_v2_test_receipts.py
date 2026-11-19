"""Synthetic APPLIED_SENSOR_RIG/v2 fixtures for offline RQ3 contract tests.

The default receipt is a **complete** synthetic rig: every camera in the
authoritative calibration plus the active LiDAR, with mounts derived from the
exact calibration bytes. It is still synthetic -- no CARLA actor was observed --
so it is not runtime evidence and must never be presented as a live capture.

Deliberately incomplete one-camera fixtures remain available for negative tests
via ``incomplete=True``. They are marked
``INCOMPLETE_FIXTURE_VALID_FOR_LIVE_ADMISSION = False`` and are invalid for live
admission by construction.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ultimate_pipeline.sensors.applied_sensor_rig import (
    build_applied_sensor_rig_v2,
    canonical_sha256,
)
from ultimate_pipeline.sensors.canonical_lidar_spec import resolve_active_lidars
from ultimate_pipeline.sensors.transform_conventions import (
    carla_ego_from_camera_from_cTv,
    carla_ego_from_lidar_from_vTl,
)

ROOT = Path(__file__).resolve().parents[2]
CALIBRATION_PATH = ROOT / "sensors" / "calib_data.json"
CALIBRATION_BYTES = CALIBRATION_PATH.read_bytes()
CALIBRATION = json.loads(CALIBRATION_BYTES.decode("utf-8"))
CALIBRATION_SHA256 = hashlib.sha256(CALIBRATION_BYTES).hexdigest()
TEST_COMMIT = "a" * 40

CAMERA_NAMES: tuple[str, ...] = tuple(sorted(CALIBRATION.get("cameras") or {}))
ACTIVE_LIDAR_SPECS = resolve_active_lidars(CALIBRATION, low_memory_profile=False)
ACTIVE_LIDAR_NAMES: tuple[str, ...] = tuple(spec.name for spec in ACTIVE_LIDAR_SPECS)
COMPLETE_SENSOR_NAMES: tuple[str, ...] = CAMERA_NAMES + ACTIVE_LIDAR_NAMES

INCOMPLETE_ONE_CAMERA = "front_left_camera"
INCOMPLETE_FIXTURE_VALID_FOR_LIVE_ADMISSION = False


def _complete_mounts() -> dict[str, Any]:
    """Derive every rigid mount from the authoritative calibration bytes."""
    mounts: dict[str, Any] = {}
    for name in CAMERA_NAMES:
        mounts[name] = carla_ego_from_camera_from_cTv(
            CALIBRATION["cameras"][name]["cTv"]
        )
    for spec in ACTIVE_LIDAR_SPECS:
        lidar = (CALIBRATION.get("lidars") or {}).get(spec.name)
        if not isinstance(lidar, dict) or "vTl" not in lidar:
            raise RuntimeError(f"active lidar calibration is incomplete: {spec.name}")
        mounts[spec.name] = carla_ego_from_lidar_from_vTl(lidar["vTl"])
    return mounts


COMPLETE_MOUNTS = _complete_mounts()


def _camera_configuration(name: str) -> dict[str, Any]:
    camera = CALIBRATION["cameras"][name]
    width, height = (int(value) for value in camera["image_size"])
    return {
        "width_px": width,
        "height_px": height,
        "requested_K_undistortion": [list(row) for row in camera["K_undistortion"]],
        "carla_nominal_K": [list(row) for row in camera["K"]],
    }


def _sensor_type(name: str) -> str:
    return "sensor.camera.rgb" if name in CAMERA_NAMES else "sensor.lidar.ray_cast"


def _blueprint(name: str) -> dict[str, Any]:
    if name in CAMERA_NAMES:
        width, height = (int(value) for value in CALIBRATION["cameras"][name]["image_size"])
        return {"image_size_x": str(width), "image_size_y": str(height)}
    return {"range": "100"}


def make_synthetic_rq3_arm_receipt(
    arm: dict[str, Any],
    *,
    code_commit: str = TEST_COMMIT,
    label: str = "arm",
    incomplete: bool = False,
) -> dict[str, Any]:
    """Return a self-consistent synthetic v2 receipt.

    ``incomplete=True`` intentionally builds a one-camera rig for negative
    admission tests; it is never valid for live admission.
    """
    dataset_identity = str(arm.get("dataset_identity") or f"synthetic-{label}")
    dataset_sha = str(
        arm.get("dataset_artifact_sha256")
        or hashlib.sha256(dataset_identity.encode()).hexdigest()
    )
    names = (INCOMPLETE_ONE_CAMERA,) if incomplete else COMPLETE_SENSOR_NAMES
    requested = {name: COMPLETE_MOUNTS[name].copy() for name in names}
    actor_base = 300 if label == "auto" else 200
    identities = {
        name: {
            "actor_id": actor_base + index,
            "type_id": _sensor_type(name),
        }
        for index, name in enumerate(names)
    }
    blueprints = {name: _blueprint(name) for name in names}
    camera_configuration = {
        name: _camera_configuration(name) for name in names if name in CAMERA_NAMES
    }
    measurements = {
        name: {
            "frame_id": 1,
            "timestamp_s": 0.05,
            "dataset_identity": dataset_identity,
            "dataset_artifact_sha256": dataset_sha,
        }
        for name in names
    }
    return build_applied_sensor_rig_v2(
        source_calibration_sha256=CALIBRATION_SHA256,
        code_commit=code_commit,
        requested_parent_relative_matrices=requested,
        ego_identity={"actor_id": 100 + (label == "auto"), "type_id": "vehicle.test"},
        sensor_identities=identities,
        blueprint_configuration=blueprints,
        effective_camera_configuration=camera_configuration,
        applied_parent_relative_matrices=requested,
        runtime_measurements=measurements,
        verification_mode="online",
    )


def complete_synthetic_arm(
    arm: dict[str, Any],
    *,
    code_commit: str = TEST_COMMIT,
    label: str = "arm",
    incomplete: bool = False,
) -> dict[str, Any]:
    """Attach a fixture while retaining explicit values used by negatives."""
    result = dict(arm)
    result.setdefault("calibration_sha256", CALIBRATION_SHA256)
    result.setdefault("dataset_identity", f"synthetic-{label}")
    result.setdefault(
        "dataset_artifact_sha256",
        hashlib.sha256(result["dataset_identity"].encode()).hexdigest(),
    )
    receipt = make_synthetic_rq3_arm_receipt(
        result, code_commit=code_commit, label=label, incomplete=incomplete
    )
    result.setdefault("sensor_rig_sha256", receipt["applied_configuration_sha256"])
    if "runtime_sensor_rig_sha256" not in result:
        from ultimate_pipeline.perception.rq3_capture_contract import runtime_sensor_rig_identity as _runtime_sensor_rig_identity
        result["runtime_sensor_rig_sha256"] = _runtime_sensor_rig_identity(
            sensor_rig_sha256=result["sensor_rig_sha256"],
            camera_response_sha256=str(result.get("camera_response_sha256", "")),
            simulation_physics_sha256=str(result.get("simulation_physics_sha256", "")),
        )["runtime_sensor_rig_sha256"]
    result["applied_sensor_rig_v2"] = receipt
    result["applied_sensor_rig_v2_sha256"] = canonical_sha256(receipt)
    return result
