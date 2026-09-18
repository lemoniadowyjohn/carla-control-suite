#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Calibration sanity harness:
- forward object alignment
- ground plane projection
- lidar-camera projection consistency
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.carla_tools.safe_spawn_ego import safe_spawn_ego
from ultimate_pipeline.sensors.attach_sensors_safe import load_calib


def _apply_transform(T: List[List[float]], p: Tuple[float, float, float]) -> Tuple[float, float, float]:
    x, y, z = p
    return (
        T[0][0] * x + T[0][1] * y + T[0][2] * z + T[0][3],
        T[1][0] * x + T[1][1] * y + T[1][2] * z + T[1][3],
        T[2][0] * x + T[2][1] * y + T[2][2] * z + T[2][3],
    )


def _project_point(K: List[List[float]], p_cam: Tuple[float, float, float]) -> Optional[Tuple[float, float]]:
    x, y, z = p_cam
    if z <= 1e-6:
        return None
    fx = K[0][0]
    fy = K[1][1]
    cx = K[0][2]
    cy = K[1][2]
    u = fx * x / z + cx
    v = fy * y / z + cy
    return float(u), float(v)


def _in_bounds(u: float, v: float, w: int, h: int) -> bool:
    return 0.0 <= u < float(w) and 0.0 <= v < float(h)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _capture_first_frames(world, sensors: Dict[str, Any], out_dir: Path, timeout_s: float = 5.0) -> Dict[str, Any]:
    report: Dict[str, Any] = {"captured": {}, "warnings": []}
    out_dir.mkdir(parents=True, exist_ok=True)
    done: Dict[str, bool] = {}

    def make_cam_cb(name: str):
        def _cb(image):
            if done.get(name):
                return
            path = out_dir / f"{name}.png"
            image.save_to_disk(str(path))
            done[name] = True
        return _cb

    listeners = []
    for name, actor in sensors.items():
        try:
            if actor.type_id.startswith("sensor.camera"):
                actor.listen(make_cam_cb(name))
                listeners.append(actor)
        except Exception:
            report["warnings"].append(f"failed to listen camera {name}")

    start = time.time()
    while time.time() - start < timeout_s:
        try:
            world.tick()
        except Exception:
            break
        if all(done.get(name) for name, actor in sensors.items() if actor.type_id.startswith("sensor.camera")):
            break

    for s in listeners:
        try:
            s.stop()
        except Exception:
            pass

    for name in done:
        report["captured"][name] = str((out_dir / f"{name}.png").as_posix())
    return report


def run_calibration_sanity_check(
    *,
    calib_path: str,
    out_dir: str,
    host: str,
    port: int,
    timeout: float,
    spawn_index: int,
    z_offset: float,
    camera_optical_frame: bool,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "ok": False,
        "calib_path": calib_path,
        "checks": {},
        "screenshots": {},
        "errors": [],
    }

    try:
        import carla  # type: ignore
    except Exception as exc:
        report["errors"].append(f"carla not available: {exc}")
        return report

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    try:
        cams, lids = load_calib(calib_path)
    except Exception as exc:
        report["errors"].append(f"failed to load calib: {exc}")
        return report

    client = carla.Client(host, port)
    client.set_timeout(timeout)
    world = client.get_world()

    ego, ego_report = safe_spawn_ego(
        world,
        spawn_index=spawn_index,
        z_offset=z_offset,
        report_path=str(out_path / "ego_spawn_report.json"),
    )
    if ego is None:
        report["errors"].append("ego spawn failed")
        return report

    from ultimate_pipeline.sensors.attach_sensors_safe import attach_sensors_safe

    sensors, attach_report = attach_sensors_safe(
        world,
        ego,
        calib_path,
        out_dir=str(out_path),
        camera_optical_frame=camera_optical_frame,
    )
    if not sensors:
        report["errors"].append("sensor attach failed")
        return report

    screenshot_report = _capture_first_frames(world, sensors, out_path / "screenshots")
    report["screenshots"] = screenshot_report

    for name, cam in cams.items():
        K = cam.K_undist
        width = cam.width
        height = cam.height
        cTv = cam.cTv

        forward_point = (10.0, 0.0, 0.0)
        p_cam = _apply_transform(cTv, forward_point)
        px = _project_point(K, p_cam)
        forward_ok = px is not None and _in_bounds(px[0], px[1], width, height)

        ground_points = [(5.0, 0.0, 0.0), (10.0, 2.0, 0.0), (15.0, -2.0, 0.0)]
        ground_hits = 0
        for gp in ground_points:
            p_cam_g = _apply_transform(cTv, gp)
            pxg = _project_point(K, p_cam_g)
            if pxg is not None and _in_bounds(pxg[0], pxg[1], width, height):
                ground_hits += 1
        ground_ok = ground_hits >= 1

        lidar_checks = {}
        for lname, lid in lids.items():
            vTl = lid.vTl
            p_vehicle = _apply_transform(vTl, (5.0, 0.0, 0.0))
            p_cam_l = _apply_transform(cTv, p_vehicle)
            pxl = _project_point(K, p_cam_l)
            lidar_checks[lname] = {
                "ok": pxl is not None,
                "pixel": [pxl[0], pxl[1]] if pxl else None,
            }

        report["checks"][name] = {
            "forward_alignment": {"ok": forward_ok, "pixel": [px[0], px[1]] if px else None},
            "ground_plane": {"ok": ground_ok, "hits": ground_hits},
            "lidar_camera_consistency": lidar_checks,
        }

    checks_ok = True
    for cam_name, cam_checks in report["checks"].items():
        if not cam_checks.get("forward_alignment", {}).get("ok", False):
            checks_ok = False
        if not cam_checks.get("ground_plane", {}).get("ok", False):
            checks_ok = False
        lidar_checks = cam_checks.get("lidar_camera_consistency", {})
        if lidar_checks and not all(item.get("ok", False) for item in lidar_checks.values()):
            checks_ok = False

    report["ok"] = checks_ok
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", required=True, help="Path to calib_data.json")
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--spawn-index", type=int, default=0)
    ap.add_argument("--z-offset", type=float, default=0.5)
    ap.add_argument("--camera-optical", action="store_true")
    args = ap.parse_args()

    report = run_calibration_sanity_check(
        calib_path=args.calib,
        out_dir=args.out,
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        spawn_index=args.spawn_index,
        z_offset=args.z_offset,
        camera_optical_frame=args.camera_optical,
    )
    _write_json(Path(args.out) / "calibration_sanity_report.json", report)
    if not report.get("ok", False):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
