#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live-CARLA route-drive probe against the CURRENTLY LOADED OpenDRIVE world.

Phase 4 drivability evidence: connect to the running server, pick spawn
point(s), spawn ego, enable autopilot, tick N frames per spawn, and report
whether vehicles moved, stayed on a road, and the server stayed healthy (no
crash). Also reports coordinate magnitude (float32 precision evidence) and
waypoint coverage.

--spawns N drives from N spread spawn points and aggregates (stronger
evidence); --spawn-index selects one specific spawn point.

Usage:
    python scripts/drive_route_probe.py --out <dir> [--frames 300] [--spawns 5]
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _drive_one(sim_map, world, ego_bp, spawn_tf, frames: int, tm_port: int | None = None) -> Dict[str, Any]:
    ego = None
    try:
        ego = world.spawn_actor(ego_bp, spawn_tf)
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAIL", "failure_reason": f"spawn_failed: {exc}"}

    if tm_port is not None:
        ego.set_autopilot(True, tm_port)
    else:
        ego.set_autopilot(True)
    samples: List[Dict[str, Any]] = []
    start = time.time()
    try:
        for i in range(frames):
            world.wait_for_tick(10.0)
            loc = ego.get_location()
            vel = ego.get_velocity()
            speed = math.hypot(vel.x, vel.y)
            if i % 30 == 0 or i == frames - 1:
                wp = None
                try:
                    wp = sim_map.get_waypoint(loc)
                except Exception:  # noqa: BLE001
                    pass
                samples.append(
                    {
                        "frame": i,
                        "x": round(loc.x, 3),
                        "y": round(loc.y, 3),
                        "z": round(loc.z, 3),
                        "speed_m_s": round(speed, 3),
                        "on_road": wp is not None,
                        "lane_id": wp.lane_id if wp else None,
                        "road_id": wp.road_id if wp else None,
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAIL", "failure_reason": f"tick_failed: {exc}", "samples": samples}
    finally:
        try:
            ego.destroy()
        except Exception:  # noqa: BLE001
            pass

    elapsed = time.time() - start
    if not samples:
        return {"status": "FAIL", "failure_reason": "no_samples", "samples": []}

    last = samples[-1]
    first = samples[0]
    max_speed = max(s["speed_m_s"] for s in samples)
    moved = math.hypot(last["x"] - first["x"], last["y"] - first["y"])
    on_road_fraction = sum(1 for s in samples if s["on_road"]) / len(samples)
    return {
        "status": "PASS" if (moved > 5.0 and max_speed > 1.0 and on_road_fraction > 0.5) else "PARTIAL",
        "failure_reason": "" if moved > 5.0 and max_speed > 1.0 else "vehicle_did_not_drive_consistently",
        "distance_travelled_m": round(moved, 2),
        "max_speed_m_s": round(max_speed, 2),
        "on_road_fraction": round(on_road_fraction, 4),
        "elapsed_s": round(elapsed, 2),
        "frames_actual": frames,
        "samples": samples,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Drive-route probe on the currently loaded CARLA world.")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--frames", type=int, default=300)
    ap.add_argument("--spawns", type=int, default=1, help="Number of spread spawn points to drive from")
    ap.add_argument("--spawn-index", type=int, default=-1, help="-1 = nearest origin (or spread when --spawns > 1)")
    ap.add_argument("--no-traffic-manager", action="store_true", help="Use built-in autopilot instead of TrafficManager")
    args = ap.parse_args()

    import carla  # type: ignore

    client = carla.Client(args.host, args.port)
    client.set_timeout(60.0)
    world = client.get_world()
    sim_map = world.get_map()

    tm_port: int | None = None
    if not args.no_traffic_manager:
        try:
            tm = client.get_trafficmanager(args.port)
            tm.set_synchronous_mode(False)
            tm_port = args.port
        except Exception as exc:  # noqa: BLE001
            print(f"[drive] traffic manager unavailable: {exc}; falling back to built-in autopilot")

    payload: Dict[str, Any] = {
        "status": "FAIL",
        "world_map_name": sim_map.name,
        "frames_requested": args.frames,
        "traffic_manager": tm_port is not None,
    }

    spawn_points = sim_map.get_spawn_points()
    payload["spawn_point_count"] = len(spawn_points)
    if not spawn_points:
        payload["failure_reason"] = "no_spawn_points"
        _save_json(args.out / "drive_route_result.json", payload)
        print(json.dumps(payload, indent=2))
        return 1

    if args.spawns <= 1 and args.spawn_index >= 0 and args.spawn_index < len(spawn_points):
        spawn_tfs = [spawn_points[args.spawn_index]]
    elif args.spawns > 1:
        n = min(args.spawns, len(spawn_points))
        step = len(spawn_points) // n
        spawn_tfs = [spawn_points[i * step] for i in range(n)]
    else:
        spawn_tfs = [min(spawn_points, key=lambda tf: math.hypot(tf.location.x, tf.location.y))]

    bp_lib = world.get_blueprint_library()
    ego_bp = bp_lib.filter("vehicle.tesla.model3")[0]

    runs: List[Dict[str, Any]] = []
    for idx, tf in enumerate(spawn_tfs):
        print(f"[drive] spawn {idx + 1}/{len(spawn_tfs)} at ({tf.location.x:.1f}, {tf.location.y:.1f}, z={tf.location.z:.1f})")
        result = _drive_one(sim_map, world, ego_bp, tf, args.frames, tm_port=tm_port)
        result["spawn_index"] = idx
        result["spawn_transform"] = {
            "x": tf.location.x,
            "y": tf.location.y,
            "z": tf.location.z,
            "yaw": tf.rotation.yaw,
        }
        runs.append(result)
        print(f"        -> {result['status']} moved={result.get('distance_travelled_m')}m "
              f"max_speed={result.get('max_speed_m_s')}m/s on_road={result.get('on_road_fraction')}")

    passed = [r for r in runs if r["status"] == "PASS"]
    all_coords = [abs(s["x"]) for r in runs for s in r.get("samples", [])]
    all_coords += [abs(s["y"]) for r in runs for s in r.get("samples", [])]
    max_abs_coord = max(all_coords) if all_coords else 0.0

    aggregate = {
        "runs_attempted": len(runs),
        "runs_passed": len(passed),
        "run_fraction": round(len(passed) / len(runs), 4) if runs else 0.0,
        "total_distance_m": round(sum(r.get("distance_travelled_m", 0.0) for r in runs), 2),
        "max_speed_overall_m_s": round(max((r.get("max_speed_m_s", 0.0) for r in runs), default=0.0), 2),
        "mean_on_road_fraction": round(sum(r.get("on_road_fraction", 0.0) for r in runs) / len(runs), 4) if runs else 0.0,
        "float32_precision_note": (
            f"max |coordinate| = {max_abs_coord:.1f} m "
            f"({'OK (<50 km)' if max_abs_coord < 50_000 else 'GLOBAL-FRAME RISK (>50 km)'})"
        ),
    }
    payload.update(aggregate)
    payload["runs"] = runs

    ok = len(passed) == len(runs)
    payload["status"] = "PASS" if ok else "PARTIAL"
    if not ok:
        payload["failure_reason"] = f"{len(runs) - len(passed)}/{len(runs)} spawn runs did not drive"
    _save_json(args.out / "drive_route_result.json", payload)
    print(json.dumps(payload, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())