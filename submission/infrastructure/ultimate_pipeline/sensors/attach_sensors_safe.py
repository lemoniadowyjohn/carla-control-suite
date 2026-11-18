#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Safe sensor attachment helper using calib_data.json.

NEW-301: Consumes canonical LiDAR runtime spec from canonical_lidar_spec.py
NEW-299: Returns runtime rig identity from spawned/verified actors
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.sensors.transform_conventions import (
    CALIBRATION_CONTRACT_VERSION,
    carla_attachment_pose_from_matrix,
    carla_ego_from_camera_from_cTv,
    carla_ego_from_lidar_from_vTl,
)
from ultimate_pipeline.sensors.applied_sensor_rig import (
    build_applied_sensor_rig_v2,
    current_clean_code_commit,
    observed_parent_relative_mount,
    validate_applied_sensor_rig_v2,
)
from ultimate_pipeline.sensors.canonical_lidar_spec import (
    resolve_active_lidars,
    all_lidar_specs,
    canonical_lidar_hash,
)


def _ensure_mat4(m: Any, name: str) -> List[List[float]]:
    if not isinstance(m, (list, tuple)) or len(m) != 4:
        raise ValueError(f"{name} must be 4x4")
    out: List[List[float]] = []
    for row in m:
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            raise ValueError(f"{name} must be 4x4")
        out.append([float(v) for v in row])
    return out


def _ensure_mat3(m: Any, name: str) -> List[List[float]]:
    if not isinstance(m, (list, tuple)) or len(m) != 3:
        raise ValueError(f"{name} must be 3x3")
    out: List[List[float]] = []
    for row in m:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            raise ValueError(f"{name} must be 3x3")
        out.append([float(v) for v in row])
    return out


def _fov_from_K(K: List[List[float]], width_px: int) -> float:
    fx = float(K[0][0]) if K and K[0] else 0.0
    if fx <= 1e-9:
        return 90.0
    return float(2.0 * math.degrees(math.atan(width_px / (2.0 * fx))))


def _carla_transform_from_vehicle_to_sensor(
    source_calibration_transform: List[List[float]],
    *,
    camera_optical_frame: bool,
):
    """Compatibility adapter routed through the authoritative v2 frame API.

    For ``camera_optical_frame=True``, input is source ``cTv``. Otherwise it is
    source ``vTl``. The historic parameter name is retained for callers, but no
    manual inversion or one-sided handedness flip is performed here.
    """
    try:
        import carla  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"carla not available: {exc}") from exc

    mount = (
        carla_ego_from_camera_from_cTv(source_calibration_transform)
        if camera_optical_frame
        else carla_ego_from_lidar_from_vTl(source_calibration_transform)
    )
    pose = carla_attachment_pose_from_matrix(mount)
    loc = carla.Location(x=pose["x"], y=pose["y"], z=pose["z"])
    rot = carla.Rotation(roll=pose["roll"], pitch=pose["pitch"], yaw=pose["yaw"])
    return carla.Transform(loc, rot)


@dataclass(frozen=True)
class CameraCalib:
    name: str
    width: int
    height: int
    K_undist: List[List[float]]
    cTv: List[List[float]]  # vehicle -> camera


@dataclass(frozen=True)
class LidarCalib:
    name: str
    vTl: List[List[float]]  # lidar -> vehicle


def _calibration_views(data: Dict[str, Any]) -> Tuple[Dict[str, CameraCalib], Dict[str, LidarCalib]]:
    cams: Dict[str, CameraCalib] = {}
    for name, c in (data.get("cameras") or {}).items():
        w, h = int(c["image_size"][0]), int(c["image_size"][1])
        cams[name] = CameraCalib(
            name=name,
            width=w,
            height=h,
            K_undist=_ensure_mat3(c["K_undistortion"], f"{name}.K_undistortion"),
            cTv=_ensure_mat4(c["cTv"], f"{name}.cTv"),
        )

    lids: Dict[str, LidarCalib] = {}
    for name, l in (data.get("lidars") or {}).items():
        lids[name] = LidarCalib(name=name, vTl=_ensure_mat4(l["vTl"], f"{name}.vTl"))

    return cams, lids


def load_calib(path: str) -> Tuple[Dict[str, CameraCalib], Dict[str, LidarCalib]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return _calibration_views(data)


def _sha256_of_file(path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _build_rig_contract_report(calib_path: str) -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "calibration_contract_version": CALIBRATION_CONTRACT_VERSION,
        "ok": False,
        "calib_path": str(calib_path),
        "calib_sha256": _sha256_of_file(calib_path),
        "camera_intrinsics_source": "K_undistortion",
        "camera_extrinsics_mode": "inverse(cTv) with FLU/FRU and optical basis changes",
        "lidar_extrinsics_mode": "vTl with FLU/FRU basis changes",
        "translation_unit": "metre",
        "active_camera_count": 0,
        "active_lidar_count": 0,
        "active_sensor_count": 0,
        "errors": [],
        "warnings": [],
    }


def _write_reports(out_dir: str, report: Dict[str, Any], contract: Dict[str, Any]) -> None:
    _write_json(out_dir, "sensor_attach_report.json", report)
    _write_json(out_dir, "rig_contract_report.json", contract)


def attach_sensors_safe(
    world,
    ego,
    calib_path: str,
    out_dir: str,
    *,
    camera_optical_frame: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    report: Dict[str, Any] = {
        "ok": False,
        "calib_path": calib_path,
        "attached": {},
        "errors": [],
        "warnings": [],
    }
    contract: Dict[str, Any] = _build_rig_contract_report(calib_path)
    active_camera_count = 0
    active_lidar_count = 0

    try:
        calibration_bytes = Path(calib_path).read_bytes()
        calib_data = json.loads(calibration_bytes.decode("utf-8"))
        if not isinstance(calib_data, dict):
            raise ValueError("calibration document must be a JSON object")
        cams, lids = _calibration_views(calib_data)
        source_calibration_sha256 = hashlib.sha256(calibration_bytes).hexdigest()
        # NEW-301: the canonical LiDAR spec is resolved from the calibration
        # document itself. `load_calib` returns only the parsed camera/LiDAR
        # sub-records, so the raw document is read here as well; referencing
        # the parsed views instead would silently drop the per-LiDAR runtime
        # attributes (range/channels/...) that the spec is built from.
    except Exception as exc:
        report["errors"].append(f"failed to load calib: {exc}")
        contract["errors"] = list(report["errors"])
        contract["warnings"] = list(report["warnings"])
        _write_reports(out_dir, report, contract)
        return {}, report

    try:
        import carla  # type: ignore
    except Exception as exc:
        report["errors"].append(f"carla not available: {exc}")
        contract["errors"] = list(report["errors"])
        contract["warnings"] = list(report["warnings"])
        _write_reports(out_dir, report, contract)
        return {}, report

    bp_lib = world.get_blueprint_library()
    sensors: Dict[str, Any] = {}

    cam_bp = bp_lib.find("sensor.camera.rgb")
    if cam_bp is None:
        report["errors"].append("missing blueprint: sensor.camera.rgb")
        contract["errors"] = list(report["errors"])
        contract["warnings"] = list(report["warnings"])
        _write_reports(out_dir, report, contract)
        return {}, report

    for name, cam in cams.items():
        try:
            bp = cam_bp
            bp.set_attribute("image_size_x", str(cam.width))
            bp.set_attribute("image_size_y", str(cam.height))
            bp.set_attribute("fov", str(_fov_from_K(cam.K_undist, cam.width)))
            bp.set_attribute("sensor_tick", "0.0")

            tf = _carla_transform_from_vehicle_to_sensor(cam.cTv, camera_optical_frame=camera_optical_frame)
            actor = world.spawn_actor(bp, tf, attach_to=ego)
            sensors[name] = actor
            report["attached"][name] = {
                "type": "camera", "ok": True,
                "blueprint_id": getattr(bp, "id", "sensor.camera.rgb"),
                "attributes": {"image_size_x": str(cam.width), "image_size_y": str(cam.height), "fov": str(_fov_from_K(cam.K_undist, cam.width)), "sensor_tick": "0.0"},
            }
            active_camera_count += 1
        except Exception as exc:
            report["attached"][name] = {"type": "camera", "ok": False, "error": str(exc)}

    lidar_bp = bp_lib.find("sensor.lidar.ray_cast")
    if lidar_bp is None:
        report["errors"].append("missing required blueprint: sensor.lidar.ray_cast")
    else:
        # NEW-301: Consume canonical LiDAR runtime spec instead of hard-coded values
        lidar_specs = resolve_active_lidars(calib_data, low_memory_profile=False)
        # NEW-300/301: a required active LiDAR that is absent from calibration is
        # a FAIL, not a warning: silently spawning zero LiDARs would invalidate
        # every downstream perception claim.
        if not lidar_specs:
            report["errors"].append("required_active_lidar_missing_from_calibration")
        for lidar_spec in lidar_specs:
            name = lidar_spec.name
            lid = lids.get(name)
            if lid is None:
                report["attached"][name] = {"type": "lidar", "ok": False,
                                            "error": "lidar_not_in_calibration"}
                continue
            try:
                bp = lidar_bp
                bp.set_attribute("range", str(lidar_spec.range))
                bp.set_attribute("rotation_frequency",
                                 str(int(lidar_spec.rotation_frequency)))
                bp.set_attribute("channels", str(lidar_spec.channels))
                bp.set_attribute("points_per_second",
                                 str(lidar_spec.points_per_second))
                bp.set_attribute("upper_fov", str(lidar_spec.upper_fov))
                bp.set_attribute("lower_fov", str(lidar_spec.lower_fov))
                bp.set_attribute("sensor_tick", str(lidar_spec.sensor_tick))

                tf = _carla_transform_from_vehicle_to_sensor(
                lid.vTl, camera_optical_frame=False
                )
                actor = world.spawn_actor(bp, tf, attach_to=ego)
                sensors[name] = actor
                report["attached"][name] = {
                    "type": "lidar", "ok": True,
                    "blueprint_id": getattr(bp, "id", "sensor.lidar.ray_cast"),
                    "attributes": {
                        "range": str(lidar_spec.range),
                        "rotation_frequency": str(int(lidar_spec.rotation_frequency)),
                        "channels": str(lidar_spec.channels),
                        "points_per_second": str(lidar_spec.points_per_second),
                        "upper_fov": str(lidar_spec.upper_fov),
                        "lower_fov": str(lidar_spec.lower_fov),
                        "sensor_tick": str(lidar_spec.sensor_tick),
                    },
                }
                active_lidar_count += 1
            except Exception as exc:
                report["attached"][name] = {
                    "type": "lidar", "ok": False, "error": str(exc)
                }

    requested = {
        name: carla_ego_from_camera_from_cTv(value["cTv"]).tolist()
        for name, value in sorted((calib_data.get("cameras") or {}).items())
    }
    for spec in resolve_active_lidars(calib_data, low_memory_profile=False):
        value = (calib_data.get("lidars") or {}).get(spec.name)
        if value is not None:
            if spec.name in requested:
                report["errors"].append(f"duplicate calibration sensor name: {spec.name}")
                continue
            requested[spec.name] = carla_ego_from_lidar_from_vTl(value["vTl"]).tolist()
    observed, identities, blueprints, effective_cameras = {}, {}, {}, {}
    for name, actor in sorted(sensors.items()):
        try:
            observed[name] = observed_parent_relative_mount(
                ego.get_transform(), actor.get_transform()
            ).tolist()
        except Exception as exc:
            report["attached"][name]["observed_transform_error"] = f"{type(exc).__name__}:{exc}"
        item = report["attached"][name]
        identities[name] = {"actor_id": getattr(actor, "id", None), "type_id": getattr(actor, "type_id", item.get("type"))}
        blueprints[name] = {"blueprint_id": item.get("blueprint_id"), "attributes": item.get("attributes", {})}
        if item.get("type") == "camera":
            camera = cams[name]
            width, height = camera.width, camera.height
            fov = _fov_from_K(camera.K_undist, width)
            fx = width / (2.0 * math.tan(math.radians(fov) / 2.0))
            effective_cameras[name] = {
                "width_px": width, "height_px": height,
                "requested_K_undistortion": camera.K_undist,
                "carla_nominal_K": [[fx, 0.0, width / 2.0], [0.0, fx, height / 2.0], [0.0, 0.0, 1.0]],
                "horizontal_fov_deg": fov,
                "intrinsic_status": "nominal_from_applied_size_and_fov_rendered_frame_unverified",
            }
    receipt = build_applied_sensor_rig_v2(
        source_calibration_sha256=source_calibration_sha256,
        code_commit=current_clean_code_commit(Path(__file__).resolve().parents[2]),
        requested_parent_relative_matrices=requested,
        ego_identity={"actor_id": getattr(ego, "id", None), "type_id": getattr(ego, "type_id", None)},
        sensor_identities=identities,
        blueprint_configuration=blueprints,
        effective_camera_configuration=effective_cameras,
        applied_parent_relative_matrices=observed if observed else None,
        verification_mode="online",
    )
    report["applied_sensor_rig_v2"] = receipt
    report["applied_sensor_rig_v2_errors"] = validate_applied_sensor_rig_v2(
        receipt,
        require_live=True,
        expected_source_calibration_sha256=source_calibration_sha256,
        expected_calibration_bytes=calibration_bytes,
    )
    report["applied_sensor_rig_v2_live_accepted"] = not report["applied_sensor_rig_v2_errors"]
    contract["applied_sensor_rig_v2"] = receipt
    contract["applied_sensor_rig_v2_errors"] = list(report["applied_sensor_rig_v2_errors"])
    report["ok"] = (
        bool(report["attached"])
        and all(item.get("ok", False) for item in report["attached"].values())
        and not report["errors"]
        and not report["applied_sensor_rig_v2_errors"]
    )
    contract["ok"] = bool(report["ok"])
    contract["active_camera_count"] = int(active_camera_count)
    contract["active_lidar_count"] = int(active_lidar_count)
    contract["active_sensor_count"] = int(active_camera_count + active_lidar_count)
    contract["errors"] = list(report["errors"])
    contract["warnings"] = list(report["warnings"])
    _write_reports(out_dir, report, contract)
    return sensors, report


def _write_json(out_dir: str, name: str, payload: Dict[str, Any]) -> None:
    try:
        import os

        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass
