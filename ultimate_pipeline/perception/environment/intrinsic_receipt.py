"""Content-addressed, fail-closed camera calibration receipt helpers.

The receipt proves identity and byte binding only.  It never promotes a
mathematical realization report or a caller-provided capture flag to live
calibration acceptance; that requires independently checked rendered frames.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Mapping

RECEIPT_SCHEMA = "CAMERA_CALIBRATION_RECEIPT/v2"
CAMERA_NAMES = (
    "front_left_camera", "front_right_camera", "left_camera",
    "right_camera", "back_left_camera", "back_right_camera",
)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def current_source_identity(repository_root: str | Path) -> Dict[str, Any]:
    """Return exact HEAD and dirty state; never infer code identity from env."""
    root = Path(repository_root).resolve()
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        text=True, stderr=subprocess.STDOUT,
    ).strip()
    status = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        text=True, stderr=subprocess.STDOUT,
    )
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("source_commit_not_full_sha1")
    return {"commit": commit, "working_tree_clean": not bool(status.strip())}


def dataset_file_inventory(dataset_root: str | Path) -> Dict[str, Any]:
    """Hash every regular file below a capture root; reject empty/stale inputs."""
    root = Path(dataset_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("dataset_root_not_directory")
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"dataset_symlink_forbidden:{path.relative_to(root)}")
        if not path.is_file():
            continue
        data = path.read_bytes()
        if not data:
            raise ValueError(f"dataset_file_empty:{path.relative_to(root)}")
        entries.append({
            "path": path.relative_to(root).as_posix(),
            "size_bytes": len(data),
            "sha256": sha256_bytes(data),
        })
    if not entries:
        raise ValueError("dataset_has_no_captured_files")
    digest = sha256_bytes(canonical_json_bytes(entries))
    return {"file_count": len(entries), "files": entries, "dataset_sha256": digest}


def _validate_matrix(value: Any, name: str) -> list[list[float]]:
    rows = [[float(v) for v in row] for row in value]
    if len(rows) != 3 or any(len(row) != 3 for row in rows):
        raise ValueError(f"{name}_must_be_3x3")
    if not all(__import__("math").isfinite(v) for row in rows for v in row):
        raise ValueError(f"{name}_contains_nonfinite")
    det = (
        rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
        - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
        + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0])
    )
    if abs(det) < 1e-12 or rows[0][0] <= 0 or rows[1][1] <= 0:
        raise ValueError(f"{name}_not_valid_camera_intrinsics")
    if any(abs(rows[2][i] - expected) > 1e-9 for i, expected in enumerate((0.0, 0.0, 1.0))):
        raise ValueError(f"{name}_invalid_homogeneous_row")
    return rows


def build_calibration_receipt(
    *,
    calibration_path: str | Path,
    repository_root: str | Path,
    effective_intrinsics: Mapping[str, Any],
    sensor_identity: Mapping[str, Any],
    runtime_settings: Mapping[str, Any],
    dataset_root: str | Path,
) -> Dict[str, Any]:
    """Build a v2 identity receipt while keeping scientific verdict pending."""
    source = current_source_identity(repository_root)
    if not source["working_tree_clean"]:
        raise ValueError("receipt_requires_clean_committed_source")
    calibration = Path(calibration_path).resolve(strict=True).read_bytes()
    calib = json.loads(calibration.decode("utf-8"))
    expected_cameras = set((calib.get("cameras") or {}).keys())
    if expected_cameras != set(CAMERA_NAMES):
        raise ValueError("calibration_must_define_exact_thesis_six_camera_set")
    actual_k = {str(k): _validate_matrix(v, f"effective_intrinsics.{k}")
                for k, v in effective_intrinsics.items()}
    if set(actual_k) != expected_cameras:
        raise ValueError("effective_intrinsic_camera_set_mismatch")
    sensors = dict(sensor_identity)
    if set(dict(sensors.get("cameras") or {})) != expected_cameras:
        raise ValueError("runtime_camera_sensor_identity_set_mismatch")
    if not dict(sensors.get("lidars") or {}):
        raise ValueError("runtime_active_lidar_identity_missing")
    all_sensors = [*dict(sensors.get("cameras") or {}).values(),
                   *dict(sensors.get("lidars") or {}).values()]
    parent_ids = set()
    actor_ids = set()
    for identity in all_sensors:
        if int(identity.get("actor_id", 0)) <= 0 or int(identity.get("parent_id", 0)) <= 0:
            raise ValueError("runtime_sensor_actor_or_parent_identity_missing")
        parent_ids.add(int(identity["parent_id"]))
        actor_ids.add(int(identity["actor_id"]))
    if len(actor_ids) != len(all_sensors):
        raise ValueError("runtime_sensor_actor_id_duplicate")
    if any("sensor.camera" not in str(item.get("type_id", ""))
           for item in dict(sensors.get("cameras") or {}).values()):
        raise ValueError("runtime_camera_blueprint_identity_invalid")
    if any("sensor.lidar" not in str(item.get("type_id", ""))
           for item in dict(sensors.get("lidars") or {}).values()):
        raise ValueError("runtime_lidar_blueprint_identity_invalid")
    if len(parent_ids) != 1:
        raise ValueError("runtime_sensors_not_attached_to_one_ego")
    if not runtime_settings:
        raise ValueError("runtime_settings_missing")
    if not str(runtime_settings.get("server_version", "")).startswith("0.9.16"):
        raise ValueError("runtime_server_version_not_carla_0_9_16")
    if not runtime_settings.get("map_name"):
        raise ValueError("runtime_map_identity_missing")
    if runtime_settings.get("synchronous_mode") is not True:
        raise ValueError("runtime_synchronous_mode_not_enabled")
    if float(runtime_settings.get("fixed_delta_seconds", 0.0) or 0.0) <= 0:
        raise ValueError("runtime_fixed_delta_missing")
    inventory = dataset_file_inventory(dataset_root)
    runtime_payload = dict(runtime_settings)
    sensor_payload = sensors
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "calibration_sha256": sha256_bytes(calibration),
        "source_commit": source["commit"],
        "source_tree_clean_at_receipt": source["working_tree_clean"],
        "effective_intrinsics": actual_k,
        "effective_intrinsics_sha256": sha256_bytes(canonical_json_bytes(actual_k)),
        "sensor_identity": sensor_payload,
        "sensor_identity_sha256": sha256_bytes(canonical_json_bytes(sensor_payload)),
        "runtime_settings": runtime_payload,
        "runtime_settings_sha256": sha256_bytes(canonical_json_bytes(runtime_payload)),
        "dataset": inventory,
        "exact_intrinsic_compliance": False,
        "live_acceptance": "PENDING_INDEPENDENT_RENDERED_FRAME_VERIFICATION",
        "live_capture_claim": "NOT_ESTABLISHED_BY_RECEIPT_CONSTRUCTION",
    }
    receipt["receipt_sha256"] = sha256_bytes(canonical_json_bytes(receipt))
    return receipt


def write_calibration_receipt(path: str | Path, receipt: Mapping[str, Any]) -> Path:
    """Atomically write only a receipt with complete non-empty bindings."""
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("unsupported_calibration_receipt_schema")
    required = (
        "calibration_sha256", "source_commit", "effective_intrinsics_sha256",
        "sensor_identity_sha256", "runtime_settings_sha256", "dataset",
    )
    if any(not receipt.get(key) for key in required):
        raise ValueError("calibration_receipt_binding_missing")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(json.dumps(receipt, sort_keys=True, indent=2).encode("utf-8"))
    os.replace(tmp, target)
    return target


def verify_calibration_receipt(
    receipt: Mapping[str, Any], *, calibration_path: str | Path,
    repository_root: str | Path, dataset_root: str | Path,
) -> Dict[str, Any]:
    """Recheck all byte identities and source cleanliness for a stored receipt."""
    reasons = []
    try:
        current_source = current_source_identity(repository_root)
        if not current_source["working_tree_clean"]:
            reasons.append("source_tree_dirty")
        if current_source["commit"] != receipt.get("source_commit"):
            reasons.append("source_commit_mismatch")
        if sha256_bytes(Path(calibration_path).resolve(strict=True).read_bytes()) != receipt.get("calibration_sha256"):
            reasons.append("calibration_bytes_mismatch")
        current_dataset = dataset_file_inventory(dataset_root)
        if current_dataset["dataset_sha256"] != (receipt.get("dataset") or {}).get("dataset_sha256"):
            reasons.append("dataset_bytes_mismatch")
        if sha256_bytes(canonical_json_bytes(receipt.get("effective_intrinsics"))) != receipt.get("effective_intrinsics_sha256"):
            reasons.append("effective_intrinsics_digest_mismatch")
        if sha256_bytes(canonical_json_bytes(receipt.get("sensor_identity"))) != receipt.get("sensor_identity_sha256"):
            reasons.append("sensor_identity_digest_mismatch")
        if sha256_bytes(canonical_json_bytes(receipt.get("runtime_settings"))) != receipt.get("runtime_settings_sha256"):
            reasons.append("runtime_settings_digest_mismatch")
        body = dict(receipt)
        declared = body.pop("receipt_sha256", None)
        if sha256_bytes(canonical_json_bytes(body)) != declared:
            reasons.append("receipt_digest_mismatch")
        if receipt.get("exact_intrinsic_compliance") is not False:
            reasons.append("unverified_exact_intrinsic_claim")
        if receipt.get("live_acceptance") != "PENDING_INDEPENDENT_RENDERED_FRAME_VERIFICATION":
            reasons.append("unexpected_live_acceptance_status")
    except Exception as exc:
        reasons.append(f"verification_error:{type(exc).__name__}:{exc}")
    return {"valid": not reasons, "invalid_reasons": reasons,
            "verdict": "IDENTITY_VALID_PENDING_SCIENTIFIC_REVIEW" if not reasons else "INVALID"}
