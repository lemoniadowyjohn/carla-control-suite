#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import argparse, json, time
from pathlib import Path
from typing import Any, Dict

from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
def _atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    tmp.replace(path)

def _truthy(x: str) -> bool:
    return str(x).strip().lower() in ("1", "true", "yes", "y", "on")

def _readiness(client, timeout_s: float) -> tuple[bool, str]:
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout_s:
        try:
            w = client.get_world()
            m = w.get_map()
            _ = m.name
            try:
                w.wait_for_tick(0.5)
            except Exception:
                pass
            return True, "ok"
        except Exception as e:
            last = e
            time.sleep(0.5)
    return False, f"not_ready: {last}"

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout-s", type=float, default=240.0)
    ap.add_argument("--check-spawn", type=int, default=0)
    ap.add_argument("--stage-name", default="carla_load_check")
    args = ap.parse_args()

    out = Path(args.out_json)
    payload: Dict[str, Any] = {
        "stage": args.stage_name,
        "xodr": args.xodr,
        "ok": False,
        "reason": None,
        "timing_s": None,
    }

    t0 = time.time()
    try:
        import carla  # native

        client = carla.Client(args.host, args.port)
        client.set_timeout(min(float(args.timeout_s), 30.0))

        ok, why = _readiness(client, timeout_s=15.0)
        if not ok:
            payload["ok"] = False
            payload["reason"] = why
            _atomic_write_json(out, payload)
            return 0

        xodr_text = Path(args.xodr).read_text(encoding="utf-8")

        params = carla.OpendriveGenerationParameters(
            vertex_distance=2.0,
            max_road_length=500.0,
            wall_height=1.0,
            additional_width=0.6,
            smooth_junctions=True,
            enable_mesh_visibility=True,
        )

        world = _reload_ready_for_sensors(client, xodr_string=xodr_text, tm_port=8000, xodr_generation_params=params)
        try:
            world.wait_for_tick(1.0)
        except Exception:
            pass

        if _truthy(args.check_spawn):
            sp = []
            try:
                sp = world.get_map().get_spawn_points()
            except Exception:
                sp = []
            if not sp:
                payload["ok"] = False
                payload["reason"] = "no_spawn_points"
            else:
                payload["ok"] = True
                payload["reason"] = f"ok_spawn_points={len(sp)}"
        else:
            payload["ok"] = True
            payload["reason"] = "ok"

        _atomic_write_json(out, payload)
        return 0

    except Exception as e:
        payload["ok"] = False
        payload["reason"] = f"python_exception: {type(e).__name__}: {e}"
        _atomic_write_json(out, payload)
        return 0
    finally:
        payload["timing_s"] = round(time.time() - t0, 3)
        try:
            _atomic_write_json(out, payload)
        except Exception:
            pass

if __name__ == "__main__":
    raise SystemExit(main())
