#!/usr/bin/env python3
"""
Calibration sanity checker (offline).

Purpose:
- Avoid ImportError fragility by NOT importing private helpers from thesis_sensor_rig.py.
- Report what the repo's DominikSensorSetup would attach in CARLA for each camera/LiDAR.

Notes:
- This tool is descriptive: it reflects current code behavior in
  ultimate_pipeline.sensors.dominik_sensor_setup.DominikSensorSetup.
- If you later centralize math in rig_transforms.py, update DominikSensorSetup and this tool
  will automatically reflect the new canonical behavior.

Usage (PowerShell):
  python -m ultimate_pipeline.tools.calib_sanity_check --calib .\calib_data.json --out .\_calib_check
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name, "")
    if not v:
        return bool(default)
    return v.strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline calibration sanity checker (DominikSensorSetup-based).")
    ap.add_argument("--calib", required=True, help="Path to calib_data.json")
    ap.add_argument("--out", required=True, help="Output directory for report JSON")
    args = ap.parse_args()

    calib_path = Path(args.calib)
    if not calib_path.exists():
        raise SystemExit(f"Calibration file not found: {calib_path}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Import DominikSensorSetup lazily so this script doesn't fail if carla isn't installed.
    from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup  # noqa: WPS433

    flip_y = _env_bool("SENSOR_FLIP_VEHICLE_Y", True)
    opencv_axes = _env_bool("SENSOR_OPENCV_CAMERA_AXES", True)
    lidar_axes_mode = os.getenv("SENSOR_LIDAR_AXES_MODE", "auto").strip().lower()

    calib: Dict[str, Any] = json.loads(calib_path.read_text(encoding="utf-8", errors="replace"))

    setup = DominikSensorSetup(
        str(calib_path),
        flip_vehicle_y=flip_y,
        opencv_camera_axes=opencv_axes,
        lidar_axes_mode=lidar_axes_mode,
    )

    cams = calib.get("cameras", {}) if isinstance(calib, dict) else {}
    lids = calib.get("lidars", {}) if isinstance(calib, dict) else {}

    report: Dict[str, Any] = {
        "calibration_file": str(calib_path.resolve()),
        "env_flags": {
            "SENSOR_FLIP_VEHICLE_Y": os.getenv("SENSOR_FLIP_VEHICLE_Y", ""),
            "SENSOR_OPENCV_CAMERA_AXES": os.getenv("SENSOR_OPENCV_CAMERA_AXES", ""),
            "SENSOR_LIDAR_AXES_MODE": os.getenv("SENSOR_LIDAR_AXES_MODE", ""),
        },
        "resolved_flags": {
            "flip_vehicle_y": bool(flip_y),
            "opencv_camera_axes": bool(opencv_axes),
            "lidar_axes_mode": str(lidar_axes_mode),
        },
        "cameras": [],
        "lidars": [],
        "notes": [
            "This report reflects DominikSensorSetup parsing code.",
            "Camera: uses K_undistortion; attachment pose is DominikSensorSetup._parse_camera_transform().",
            "LiDAR: attachment pose is DominikSensorSetup._parse_lidar_transform().",
        ],
    }

    for name, cam in cams.items():
        entry: Dict[str, Any] = {"name": name}
        try:
            entry["raw_cTv"] = cam.get("cTv")
            entry["image_size"] = cam.get("image_size")
            entry["has_K_undistortion"] = bool(cam.get("K_undistortion") is not None)
            entry["attach_transform_dict"] = setup._parse_camera_transform(cam)  # type: ignore[attr-defined]
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {e}"
        report["cameras"].append(entry)

    for name, lid in lids.items():
        entry: Dict[str, Any] = {"name": name}
        try:
            entry["raw_vTl"] = lid.get("vTl")
            entry["attach_transform_dict"] = setup._parse_lidar_transform(lid)  # type: ignore[attr-defined]
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {e}"
        report["lidars"].append(entry)

    out_path = out_dir / "calib_sanity_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"OK wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
