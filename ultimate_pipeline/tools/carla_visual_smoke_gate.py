#!/usr/bin/env python3
"""CARLA visual smoke gate for final OpenDRIVE maps.

This is a CARLA-dependent gate. It loads one XODR with
generate_opendrive_world(), captures three deterministic RGB views, and writes
a machine-readable readiness report. Perception evidence should only be treated
as validation when this report has ok=true.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ultimate_pipeline.utils.file_hashing import safe_sha256_file


REQUIRED_VIEWS: Tuple[str, ...] = ("top_down", "street", "junction")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in ("1", "true", "yes", "on", "y")


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True)
    path.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")


def _advance_world(world: Any, timeout_s: float) -> bool:
    try:
        world.tick()
        return True
    except Exception:
        try:
            world.wait_for_tick(float(timeout_s))
            return True
        except Exception:
            return False


def _spawn_points_and_waypoints(carla_map: Any) -> Tuple[List[Any], List[Any]]:
    spawn_points: List[Any] = []
    waypoints: List[Any] = []
    try:
        spawn_points = list(carla_map.get_spawn_points() or [])
    except Exception:
        spawn_points = []
    try:
        waypoints = list(carla_map.generate_waypoints(20.0) or [])
    except Exception:
        waypoints = []
    return spawn_points, waypoints


def _mean_xy(points: Iterable[Any]) -> Tuple[float, float, float]:
    xs: List[float] = []
    ys: List[float] = []
    for item in points:
        loc = getattr(item, "location", None)
        if loc is None and hasattr(item, "transform"):
            loc = getattr(item.transform, "location", None)
        if loc is None:
            continue
        xs.append(float(loc.x))
        ys.append(float(loc.y))
    if not xs:
        return 0.0, 0.0, 200.0
    extent = max(max(xs) - min(xs), max(ys) - min(ys), 200.0)
    return sum(xs) / len(xs), sum(ys) / len(ys), extent


def _camera_transforms(world: Any, carla: Any) -> Dict[str, Any]:
    carla_map = world.get_map()
    spawn_points, waypoints = _spawn_points_and_waypoints(carla_map)
    center_source = spawn_points if spawn_points else [wp.transform for wp in waypoints]
    center_x, center_y, extent = _mean_xy(center_source)
    altitude = max(120.0, min(700.0, extent * 0.85))

    top_down = carla.Transform(
        carla.Location(x=center_x, y=center_y, z=altitude),
        carla.Rotation(pitch=-90.0, yaw=0.0, roll=0.0),
    )

    if spawn_points:
        street_base = spawn_points[0]
        street_loc = carla.Location(
            x=float(street_base.location.x),
            y=float(street_base.location.y),
            z=float(street_base.location.z) + 2.2,
        )
        street_rot = carla.Rotation(
            pitch=-8.0,
            yaw=float(street_base.rotation.yaw),
            roll=0.0,
        )
    else:
        street_loc = carla.Location(x=center_x, y=center_y, z=2.2)
        street_rot = carla.Rotation(pitch=-8.0, yaw=0.0, roll=0.0)
    street = carla.Transform(street_loc, street_rot)

    junction_wp = None
    for wp in waypoints:
        if bool(getattr(wp, "is_junction", False)):
            junction_wp = wp
            break
    if junction_wp is not None:
        loc = junction_wp.transform.location
        rot = junction_wp.transform.rotation
        junction = carla.Transform(
            carla.Location(x=float(loc.x), y=float(loc.y), z=float(loc.z) + 35.0),
            carla.Rotation(pitch=-62.0, yaw=float(rot.yaw), roll=0.0),
        )
    else:
        junction = carla.Transform(
            carla.Location(x=center_x, y=center_y, z=35.0),
            carla.Rotation(pitch=-62.0, yaw=45.0, roll=0.0),
        )

    return {"top_down": top_down, "street": street, "junction": junction}


def _transform_payload(transform: Any) -> Dict[str, float]:
    loc = transform.location
    rot = transform.rotation
    return {
        "x": round(float(loc.x), 3),
        "y": round(float(loc.y), 3),
        "z": round(float(loc.z), 3),
        "pitch": round(float(rot.pitch), 3),
        "yaw": round(float(rot.yaw), 3),
        "roll": round(float(rot.roll), 3),
    }


def _capture_camera_view(
    *,
    world: Any,
    carla: Any,
    transform: Any,
    out_path: Path,
    timeout_s: float,
    warmup_ticks: int,
    width: int,
    height: int,
    fov: float,
) -> Dict[str, Any]:
    camera = None
    result: Dict[str, Any] = {
        "ok": False,
        "path": str(out_path),
        "error": "",
        "transform": _transform_payload(transform),
    }
    try:
        bp_lib = world.get_blueprint_library()
        cam_bp = bp_lib.find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", str(int(width)))
        cam_bp.set_attribute("image_size_y", str(int(height)))
        cam_bp.set_attribute("fov", str(float(fov)))
        camera = world.spawn_actor(cam_bp, transform)

        image_queue: "queue.Queue[Any]" = queue.Queue()
        camera.listen(lambda image: image_queue.put(image))

        for _ in range(max(0, int(warmup_ticks))):
            _advance_world(world, timeout_s)
            try:
                image_queue.get(timeout=0.2)
            except queue.Empty:
                pass

        deadline = time.time() + max(1.0, float(timeout_s))
        image = None
        while time.time() < deadline:
            _advance_world(world, timeout_s)
            try:
                image = image_queue.get(timeout=1.0)
                if image is not None:
                    break
            except queue.Empty:
                continue
        if image is None:
            raise RuntimeError("no_image_received")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save_to_disk(str(out_path))
        if not out_path.exists() or out_path.stat().st_size <= 0:
            raise RuntimeError("screenshot_not_written")
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        try:
            if camera is not None:
                camera.stop()
        except Exception:
            pass
        try:
            if camera is not None:
                camera.destroy()
        except Exception:
            pass
    return result


def evaluate_visual_smoke_report(
    report: Dict[str, Any],
    *,
    required_views: Tuple[str, ...] = REQUIRED_VIEWS,
    require_files: bool = False,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    screenshots = report.get("screenshots", {})
    if not isinstance(screenshots, dict):
        screenshots = {}

    missing_views: List[str] = []
    failed_views: List[str] = []
    missing_files: List[str] = []
    for view in required_views:
        item = screenshots.get(view)
        if not isinstance(item, dict):
            missing_views.append(view)
            continue
        if not bool(item.get("ok", False)):
            failed_views.append(view)
        path_text = str(item.get("path") or "").strip()
        if require_files:
            if not path_text:
                missing_files.append(view)
            else:
                p = Path(path_text)
                if not p.is_absolute() and base_dir is not None:
                    p = base_dir / p
                if not p.exists() or p.stat().st_size <= 0:
                    missing_files.append(view)

    ok = bool(report.get("ok", False)) and not missing_views and not failed_views and not missing_files
    reason_parts: List[str] = []
    if missing_views:
        reason_parts.append("missing_views:" + ",".join(missing_views))
    if failed_views:
        reason_parts.append("failed_views:" + ",".join(failed_views))
    if missing_files:
        reason_parts.append("missing_files:" + ",".join(missing_files))
    if not bool(report.get("load_ok", report.get("ok", False))):
        reason_parts.append("map_load_failed_or_missing")
    return {
        "ok": ok,
        "required_views": list(required_views),
        "missing_views": missing_views,
        "failed_views": failed_views,
        "missing_files": missing_files,
        "reason": ";".join(reason_parts),
    }


def run_visual_smoke_gate(
    *,
    xodr_path: Path,
    out_dir: Path,
    host: str = "127.0.0.1",
    port: int = 2000,
    timeout_s: float = 180.0,
    screenshot_timeout_s: float = 15.0,
    warmup_ticks: int = 8,
    width: int = 1280,
    height: int = 720,
    fov: float = 90.0,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "carla_visual_smoke_gate.json"
    timestamp = datetime.now(timezone.utc).isoformat()
    report: Dict[str, Any] = {
        "schema": "carla_visual_smoke_gate_v1",
        "checked_at_utc": timestamp,
        "xodr_path": str(xodr_path),
        "xodr_sha256": safe_sha256_file(xodr_path) if xodr_path.exists() else "",
        "host": str(host),
        "port": int(port),
        "load_ok": False,
        "ok": False,
        "CARLA_VISUAL_READY": "no",
        "PERCEPTION_EVIDENCE_ALLOWED": False,
        "perception_gate_reason": "visual_smoke_not_passed",
        "screenshots": {},
        "errors": [],
    }

    if not xodr_path.exists():
        report["errors"].append("xodr_missing")
        _write_json(report_path, report)
        return report
    if _env_bool("UP_DISABLE_CARLA", False):
        report["errors"].append("carla_disabled_by_env")
        report["CARLA_VISUAL_READY"] = "skipped"
        _write_json(report_path, report)
        return report

    try:
        from ultimate_pipeline.optional.carla_api import get_carla
        from ultimate_pipeline.core.carla_opendrive_loader import (
            load_opendrive_world_from_file,
        )

        carla = get_carla()
        client = carla.Client(str(host), int(port))
        client.set_timeout(float(timeout_s))
        world = load_opendrive_world_from_file(
            client,
            xodr_path,
            timeout_s=float(timeout_s),
            retries=1,
            do_reload=True,
        )
        report["load_ok"] = True
        carla_map = world.get_map()
        report["map_name"] = str(getattr(carla_map, "name", "") or "")

        transforms = _camera_transforms(world, carla)
        shots_dir = out_dir / "screenshots"
        for view_name in REQUIRED_VIEWS:
            view_result = _capture_camera_view(
                world=world,
                carla=carla,
                transform=transforms[view_name],
                out_path=shots_dir / f"{view_name}.png",
                timeout_s=float(screenshot_timeout_s),
                warmup_ticks=int(warmup_ticks),
                width=int(width),
                height=int(height),
                fov=float(fov),
            )
            report["screenshots"][view_name] = view_result
    except Exception as exc:
        report["errors"].append(str(exc))

    evaluation = evaluate_visual_smoke_report(report, require_files=True)
    report["visual_smoke_evaluation"] = evaluation
    report["ok"] = bool(evaluation["ok"])
    if report["ok"]:
        report["CARLA_VISUAL_READY"] = "yes"
        report["PERCEPTION_EVIDENCE_ALLOWED"] = True
        report["perception_gate_reason"] = ""
    _write_json(report_path, report)
    report["report_path"] = str(report_path)
    return report


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load a final XODR in CARLA and capture top-down/street/junction smoke screenshots."
    )
    parser.add_argument("--xodr", type=Path, required=True, help="Final XODR path")
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--screenshot-timeout", type=float, default=15.0)
    parser.add_argument("--warmup-ticks", type=int, default=8)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fov", type=float, default=90.0)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return nonzero unless CARLA visual readiness passes.",
    )
    return parser.parse_args(sys.argv[1:] if argv is None else argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    report = run_visual_smoke_gate(
        xodr_path=args.xodr,
        out_dir=args.out,
        host=args.host,
        port=args.port,
        timeout_s=args.timeout,
        screenshot_timeout_s=args.screenshot_timeout,
        warmup_ticks=args.warmup_ticks,
        width=args.width,
        height=args.height,
        fov=args.fov,
    )
    print(
        "[carla_visual_smoke_gate] "
        f"load_ok={report.get('load_ok')} "
        f"ok={report.get('ok')} "
        f"CARLA_VISUAL_READY={report.get('CARLA_VISUAL_READY')} "
        f"report={report.get('report_path', args.out / 'carla_visual_smoke_gate.json')}"
    )
    return 0 if bool(report.get("ok", False)) or not bool(args.strict) else 2


if __name__ == "__main__":
    raise SystemExit(main())
