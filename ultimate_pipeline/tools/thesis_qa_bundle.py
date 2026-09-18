# ultimate_pipeline/tools/thesis_qa_bundle.py
# -*- coding: utf-8 -*-

"""
Thesis QA bundle helper.

Loads an OpenDRIVE map into CARLA, spawns the thesis sensor rig, and captures
one frame per camera and one LiDAR snapshot (if configured).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from queue import Queue, Empty
from typing import Any, Dict, Optional

import carla

from ultimate_pipeline.carla_tools.thesis_sensor_rig import ThesisSensorRig
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _capture_sensor_once(sensor: carla.Sensor, out_path: Path, timeout_s: float = 5.0) -> bool:
    q: Queue = Queue(maxsize=1)

    def _cb(data):
        try:
            if q.full():
                return
            q.put(data)
        except Exception:
            pass

    sensor.listen(_cb)
    try:
        data = q.get(timeout=timeout_s)
        data.save_to_disk(str(out_path))
        return True
    except Empty:
        return False
    finally:
        try:
            sensor.stop()
        except Exception:
            pass


def _spawn_ego(world: carla.World) -> carla.Actor:
    bp_lib = world.get_blueprint_library()
    candidates = bp_lib.filter("vehicle.tesla.model3")
    if not candidates:
        candidates = bp_lib.filter("vehicle.*")
    if not candidates:
        raise RuntimeError("No vehicle blueprints available")
    bp = candidates[0]
    bp.set_attribute("role_name", "ego")
    spawns = world.get_map().get_spawn_points()
    if not spawns:
        raise RuntimeError("No spawn points found in map")
    ego = world.try_spawn_actor(bp, spawns[0])
    if ego is None:
        raise RuntimeError("Failed to spawn ego vehicle")
    return ego


def run_thesis_qa_bundle(
    xodr_path: str,
    calib_json: str,
    out_dir: str,
    *,
    host: str = "127.0.0.1",
    port: int = 2000,
) -> str:
    out_root = Path(out_dir)
    bundle_dir = out_root / "thesis_qa_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    xodr_file = Path(xodr_path).expanduser().resolve()
    if not xodr_file.is_file():
        raise FileNotFoundError(f"XODR not found: {xodr_file}")

    calib_file = Path(calib_json).expanduser().resolve()
    if not calib_file.is_file():
        raise FileNotFoundError(f"Calibration JSON not found: {calib_file}")

    client = carla.Client(host, int(port))
    client.set_timeout(120.0)

    xodr_text = xodr_file.read_text(encoding="utf-8", errors="replace")
    world = load_opendrive_world(client, xodr_text, timeout_s=180.0, retries=1, do_reload=True)

    original_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)
    for _ in range(5):
        world.tick()

    ego = _spawn_ego(world)
    rig = ThesisSensorRig(str(calib_file))
    sensors = rig.spawn_rig(world, ego)

    captures: Dict[str, Dict[str, str]] = {"cameras": {}, "lidars": {}}
    for name, spawned in sensors.items():
        sensor = spawned.actor
        s_type = spawned.report.get("type")
        if s_type == "camera":
            out_path = bundle_dir / f"{name}.png"
            if _capture_sensor_once(sensor, out_path):
                captures["cameras"][name] = str(out_path)
        elif s_type == "lidar":
            out_path = bundle_dir / f"{name}.ply"
            if _capture_sensor_once(sensor, out_path):
                captures["lidars"][name] = str(out_path)

    try:
        world.apply_settings(original_settings)
    except Exception:
        pass

    try:
        for spawned in sensors.values():
            spawned.actor.destroy()
    except Exception:
        pass
    try:
        ego.destroy()
    except Exception:
        pass

    manifest = {
        "xodr_path": str(xodr_file),
        "xodr_sha256": _sha256_file(xodr_file),
        "calib_json": str(calib_file),
        "captures": captures,
        "determinism_fingerprint": None,
        "pipeline_health_summary": None,
    }

    det_path = out_root / "determinism_fingerprint.json"
    if det_path.is_file():
        manifest["determinism_fingerprint"] = str(det_path)

    summary_path = out_root / "pipeline_health_summary.json"
    if summary_path.is_file():
        manifest["pipeline_health_summary"] = str(summary_path)

    manifest_path = bundle_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=True)
    return str(manifest_path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate thesis QA bundle in CARLA")
    ap.add_argument("--xodr", required=True, help="Path to OpenDRIVE (.xodr) file")
    ap.add_argument("--calib-json", required=True, help="Path to calibration JSON")
    ap.add_argument("--out-dir", required=True, help="Pipeline output directory")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    args = ap.parse_args()

    run_thesis_qa_bundle(
        args.xodr,
        args.calib_json,
        args.out_dir,
        host=args.host,
        port=int(args.port),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
