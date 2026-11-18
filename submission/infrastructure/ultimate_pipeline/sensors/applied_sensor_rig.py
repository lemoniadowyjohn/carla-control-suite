"""Versioned evidence for requested and actually observed CARLA sensor mounts."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

import numpy as np

SCHEMA = "APPLIED_SENSOR_RIG/v2"
CONTRACT_VERSION = "CARLA_SENSOR_MOUNTING/v2"
POSITION_RESIDUAL_LIMIT_M = 0.01
ANGULAR_RESIDUAL_LIMIT_DEG = 0.1


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def current_clean_code_commit(source_root: str | Path) -> str | None:
    """Return a source identity only for a clean, committed checkout."""
    try:
        root = Path(source_root)
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=True, capture_output=True, text=True, timeout=3,
        ).stdout.strip().lower()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            check=True, capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        return head if re.fullmatch(r"[0-9a-f]{40}", head) and not status else None
    except (OSError, subprocess.SubprocessError):
        return None


def _rigid_matrix(value: Any, *, label: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=float)
    if matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)):
        raise ValueError(f"{label} must be a finite 4x4 matrix")
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-8, rtol=0):
        raise ValueError(f"{label} has invalid homogeneous row")
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6, rtol=0):
        raise ValueError(f"{label} rotation is nonrigid")
    if not math.isclose(float(np.linalg.det(rotation)), 1.0, abs_tol=1e-6, rel_tol=0):
        raise ValueError(f"{label} rotation is reflected")
    return matrix


def carla_transform_matrix(transform: Any) -> np.ndarray:
    """Read the observed 4x4 matrix from a CARLA Transform-like client object."""
    if transform is None or not callable(getattr(transform, "get_matrix", None)):
        raise ValueError("CARLA transform with get_matrix() is required")
    return _rigid_matrix(transform.get_matrix(), label="CARLA world transform")


def observed_parent_relative_mount(ego_world_transform: Any, sensor_world_transform: Any) -> np.ndarray:
    """Reconstruct child pose from observed world transforms, never spawn input."""
    ego_world = carla_transform_matrix(ego_world_transform)
    sensor_world = carla_transform_matrix(sensor_world_transform)
    rotation = ego_world[:3, :3]
    inverse_ego = np.eye(4, dtype=float)
    inverse_ego[:3, :3] = rotation.T
    inverse_ego[:3, 3] = -(rotation.T @ ego_world[:3, 3])
    return _rigid_matrix(inverse_ego @ sensor_world, label="observed parent-relative sensor mount")


def _residuals(requested: Any, observed: Any) -> dict[str, float]:
    req = _rigid_matrix(requested, label="requested mount")
    obs = _rigid_matrix(observed, label="observed mount")
    position = float(np.linalg.norm(req[:3, 3] - obs[:3, 3]))
    delta = req[:3, :3].T @ obs[:3, :3]
    cosine = min(1.0, max(-1.0, (float(np.trace(delta)) - 1.0) / 2.0))
    angular = math.degrees(math.acos(cosine))
    return {"position_m": position, "angle_deg": angular}


def _actual_config_digest_payload(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "source_calibration_sha256": receipt.get("source_calibration_sha256"),
        "code_commit": receipt.get("code_commit"),
        "calibration_contract_version": receipt.get("calibration_contract_version"),
        "requested_parent_relative_matrices": receipt.get("requested_parent_relative_matrices"),
        "applied_parent_relative_matrices": receipt.get("applied_parent_relative_matrices"),
        "blueprint_configuration": receipt.get("blueprint_configuration"),
        "effective_camera_configuration": receipt.get("effective_camera_configuration"),
    }


def _identity_binding_payload(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ego_identity": receipt.get("ego_identity"),
        "sensor_identities": receipt.get("sensor_identities"),
    }


def seal_applied_sensor_rig_v2(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute all v2 receipt digests after capture evidence is attached."""
    sealed = dict(receipt)
    # Self-hashes detect accidental mutation only; no runtime trust root exists here.
    sealed["attestation_status"] = "UNATTESTED_SELF_REPORTED"
    if isinstance(sealed.get("applied_parent_relative_matrices"), dict):
        sealed["applied_configuration_sha256"] = canonical_sha256(
            _actual_config_digest_payload(sealed)
        )
        sealed["identity_binding_sha256"] = canonical_sha256(
            _identity_binding_payload(sealed)
        )
    requested = sealed.get("requested_parent_relative_matrices")
    measurements = sealed.get("runtime_measurements")
    complete = (
        sealed.get("verification_mode") == "online"
        and isinstance(requested, dict)
        and bool(requested)
        and isinstance(measurements, dict)
        and set(measurements) == set(requested)
    )
    sealed["verification_status"] = (
        "online_observation_claim_consistent_unattested" if complete else
        "online_observation_claim_incomplete_unattested"
        if sealed.get("verification_mode") == "online" else "offline_source_only"
    )
    sealed["receipt_sha256"] = None
    sealed["receipt_sha256"] = canonical_sha256(sealed)
    return sealed


def bind_recorder_dataset_v2(receipt: Mapping[str, Any], manifest_path: str | Path) -> tuple[dict[str, Any], list[str]]:
    """Bind a live mount receipt to verified recorder frame artifacts.

    All requested sensors must have written artifacts for at least one common
    callback frame. Every referenced file is rehashed from the capture tree.
    """
    result = dict(receipt)
    errors: list[str] = []
    path = Path(manifest_path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return result, [f"recorder_manifest_unreadable:{type(exc).__name__}"]
    requested = result.get("requested_parent_relative_matrices")
    artifacts = manifest.get("artifact_bindings")
    correspondence = manifest.get("frame_correspondence")
    if not isinstance(requested, dict) or not requested or not isinstance(artifacts, dict):
        return result, ["recorder_artifact_bindings_missing"]
    if not isinstance(correspondence, dict) or correspondence.get("schema") != "FRAME_CORRESPONDENCE/v1":
        return result, ["recorder_frame_correspondence_missing"]
    manifest_sensors = manifest.get("sensors")
    if not isinstance(manifest_sensors, list):
        return result, ["recorder_sensor_identities_missing"]
    manifest_identities = {
        str(item.get("name")): item
        for item in manifest_sensors
        if isinstance(item, dict) and item.get("name") is not None
    }
    receipt_identities = result.get("sensor_identities")
    if not isinstance(receipt_identities, dict):
        return result, ["applied_rig_sensor_identities_missing"]
    for name in requested:
        manifest_sensor = manifest_identities.get(name)
        receipt_sensor = receipt_identities.get(name)
        if not isinstance(manifest_sensor, dict) or not isinstance(receipt_sensor, dict):
            errors.append(f"{name}:recorder_or_receipt_sensor_identity_missing")
            continue
        if str(manifest_sensor.get("actor_id")) != str(receipt_sensor.get("actor_id")):
            errors.append(f"{name}:recorder_actor_identity_mismatch")
        if str(manifest_sensor.get("type_id", "")) != str(receipt_sensor.get("type_id", "")):
            errors.append(f"{name}:recorder_sensor_type_mismatch")
    duplicates = correspondence.get("duplicates_by_sensor", {})
    if any(duplicates.get(name) for name in requested):
        errors.append("duplicate_sensor_callback_frames")
    common = correspondence.get("common_frame_ids")
    if not isinstance(common, list) or not common:
        return result, errors + ["no_common_recorder_frame"]

    resolved: dict[str, dict[int, dict[str, Any]]] = {}
    capture_records: list[dict[str, Any]] = []
    for name in sorted(requested):
        per_frame = artifacts.get(name)
        if not isinstance(per_frame, dict):
            errors.append(f"{name}:artifact_bindings_missing")
            continue
        resolved[name] = {}
        for raw_frame, record in per_frame.items():
            try:
                frame_id = int(raw_frame)
            except (TypeError, ValueError):
                errors.append(f"{name}:invalid_artifact_frame_id")
                continue
            if not isinstance(record, dict) or record.get("write_status") != "WRITTEN":
                continue
            output_path = Path(str(record.get("output_path", "")))
            try:
                file_path = output_path.resolve(strict=True)
                file_path.relative_to(path.parent.resolve(strict=True))
                actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
            except (OSError, ValueError):
                errors.append(f"{name}:{frame_id}:artifact_missing_or_outside_capture")
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("output_sha256", ""))) or actual_sha != record.get("output_sha256"):
                errors.append(f"{name}:{frame_id}:artifact_sha256_mismatch")
                continue
            if record.get("callback_frame_id") != frame_id or record.get("filename_frame_id") != frame_id:
                errors.append(f"{name}:{frame_id}:frame_binding_mismatch")
                continue
            timestamp = record.get("sim_timestamp")
            if not isinstance(timestamp, (int, float)) or not math.isfinite(float(timestamp)):
                errors.append(f"{name}:{frame_id}:simulation_timestamp_missing")
                continue
            resolved[name][frame_id] = {
                "output_sha256": actual_sha,
                "sim_timestamp": float(timestamp),
                "output_path": str(file_path.relative_to(path.parent.resolve(strict=True))),
            }
    if errors:
        return result, errors
    actual_common = set(int(frame) for frame in common)
    for name in requested:
        actual_common.intersection_update(resolved.get(name, {}).keys())
    if not actual_common:
        return result, ["manifest_common_frames_have_no_verified_artifacts"]
    common_ids = sorted(actual_common)
    for name in sorted(requested):
        for frame_id in common_ids:
            capture_records.append({"sensor": name, "frame_id": frame_id, **resolved[name][frame_id]})
    dataset_sha = canonical_sha256(capture_records)
    selected_frame = common_ids[0]
    result["runtime_measurements"] = {
        name: {
            "frame_id": selected_frame,
            "timestamp_s": resolved[name][selected_frame]["sim_timestamp"],
            "dataset_identity": f"{path.parent.name}:{dataset_sha}",
            "dataset_artifact_sha256": dataset_sha,
        }
        for name in sorted(requested)
    }
    result = seal_applied_sensor_rig_v2(result)
    return result, []


def build_applied_sensor_rig_v2(
    *,
    source_calibration_sha256: str,
    code_commit: str | None,
    requested_parent_relative_matrices: Mapping[str, Any],
    ego_identity: Mapping[str, Any] | None,
    sensor_identities: Mapping[str, Mapping[str, Any]],
    blueprint_configuration: Mapping[str, Mapping[str, Any]],
    effective_camera_configuration: Mapping[str, Mapping[str, Any]],
    applied_parent_relative_matrices: Mapping[str, Any] | None = None,
    runtime_measurements: Mapping[str, Mapping[str, Any]] | None = None,
    verification_mode: str = "offline_source_only",
) -> dict[str, Any]:
    """Build a self-reported consistency receipt, not an authenticity proof.

    The producer reads online observations from CARLA actor transforms and frame
    records, but JSON self-hashes cannot prove that to an independent consumer.
    The receipt therefore remains UNATTESTED_SELF_REPORTED. RQ3 authority still
    requires the existing independently signed review-receipt gate.

    Offline reports are readable but cannot pass the live consistency validator.
    """
    if verification_mode not in ("offline_source_only", "online"):
        raise ValueError("verification_mode must be offline_source_only or online")
    requested = {
        name: _rigid_matrix(value, label=f"requested {name}").tolist()
        for name, value in sorted(requested_parent_relative_matrices.items())
    }
    applied: dict[str, Any] | None = None
    residuals: dict[str, Any] = {}
    if applied_parent_relative_matrices is not None:
        applied = {
            name: _rigid_matrix(value, label=f"applied {name}").tolist()
            for name, value in sorted(applied_parent_relative_matrices.items())
        }
        for name, matrix in requested.items():
            if name not in applied:
                continue
            residuals[name] = _residuals(matrix, applied[name])

    cameras = {
        name: dict(value) for name, value in sorted(effective_camera_configuration.items())
    }
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "calibration_contract_version": CONTRACT_VERSION,
        "source_calibration_sha256": source_calibration_sha256,
        "code_commit": code_commit,
        "attestation_status": "UNATTESTED_SELF_REPORTED",
        "verification_mode": verification_mode,
        "verification_status": (
            "online_transform_observed_frames_missing"
            if verification_mode == "online" and not runtime_measurements
            else "online_observation_claim_consistent_unattested" if verification_mode == "online"
            else "offline_source_only"
        ),
        "ego_identity": dict(ego_identity or {}),
        "sensor_identities": {
            name: dict(value) for name, value in sorted(sensor_identities.items())
        },
        "requested_parent_relative_matrices": requested,
        "applied_parent_relative_matrices": applied,
        "blueprint_configuration": {
            name: dict(value) for name, value in sorted(blueprint_configuration.items())
        },
        "effective_camera_configuration": cameras,
        "runtime_measurements": {
            name: dict(value) for name, value in sorted((runtime_measurements or {}).items())
        },
        "residuals": residuals,
        "residual_limits": {
            "position_m": POSITION_RESIDUAL_LIMIT_M,
            "angle_deg": ANGULAR_RESIDUAL_LIMIT_DEG,
        },
        "applied_configuration_sha256": None,
        "identity_binding_sha256": None,
        "receipt_sha256": None,
    }
    return seal_applied_sensor_rig_v2(receipt)


def _source_calibration_mounts(
    expected_source_calibration_sha256: str | None,
    calibration_bytes: bytes | None = None,
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Derive trusted mounts from exact, SHA-bound calibration bytes.

    The repository calibration is the default trust source. A caller using an
    explicitly selected calibration must provide the exact bytes and digest
    it loaded. Matrices copied from the receipt are never used as their own
    oracle.
    """
    errors: list[str] = []
    if calibration_bytes is None:
        source_path = Path(__file__).resolve().with_name("calib_data.json")
        try:
            calibration_bytes = source_path.read_bytes()
        except OSError as exc:
            return {}, [f"trusted_calibration_source_unavailable:{type(exc).__name__}"]
    actual_sha256 = hashlib.sha256(calibration_bytes).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_source_calibration_sha256 or "")):
        return {}, ["trusted_source_calibration_sha256_required"]
    if actual_sha256 != expected_source_calibration_sha256:
        return {}, ["trusted_calibration_bytes_sha256_mismatch"]
    try:
        calibration = json.loads(calibration_bytes.decode("utf-8"))
        if not isinstance(calibration, dict):
            raise ValueError("calibration root must be an object")
        from ultimate_pipeline.sensors.canonical_lidar_spec import resolve_active_lidars
        from ultimate_pipeline.sensors.transform_conventions import (
            carla_ego_from_camera_from_cTv,
            carla_ego_from_lidar_from_vTl,
        )

        mounts: dict[str, np.ndarray] = {}
        for name, camera in (calibration.get("cameras") or {}).items():
            mounts[str(name)] = carla_ego_from_camera_from_cTv(camera["cTv"])
        for spec in resolve_active_lidars(calibration, low_memory_profile=False):
            lidar = (calibration.get("lidars") or {}).get(spec.name)
            if not isinstance(lidar, dict) or "vTl" not in lidar:
                raise ValueError(f"active lidar calibration is incomplete: {spec.name}")
            mounts[spec.name] = carla_ego_from_lidar_from_vTl(lidar["vTl"])
        if not mounts:
            raise ValueError("calibration contains no expected mounts")
        return mounts, errors
    except Exception as exc:
        return {}, [f"trusted_calibration_mount_derivation_failed:{type(exc).__name__}:{exc}"]


def validate_applied_sensor_rig_v2(
    receipt: Any,
    *,
    require_live: bool = True,
    expected_source_calibration_sha256: str | None = None,
    expected_calibration_bytes: bytes | None = None,
) -> list[str]:
    """Validate internal consistency; this does not authenticate runtime claims.

    Independent scientific admission must also pass the signed RQ3 review gate.
    """
    errors: list[str] = []
    if not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA:
        return ["applied_sensor_rig_v2_missing_or_wrong_schema"]
    expected_fields = {
        "schema", "calibration_contract_version", "source_calibration_sha256", "code_commit",
        "attestation_status", "verification_mode", "verification_status", "ego_identity", "sensor_identities",
        "requested_parent_relative_matrices", "applied_parent_relative_matrices",
        "blueprint_configuration", "effective_camera_configuration", "runtime_measurements",
        "residuals", "residual_limits", "applied_configuration_sha256",
        "identity_binding_sha256", "receipt_sha256",
    }
    for field in sorted(set(receipt) - expected_fields):
        errors.append(f"unsupported_receipt_field:{field}")
    for field in sorted(expected_fields - set(receipt)):
        errors.append(f"receipt_field_missing:{field}")
    if receipt.get("calibration_contract_version") != CONTRACT_VERSION:
        errors.append("calibration_contract_version_mismatch")
    if receipt.get("attestation_status") != "UNATTESTED_SELF_REPORTED":
        errors.append("runtime_observation_not_independently_attested")
    limits = receipt.get("residual_limits")
    if limits != {"position_m": POSITION_RESIDUAL_LIMIT_M, "angle_deg": ANGULAR_RESIDUAL_LIMIT_DEG}:
        errors.append("sensor_mount_residual_limits_mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("source_calibration_sha256", ""))):
        errors.append("source_calibration_sha256_invalid")
    if require_live:
        if not re.fullmatch(r"[0-9a-f]{64}", str(expected_source_calibration_sha256 or "")):
            errors.append("trusted_source_calibration_sha256_required")
        elif receipt.get("source_calibration_sha256") != expected_source_calibration_sha256:
            errors.append("source_calibration_sha256_mismatch")
        trusted_mounts, trust_errors = _source_calibration_mounts(
            expected_source_calibration_sha256, expected_calibration_bytes
        )
        errors.extend(trust_errors)
        if trusted_mounts and isinstance(receipt, dict):
            requested_mounts = receipt.get("requested_parent_relative_matrices")
            applied_mounts = receipt.get("applied_parent_relative_matrices")
            if isinstance(requested_mounts, dict):
                if set(requested_mounts) - set(trusted_mounts):
                    errors.append("receipt_contains_sensor_without_trusted_calibration_mount")
                for name, requested_matrix in requested_mounts.items():
                    if name not in trusted_mounts:
                        continue
                    try:
                        requested_array = _rigid_matrix(requested_matrix, label=f"requested {name}")
                        if not np.allclose(requested_array, trusted_mounts[name], rtol=0.0, atol=2e-6):
                            errors.append(f"{name}:requested_mount_does_not_match_source_calibration")
                    except (TypeError, ValueError) as exc:
                        errors.append(str(exc))
                    if isinstance(applied_mounts, dict) and name in applied_mounts:
                        try:
                            applied_array = _rigid_matrix(applied_mounts[name], label=f"applied {name}")
                            if not np.allclose(applied_array, trusted_mounts[name], rtol=0.0, atol=2e-6):
                                errors.append(f"{name}:observed_mount_does_not_match_source_calibration")
                        except (TypeError, ValueError) as exc:
                            errors.append(str(exc))
    if not re.fullmatch(r"[0-9a-f]{40}", str(receipt.get("code_commit", ""))):
        errors.append("code_commit_missing_or_invalid")
    requested = receipt.get("requested_parent_relative_matrices")
    applied = receipt.get("applied_parent_relative_matrices")
    identities = receipt.get("sensor_identities")
    if not isinstance(requested, dict) or not requested:
        errors.append("requested_mount_matrices_missing")
    if not isinstance(identities, dict) or not identities:
        errors.append("sensor_identities_missing")
    if require_live:
        if receipt.get("verification_mode") != "online":
            errors.append("live_verification_required")
        if not isinstance(applied, dict) or set(applied) != set(requested or {}):
            errors.append("observed_applied_mounts_missing_or_incomplete")
        if not isinstance(identities, dict) or set(identities) != set(requested or {}):
            errors.append("sensor_identity_set_mismatch")
        blueprints = receipt.get("blueprint_configuration")
        if not isinstance(blueprints, dict) or set(blueprints) != set(requested or {}):
            errors.append("sensor_blueprint_set_mismatch")
        if not isinstance(receipt.get("ego_identity"), dict) or not receipt["ego_identity"].get("actor_id"):
            errors.append("ego_identity_missing")
        actor_ids: list[int] = []
        camera_names: set[str] = set()
        for name in requested or {}:
            identity = (identities or {}).get(name, {})
            if not identity.get("actor_id") or not identity.get("type_id"):
                errors.append(f"{name}:sensor_identity_incomplete")
                continue
            try:
                actor_ids.append(int(identity["actor_id"]))
            except (TypeError, ValueError):
                errors.append(f"{name}:sensor_actor_id_invalid")
            type_id = str(identity["type_id"])
            if type_id.startswith("sensor.camera"):
                camera_names.add(name)
                camera_config = (receipt.get("effective_camera_configuration") or {}).get(name)
                if not isinstance(camera_config, dict):
                    errors.append(f"{name}:camera_intrinsics_missing")
                else:
                    for key in ("requested_K_undistortion", "carla_nominal_K"):
                        try:
                            matrix = np.asarray(camera_config.get(key), dtype=float)
                            valid_matrix = matrix.shape == (3, 3) and np.isfinite(matrix).all()
                        except (TypeError, ValueError):
                            valid_matrix = False
                        if not valid_matrix:
                            errors.append(f"{name}:{key}_invalid")
                    for key in ("width_px", "height_px"):
                        value = camera_config.get(key)
                        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                            errors.append(f"{name}:{key}_invalid")
            elif type_id.startswith("sensor.lidar"):
                if name in (receipt.get("effective_camera_configuration") or {}):
                    errors.append(f"{name}:lidar_misclassified_as_camera")
            else:
                errors.append(f"{name}:unsupported_sensor_type")
        if len(actor_ids) != len(set(actor_ids)):
            errors.append("duplicate_sensor_actor_ids")
        if set(receipt.get("effective_camera_configuration") or {}) != camera_names:
            errors.append("effective_camera_configuration_sensor_set_mismatch")
        measurements = receipt.get("runtime_measurements")
        if not isinstance(measurements, dict) or set(measurements) != set(requested or {}):
            errors.append("runtime_measurements_missing_or_incomplete")
        else:
            frame_ids: set[int] = set()
            dataset_ids: set[str] = set()
            dataset_hashes: set[str] = set()
            timestamps: list[float] = []
            for name, sample in measurements.items():
                if not isinstance(sample, dict):
                    errors.append(f"{name}:runtime_measurement_invalid")
                    continue
                required_sample_fields = {"frame_id", "timestamp_s", "dataset_identity", "dataset_artifact_sha256"}
                for field in sorted(set(sample) - required_sample_fields):
                    errors.append(f"{name}:unsupported_runtime_measurement_field:{field}")
                for field in sorted(required_sample_fields - set(sample)):
                    errors.append(f"{name}:runtime_measurement_field_missing:{field}")
                frame_id = sample.get("frame_id")
                timestamp = sample.get("timestamp_s")
                if not isinstance(frame_id, int) or isinstance(frame_id, bool) or frame_id < 0:
                    errors.append(f"{name}:runtime_frame_identity_missing")
                else:
                    frame_ids.add(frame_id)
                if not isinstance(timestamp, (float, int)) or isinstance(timestamp, bool) or not math.isfinite(float(timestamp)):
                    errors.append(f"{name}:runtime_timestamp_invalid")
                else:
                    timestamps.append(float(timestamp))
                if not isinstance(sample.get("dataset_identity"), str) or not sample["dataset_identity"]:
                    errors.append(f"{name}:dataset_identity_missing")
                else:
                    dataset_ids.add(sample["dataset_identity"])
                if not re.fullmatch(r"[0-9a-f]{64}", str(sample.get("dataset_artifact_sha256", ""))):
                    errors.append(f"{name}:dataset_artifact_sha256_missing_or_invalid")
                else:
                    dataset_hashes.add(sample["dataset_artifact_sha256"])
            if len(frame_ids) > 1:
                errors.append("runtime_sensor_frames_not_common")
            if timestamps and max(timestamps) - min(timestamps) > 1e-6:
                errors.append("runtime_sensor_timestamps_not_common")
            if len(dataset_ids) > 1 or len(dataset_hashes) > 1:
                errors.append("runtime_dataset_identity_not_shared")
        if receipt.get("verification_status") != "online_observation_claim_consistent_unattested":
            errors.append("online_observation_claim_not_consistent")
    if isinstance(requested, dict):
        for name, matrix in requested.items():
            try:
                _rigid_matrix(matrix, label=f"requested {name}")
            except (TypeError, ValueError) as exc:
                errors.append(str(exc))
    if isinstance(applied, dict):
        for name, matrix in applied.items():
            try:
                _rigid_matrix(matrix, label=f"applied {name}")
                if name in (requested or {}):
                    residual = _residuals(requested[name], matrix)
                    if residual["position_m"] > POSITION_RESIDUAL_LIMIT_M:
                        errors.append(f"{name}:position_residual_exceeded")
                    if residual["angle_deg"] > ANGULAR_RESIDUAL_LIMIT_DEG:
                        errors.append(f"{name}:angular_residual_exceeded")
                    reported = (receipt.get("residuals") or {}).get(name)
                    if not isinstance(reported, dict):
                        errors.append(f"{name}:reported_mount_residual_missing")
                    else:
                        for key in ("position_m", "angle_deg"):
                            try:
                                reported_value = float(reported[key])
                            except (KeyError, TypeError, ValueError):
                                errors.append(f"{name}:reported_{key}_invalid")
                                continue
                            if not math.isfinite(reported_value) or abs(reported_value - residual[key]) > 1e-7:
                                errors.append(f"{name}:reported_{key}_mismatch")
            except (TypeError, ValueError) as exc:
                errors.append(str(exc))
    digest = receipt.get("applied_configuration_sha256")
    identity_digest = receipt.get("identity_binding_sha256")
    if require_live:
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append("applied_configuration_digest_missing")
        elif digest != canonical_sha256(_actual_config_digest_payload(receipt)):
            errors.append("applied_configuration_digest_mismatch")
        if not isinstance(identity_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", identity_digest):
            errors.append("identity_binding_digest_missing")
        elif identity_digest != canonical_sha256(_identity_binding_payload(receipt)):
            errors.append("identity_binding_digest_mismatch")
        receipt_digest = receipt.get("receipt_sha256")
        unsealed = dict(receipt)
        unsealed["receipt_sha256"] = None
        if not isinstance(receipt_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", receipt_digest):
            errors.append("receipt_digest_missing")
        elif receipt_digest != canonical_sha256(unsealed):
            errors.append("receipt_digest_mismatch")
    return errors
