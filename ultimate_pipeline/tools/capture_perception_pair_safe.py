#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Safe paired perception capture using robust spawn and sensor attach.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ultimate_pipeline.carla_tools.safe_spawn_ego import safe_spawn_ego
from ultimate_pipeline.sensors.attach_sensors_safe import attach_sensors_safe
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world_from_file


from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _capture_arm(
    *,
    arm_name: str,
    world,
    calib_path: str,
    out_dir: Path,
    frames: int,
    spawn_index: int,
    z_offset: float,
    camera_optical_frame: bool,
    sync: bool,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "arm": arm_name,
        "ok": False,
        "frames": frames,
        "errors": [],
        "captures": {"camera_frames": {}, "lidar_frames": {}},
    }
    out_dir.mkdir(parents=True, exist_ok=True)

    old_settings = None
    if sync:
        try:
            old_settings = world.get_settings()
            if not old_settings.synchronous_mode:
                import carla  # type: ignore

                new_settings = carla.WorldSettings(
                    no_rendering_mode=old_settings.no_rendering_mode,
                    synchronous_mode=True,
                    fixed_delta_seconds=old_settings.fixed_delta_seconds or 0.05,
                    max_substep_delta_time=old_settings.max_substep_delta_time,
                    max_substeps=old_settings.max_substeps,
                )
                world.apply_settings(new_settings)
        except Exception as exc:
            report["errors"].append(f"sync mode enable failed: {exc}")

    ego, _ = safe_spawn_ego(
        world,
        spawn_index=spawn_index,
        z_offset=z_offset,
        report_path=str(out_dir / "ego_spawn_report.json"),
    )
    if ego is None:
        report["errors"].append("ego spawn failed")
        _write_json(out_dir / "arm_report.json", report)
        return report

    sensors, attach_report = attach_sensors_safe(
        world,
        ego,
        calib_path,
        out_dir=str(out_dir),
        camera_optical_frame=camera_optical_frame,
    )
    if not sensors:
        report["errors"].append("sensor attach failed")
        _write_json(out_dir / "arm_report.json", report)
        return report

    cam_dir = out_dir / "cameras"
    lidar_dir = out_dir / "lidars"
    cam_dir.mkdir(exist_ok=True)
    lidar_dir.mkdir(exist_ok=True)

    cam_counts: Dict[str, int] = {}
    lidar_counts: Dict[str, int] = {}
    listeners = []

    def make_cam_cb(name: str):
        def _cb(image):
            count = cam_counts.get(name, 0)
            if count >= frames:
                return
            out_path = cam_dir / name
            out_path.mkdir(parents=True, exist_ok=True)
            image.save_to_disk(str(out_path / f"{count:06d}.png"))
            cam_counts[name] = count + 1
        return _cb

    def make_lidar_cb(name: str):
        def _cb(points):
            count = lidar_counts.get(name, 0)
            if count >= frames:
                return
            out_path = lidar_dir / name
            out_path.mkdir(parents=True, exist_ok=True)
            points.save_to_disk(str(out_path / f"{count:06d}.ply"))
            lidar_counts[name] = count + 1
        return _cb

    for name, actor in sensors.items():
        try:
            if actor.type_id.startswith("sensor.camera"):
                actor.listen(make_cam_cb(name))
                listeners.append(actor)
            elif actor.type_id.startswith("sensor.lidar"):
                actor.listen(make_lidar_cb(name))
                listeners.append(actor)
        except Exception as exc:
            report["errors"].append(f"sensor listen failed: {name}: {exc}")

    try:
        start = time.time()
        while True:
            try:
                world.tick()
            except Exception:
                try:
                    world.wait_for_tick(2.0)
                except Exception:
                    break
            if all(v >= frames for v in cam_counts.values() or [frames]) and all(
                v >= frames for v in lidar_counts.values() or [frames]
            ):
                break
            if time.time() - start > max(10.0, frames * 2.0):
                break
    finally:
        for s in listeners:
            try:
                s.stop()
            except Exception:
                pass
        for actor in list(sensors.values()) + [ego]:
            try:
                actor.destroy()
            except Exception:
                pass
        if sync and old_settings is not None:
            try:
                world.apply_settings(old_settings)
            except Exception:
                pass

    report["captures"]["camera_frames"] = cam_counts
    report["captures"]["lidar_frames"] = lidar_counts
    report["ok"] = True
    _write_json(out_dir / "arm_report.json", report)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual-town", help="CARLA town name (e.g., Grid0821)")
    ap.add_argument("--auto-xodr", help="Path to auto-generated XODR")
    ap.add_argument("--calib", required=True, help="Path to calib_data.json")
    ap.add_argument("--out", required=True, help="Output directory for paired capture")
    ap.add_argument("--frames", type=int, default=10)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--spawn-index", type=int, default=0)
    ap.add_argument("--z-offset", type=float, default=0.5)
    ap.add_argument("--camera-optical", action="store_true")
    ap.add_argument("--sync", action="store_true")
    args = ap.parse_args()

    if not args.manual_town and not args.auto_xodr:
        raise SystemExit("Provide --manual-town and/or --auto-xodr")

    try:
        import carla  # type: ignore
    except Exception as exc:
        raise SystemExit(f"carla not available: {exc}") from exc

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)

    pair_report: Dict[str, Any] = {"manual": None, "auto": None, "errors": []}

    if args.manual_town:
        try:
            world = _reload_ready_for_sensors(client, map_name=args.manual_town, tm_port=8000)
            pair_report["manual"] = _capture_arm(
                arm_name="manual",
                world=world,
                calib_path=args.calib,
                out_dir=out_dir / "manual",
                frames=args.frames,
                spawn_index=args.spawn_index,
                z_offset=args.z_offset,
                camera_optical_frame=args.camera_optical,
                sync=args.sync,
            )
        except Exception as exc:
            pair_report["errors"].append(f"manual capture failed: {exc}")

    if args.auto_xodr:
        try:
            world = load_opendrive_world_from_file(client, args.auto_xodr, timeout_s=180.0, retries=1, do_reload=True)
            pair_report["auto"] = _capture_arm(
                arm_name="auto",
                world=world,
                calib_path=args.calib,
                out_dir=out_dir / "auto",
                frames=args.frames,
                spawn_index=args.spawn_index,
                z_offset=args.z_offset,
                camera_optical_frame=args.camera_optical,
                sync=args.sync,
            )
        except Exception as exc:
            pair_report["errors"].append(f"auto capture failed: {exc}")

    _write_json(out_dir / "pair_report.json", pair_report)
    if pair_report["errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
