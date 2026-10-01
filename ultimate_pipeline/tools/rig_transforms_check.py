#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline cross-check: canonical attachment poses vs DominikSensorSetup parsing.

This was previously ``ultimate_pipeline/sensors/rig_transforms.py``. It was a
script, not a module: it read ``calib_data.json`` from the current working
directory at import time and self-imported, so merely importing anything in the
sensors package executed cwd-dependent work and could raise. It also competed
with ``ultimate_pipeline.sensors.transform_conventions`` as a second source of
attachment-pose math.

It is relocated here, out of the sensors package, and made import-safe:

* no module-level file reads, no module-level execution;
* the canonical pose authority stays
  ``ultimate_pipeline.sensors.transform_conventions``; this tool only verifies
  that ``DominikSensorSetup`` agrees with it;
* run it explicitly:
  ``python -m ultimate_pipeline.tools.rig_transforms_check <calib.json>``
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from ultimate_pipeline.sensors.dominik_sensor_setup import (
    DominikSensorSetup,
    _matrix_to_transform,
)
from ultimate_pipeline.sensors.transform_conventions import (
    camera_attachment_pose_from_cTv,
    lidar_attachment_pose_from_vTl,
)

TOLERANCES = {
    "x": 1e-3,
    "y": 1e-3,
    "z": 1e-3,
    "roll": 1e-2,
    "pitch": 1e-2,
    "yaw": 1e-2,
}


def close(a: Any, b: Any, tol: float) -> bool:
    return abs(float(a) - float(b)) <= tol


def compare(name: str, expected: Dict[str, float], actual: Dict[str, float]) -> List[Tuple[str, Any, Any]]:
    errs: List[Tuple[str, Any, Any]] = []
    for key, tol in TOLERANCES.items():
        if not close(expected[key], actual[key], tol):
            errs.append((key, expected[key], actual[key]))
    return errs


def run(calib_path: Path) -> int:
    calib = json.loads(calib_path.read_text(encoding="utf-8"))
    setup = DominikSensorSetup(
        str(calib_path),
        flip_vehicle_y=True,
        opencv_camera_axes=True,
        lidar_axes_mode="auto",
    )

    failures = 0
    for cam_name, cam_data in calib.get("cameras", {}).items():
        expected = _matrix_to_transform(
            camera_attachment_pose_from_cTv(
                np.array(cam_data["cTv"], dtype=np.float64),
                flip_vehicle_y=True,
                opencv_camera_axes=True,
            )
        )
        actual = setup._parse_camera_transform(cam_data)
        errs = compare(f"camera {cam_name}", expected, actual)
        if errs:
            failures += 1
            print(f"FAIL camera {cam_name}: {errs}")
        else:
            print(f"OK   camera {cam_name}")

    for lid_name, lid_data in calib.get("lidars", {}).items():
        expected = _matrix_to_transform(
            lidar_attachment_pose_from_vTl(
                np.array(lid_data["vTl"], dtype=np.float64),
                flip_vehicle_y=True,
            )
        )
        actual = setup._parse_lidar_transform(lid_data)
        errs = compare(f"lidar {lid_name}", expected, actual)
        if errs:
            failures += 1
            print(f"FAIL lidar {lid_name}: {errs}")
        else:
            print(f"OK   lidar {lid_name}")

    return 2 if failures else 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("calib_json", type=Path, help="path to calibration JSON")
    args = parser.parse_args(argv)
    if not args.calib_json.is_file():
        parser.error(f"calibration file not found: {args.calib_json}")
    return run(args.calib_json)


if __name__ == "__main__":
    raise SystemExit(main())
