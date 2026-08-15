from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np

from ultimate_pipeline.contracts.agent_sync import load_agent_sync
from ultimate_pipeline.sensors.transform_conventions import (
    vehicle_to_camera_from_cTv,
    vehicle_to_lidar_from_vTl,
)

CALIBRATION_SEMANTICS = {
    "camera_model": "CARLA ideal pinhole",
    "effective_intrinsics_source": "K_undistortion_ideal_pinhole",
    "ignored_sources": ["K", "D"],
    "distortion_in_carla": "none",
    "use_K_undistortion": "legacy flag meaning: use the rectified K_undistortion matrix as the pinhole FOV source",
    "cTv": "vehicle_to_camera_used_directly_not_inverted",
    "vTl": "lidar_to_vehicle_inverted_to_vehicle_to_lidar",
}


def canonical_calib_path() -> Path:
    return Path(__file__).resolve().parent / "calib_data.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_image_size(value: Any) -> Tuple[int, int]:
    if isinstance(value, dict):
        return int(value["width"]), int(value["height"])
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return int(value[0]), int(value[1])
    raise RuntimeError(f"Unsupported image_size format: {value!r}")


def _ensure_matrix(matrix: Any, shape: Tuple[int, int], name: str) -> np.ndarray:
    arr = np.asarray(matrix, dtype=float)
    if arr.shape != shape:
        raise RuntimeError(f"{name} must be {shape}, got {arr.shape}")
    return arr


def fov_deg_from_k_undistortion(k_undistortion: Any, width_px: int) -> float:
    K = _ensure_matrix(k_undistortion, (3, 3), "K_undistortion")
    fx = float(K[0, 0])
    if fx <= 1e-9:
        raise RuntimeError("K_undistortion fx must be positive")
    return float(2.0 * math.degrees(math.atan(float(width_px) / (2.0 * fx))))


def effective_camera_intrinsics(camera: Dict[str, Any]) -> Dict[str, Any]:
    if "K_undistortion" not in camera:
        raise RuntimeError("Camera calibration missing K_undistortion")
    if "image_size" not in camera:
        raise RuntimeError("Camera calibration missing image_size")
    K = _ensure_matrix(camera["K_undistortion"], (3, 3), "K_undistortion")
    width, height = parse_image_size(camera["image_size"])
    if width <= 0 or height <= 0:
        raise RuntimeError(f"image_size must be positive, got {(width, height)}")
    return {
        "source": "K_undistortion_ideal_pinhole",
        "ignored_sources": ["K", "D"],
        "width_px": int(width),
        "height_px": int(height),
        "fx": float(K[0, 0]),
        "fy": float(K[1, 1]),
        "cx": float(K[0, 2]),
        "cy": float(K[1, 2]),
        "horizontal_fov_deg": fov_deg_from_k_undistortion(K, width),
    }


def load_calibration(path: Path | None = None) -> Dict[str, Any]:
    resolved = canonical_calib_path() if path is None else Path(path)
    return json.loads(resolved.read_text(encoding="utf-8"))


def rig_round_trip_check(calib_path: Path | None = None) -> Dict[str, Any]:
    path = canonical_calib_path() if calib_path is None else Path(calib_path)
    data = load_calibration(path)
    camera_reports: Dict[str, Any] = {}
    lidar_reports: Dict[str, Any] = {}
    errors = []

    for name, camera in (data.get("cameras") or {}).items():
        try:
            ctv = _ensure_matrix(camera["cTv"], (4, 4), f"{name}.cTv")
            vehicle_to_camera = vehicle_to_camera_from_cTv(
                ctv,
                flip_vehicle_y=False,
                opencv_camera_axes=False,
                ctv_invert=False,
            )
            camera_reports[name] = {
                "intrinsics": effective_camera_intrinsics(camera),
                "vehicle_to_camera_matrix": vehicle_to_camera.tolist(),
                "ctv_direct_not_inverted": bool(np.allclose(vehicle_to_camera, ctv)),
            }
            if not camera_reports[name]["ctv_direct_not_inverted"]:
                errors.append(f"{name}: cTv was not applied directly")
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    for name, lidar in (data.get("lidars") or {}).items():
        try:
            vtl = _ensure_matrix(lidar["vTl"], (4, 4), f"{name}.vTl")
            vehicle_to_lidar = vehicle_to_lidar_from_vTl(vtl, flip_vehicle_y=False)
            expected = np.linalg.inv(vtl)
            lidar_reports[name] = {
                "vehicle_to_lidar_matrix": vehicle_to_lidar.tolist(),
                "vtl_inverted": bool(np.allclose(vehicle_to_lidar, expected)),
            }
            if not lidar_reports[name]["vtl_inverted"]:
                errors.append(f"{name}: vTl was not inverted")
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    return {
        "schema": "D2_SENSOR_CALIBRATION_ROUND_TRIP/v1",
        "verdict": "PASS" if not errors and camera_reports and lidar_reports else "FAIL_CLOSED",
        "calib_path": str(path),
        "calib_sha256": sha256_file(path),
        "calibration_semantics": CALIBRATION_SEMANTICS,
        "cameras": camera_reports,
        "lidars": lidar_reports,
        "errors": errors,
    }


def validate_calibration_contract(
    calib_path: Path | None = None,
    agent_sync_path: Path | None = None,
) -> Dict[str, Any]:
    path = canonical_calib_path() if calib_path is None else Path(calib_path)
    data = load_calibration(path)
    sync = load_agent_sync(agent_sync_path)
    errors = []

    rig = sync.sensor_rig
    if not rig.use_K_undistortion or not rig.ignore_K or not rig.ignore_D:
        errors.append("agent_sync must declare use_K_undistortion=true and ignore_K/D=true")
    if rig.ctv_inverted:
        errors.append("agent_sync must declare ctv_inverted=false")
    if not rig.vtl_inverted:
        errors.append("agent_sync must declare vtl_inverted=true")

    camera_intrinsics = {}
    for name, camera in (data.get("cameras") or {}).items():
        try:
            _ensure_matrix(camera["cTv"], (4, 4), f"{name}.cTv")
            camera_intrinsics[name] = effective_camera_intrinsics(camera)
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    for name, lidar in (data.get("lidars") or {}).items():
        try:
            _ensure_matrix(lidar["vTl"], (4, 4), f"{name}.vTl")
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    round_trip = rig_round_trip_check(path)
    if round_trip["verdict"] != "PASS":
        errors.extend(round_trip.get("errors", []))

    return {
        "schema": "D2_SENSOR_CALIBRATION_CONTRACT/v1",
        "verdict": "PASS" if not errors else "FAIL_CLOSED",
        "calib_path": str(path),
        "calib_sha256": sha256_file(path),
        "camera_count": len(data.get("cameras") or {}),
        "lidar_count": len(data.get("lidars") or {}),
        "calibration_semantics": CALIBRATION_SEMANTICS,
        "camera_intrinsics": camera_intrinsics,
        "round_trip": round_trip,
        "errors": errors,
    }
