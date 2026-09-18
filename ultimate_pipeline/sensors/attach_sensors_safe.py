#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Safe sensor attachment helper using calib_data.json.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


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


def invert_rigid_transform(T: List[List[float]]) -> List[List[float]]:
    R = [[T[r][c] for c in range(3)] for r in range(3)]
    t = [T[r][3] for r in range(3)]
    Rt = [[R[c][r] for c in range(3)] for r in range(3)]
    tinv = [
        -(Rt[0][0] * t[0] + Rt[0][1] * t[1] + Rt[0][2] * t[2]),
        -(Rt[1][0] * t[0] + Rt[1][1] * t[1] + Rt[1][2] * t[2]),
        -(Rt[2][0] * t[0] + Rt[2][1] * t[1] + Rt[2][2] * t[2]),
    ]
    return [
        [Rt[0][0], Rt[0][1], Rt[0][2], tinv[0]],
        [Rt[1][0], Rt[1][1], Rt[1][2], tinv[1]],
        [Rt[2][0], Rt[2][1], Rt[2][2], tinv[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _rotmat_to_euler_zyx_deg(R: List[List[float]]) -> Tuple[float, float, float]:
    v = -R[2][0]
    v = max(-1.0, min(1.0, v))
    pitch = math.asin(v)
    roll = math.atan2(R[2][1], R[2][2])
    yaw = math.atan2(R[1][0], R[0][0])
    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)


def _fov_from_K(K: List[List[float]], width_px: int) -> float:
    fx = float(K[0][0]) if K and K[0] else 0.0
    if fx <= 1e-9:
        return 90.0
    return float(2.0 * math.degrees(math.atan(width_px / (2.0 * fx))))


def _carla_transform_from_vehicle_to_sensor(
    T_v_s: List[List[float]],
    *,
    camera_optical_frame: bool,
):
    try:
        import carla  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"carla not available: {exc}") from exc

    T_s_v = invert_rigid_transform(T_v_s)
    R_v_s = [[T_s_v[r][c] for c in range(3)] for r in range(3)]
    t_v_s = [T_s_v[r][3] for r in range(3)]

    if camera_optical_frame:
        R_carla_from_optical = [
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 0.0],
            [0.0, -1.0, 0.0],
        ]
        R_optical_from_carla = [
            [R_carla_from_optical[c][r] for c in range(3)] for r in range(3)
        ]
        R_v_s = [
            [
                R_v_s[r][0] * R_optical_from_carla[0][c]
                + R_v_s[r][1] * R_optical_from_carla[1][c]
                + R_v_s[r][2] * R_optical_from_carla[2][c]
                for c in range(3)
            ]
            for r in range(3)
        ]

    roll, pitch, yaw = _rotmat_to_euler_zyx_deg(R_v_s)
    loc = carla.Location(x=float(t_v_s[0]), y=float(t_v_s[1]), z=float(t_v_s[2]))
    rot = carla.Rotation(roll=float(roll), pitch=float(pitch), yaw=float(yaw))
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


def load_calib(path: str) -> Tuple[Dict[str, CameraCalib], Dict[str, LidarCalib]]:
    data = json.loads(open(path, "r", encoding="utf-8").read())

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
        "schema_version": 1,
        "ok": False,
        "calib_path": str(calib_path),
        "calib_sha256": _sha256_of_file(calib_path),
        "camera_intrinsics_source": "K_undistortion",
        "camera_extrinsics_mode": "cTv_direct",
        "lidar_extrinsics_mode": "invert_vTl",
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
        cams, lids = load_calib(calib_path)
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
            report["attached"][name] = {"type": "camera", "ok": True}
            active_camera_count += 1
        except Exception as exc:
            report["attached"][name] = {"type": "camera", "ok": False, "error": str(exc)}

    lidar_bp = bp_lib.find("sensor.lidar.ray_cast")
    if lidar_bp is None:
        report["warnings"].append("missing blueprint: sensor.lidar.ray_cast")
    else:
        for name, lid in lids.items():
            try:
                bp = lidar_bp
                bp.set_attribute("range", "80")
                bp.set_attribute("rotation_frequency", "20")
                bp.set_attribute("channels", "64")
                bp.set_attribute("points_per_second", "200000")
                bp.set_attribute("upper_fov", "10")
                bp.set_attribute("lower_fov", "-30")
                bp.set_attribute("sensor_tick", "0.0")

                vTl_inv = invert_rigid_transform(lid.vTl)
                tf = _carla_transform_from_vehicle_to_sensor(vTl_inv, camera_optical_frame=False)
                actor = world.spawn_actor(bp, tf, attach_to=ego)
                sensors[name] = actor
                report["attached"][name] = {"type": "lidar", "ok": True}
                active_lidar_count += 1
            except Exception as exc:
                report["attached"][name] = {"type": "lidar", "ok": False, "error": str(exc)}

    report["ok"] = all(item.get("ok", False) for item in report["attached"].values()) if report["attached"] else False
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
