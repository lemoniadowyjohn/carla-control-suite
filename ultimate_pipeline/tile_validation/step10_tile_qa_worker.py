#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""STEP 10 Tile QA Worker (CHILD)

Imports `carla`. Expected to be disposable. Writes JSON output and exits 0 even on QA failure.
Native crashes will terminate the process; supervisor contains them.

Default validity:
- readiness (world+map+tick)
- generate_opendrive_world
- post-load readiness
- generate_waypoints() > 0
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
def _atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    tmp.replace(path)

def _carla_readiness_check(client, timeout_s: float = 30.0, tick_timeout_s: float = 5.0) -> Tuple[bool, str, Dict[str, Any]]:
    t0 = time.time()
    attempts = 0
    last_error: Optional[str] = None
    last_map: Optional[str] = None
    last_sync: Optional[bool] = None
    last_fixed_dt: Optional[float] = None
    while time.time() - t0 < timeout_s:
        try:
            world = client.get_world()
            m = world.get_map()
            if m is None:
                last_map = None
                time.sleep(0.2)
                continue
            last_map = getattr(m, "name", None)
            settings = world.get_settings()
            last_sync = bool(getattr(settings, "synchronous_mode", False))
            last_fixed_dt = getattr(settings, "fixed_delta_seconds", None)
            attempts += 1
            if last_sync:
                world.tick()
            else:
                world.wait_for_tick(float(tick_timeout_s))
            return True, "ready", {
                "attempts": attempts,
                "map_name": last_map,
                "sync": last_sync,
                "fixed_delta_seconds": last_fixed_dt,
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.2)
    return False, "not_ready_world_map_tick", {
        "attempts": attempts,
        "map_name": last_map,
        "sync": last_sync,
        "fixed_delta_seconds": last_fixed_dt,
        "last_error": last_error,
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tile-id", required=True)
    ap.add_argument("--xodr", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout-s", type=float, default=180.0)
    ap.add_argument("--no-spawn", type=int, default=1)
    ap.add_argument("--strict", type=int, default=0)
    args = ap.parse_args()

    out_path = Path(args.out_json)
    xodr_path = Path(args.xodr)

    payload: Dict[str, Any] = {
        "tile_id": args.tile_id,
        "ok": False,
        "reason": "init",
        "timing_s": None,
        "stats": {},
        "carla": {},
        "worker": {"host": args.host, "port": args.port, "no_spawn": bool(args.no_spawn), "strict": bool(args.strict)},
    }

    t0 = time.time()
    try:
        import carla  # type: ignore

        client = carla.Client(args.host, args.port)
        client.set_timeout(min(float(args.timeout_s), 60.0))
        try:
            payload["carla"]["server_version"] = client.get_server_version()
        except Exception:
            payload["carla"]["server_version"] = None
        try:
            payload["carla"]["client_version"] = client.get_client_version()
        except Exception:
            payload["carla"]["client_version"] = None

        readiness_timeout = min(float(args.timeout_s), 60.0)
        ok, why, readiness = _carla_readiness_check(client, timeout_s=readiness_timeout, tick_timeout_s=5.0)
        payload["carla"]["readiness"] = readiness
        print(f"[STEP10_WORKER] readiness ok={ok} reason={why} map={readiness.get('map_name')} sync={readiness.get('sync')} fixed_dt={readiness.get('fixed_delta_seconds')}")
        if not ok:
            payload["reason"] = why
            _atomic_write_json(out_path, payload)
            return 0

        xodr_text = xodr_path.read_text(encoding="utf-8")
        params = carla.OpendriveGenerationParameters(
            vertex_distance=2.0,
            max_road_length=500.0,
            wall_height=0.0,
            additional_width=0.0,
            smooth_junctions=True,
            enable_mesh_visibility=True,
        )
        world = _reload_ready_for_sensors(client, xodr_string=xodr_text, tm_port=8000, xodr_generation_params=params)

        ok, why, readiness = _carla_readiness_check(client, timeout_s=min(float(args.timeout_s), 60.0), tick_timeout_s=5.0)
        payload["carla"]["post_load_readiness"] = readiness
        print(f"[STEP10_WORKER] post_load ok={ok} reason={why} map={readiness.get('map_name')} sync={readiness.get('sync')} fixed_dt={readiness.get('fixed_delta_seconds')}")
        if not ok:
            payload["reason"] = f"post_load_{why}"
            _atomic_write_json(out_path, payload)
            return 0

        m = world.get_map()
        wps = m.generate_waypoints(2.0)
        spawns = m.get_spawn_points()

        payload["stats"] = {"waypoints": len(wps), "spawn_points": len(spawns), "map_name": getattr(m, "name", None)}
        if len(wps) == 0:
            payload["ok"] = False
            payload["reason"] = "no_waypoints"
        else:
            payload["ok"] = True
            payload["reason"] = "ok"

        _atomic_write_json(out_path, payload)
        return 0

    except Exception as e:
        payload["ok"] = False
        payload["reason"] = f"python_exception: {type(e).__name__}: {e}"
        _atomic_write_json(out_path, payload)
        return 0
    finally:
        payload["timing_s"] = round(time.time() - t0, 3)
        try:
            _atomic_write_json(out_path, payload)
        except Exception:
            pass

if __name__ == "__main__":
    raise SystemExit(main())
