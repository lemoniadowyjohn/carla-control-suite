#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CARLA-only spawn + teardown smoke check.

Loads a town, selects a spawn, spawns a vehicle, ticks N frames, then performs
record_route-style soft teardown. Writes spawn_check.json under --out.
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional


from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--town", choices=["Grid0821", "Grid0828"], default="Grid0828", help="Manual CARLA town")
    ap.add_argument("--out", required=True, help="Output directory for artifacts")
    ap.add_argument("--host", default="127.0.0.1", help="CARLA host")
    ap.add_argument("--port", type=int, default=2000, help="CARLA RPC port")
    ap.add_argument("--spawn-index", type=int, default=0, help="Requested spawn index (default: 0)")
    ap.add_argument("--vehicle", default="vehicle.audi.a2", help="Vehicle blueprint id")
    ap.add_argument("--ticks", type=int, default=30, help="Ticks to run after spawn (default: 30)")
    ap.add_argument("--seed", type=int, default=0, help="Deterministic seed for spawn candidate ordering")
    return ap.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "spawn_check.json"

    t0 = time.time()
    report: Dict[str, Any] = {
        "success": False,
        "town": str(args.town),
        "host": str(args.host),
        "port": int(args.port),
        "ticks": int(args.ticks),
        "elapsed_s": None,
        "error": None,
    }

    try:
        import carla  # type: ignore

        from ultimate_pipeline.perception.record_route import (
            _safe_tick,
            _soft_teardown,
            build_spawn_candidate_indices,
            _write_run_status,
            _transform_to_dict,
        )

        client = carla.Client(str(args.host), int(args.port))
        client.set_timeout(10.0)
        report["server_version"] = client.get_server_version()

        world = _reload_ready_for_sensors(client, map_name=str(args.town), tm_port=8000)
        original_settings = world.get_settings()

        # Ensure ticking works
        tick_res = _safe_tick(world, n=2, timeout_s=2.0)
        report["tick_ok"] = bool(tick_res.get("ok", False))
        if not report["tick_ok"]:
            raise RuntimeError(f"tick_failed: {tick_res.get('error')}")

        bp_lib = world.get_blueprint_library()
        vehicle_candidates = bp_lib.filter(str(args.vehicle))
        if not vehicle_candidates:
            raise RuntimeError(f"vehicle_blueprint_missing: {args.vehicle}")
        vehicle_bp = vehicle_candidates[0]

        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            raise RuntimeError("no_spawn_points")

        candidates = build_spawn_candidate_indices(int(args.spawn_index), len(spawn_points), seed=int(args.seed))
        report["spawn_candidates"] = list(candidates)

        ego = None
        spawn_tf = None
        chosen_idx = None
        attempts = []
        for idx in candidates:
            tf = spawn_points[int(idx)]
            try:
                actor = world.try_spawn_actor(vehicle_bp, tf)
            except Exception as exc:
                attempts.append({"index": int(idx), "ok": False, "error": str(exc)})
                continue
            if actor is None:
                attempts.append({"index": int(idx), "ok": False, "error": "try_spawn_actor_returned_none"})
                continue
            ego = actor
            spawn_tf = tf
            chosen_idx = int(idx)
            attempts.append({"index": int(idx), "ok": True, "error": None})
            break
        report["spawn_attempts"] = attempts
        if ego is None or spawn_tf is None or chosen_idx is None:
            raise RuntimeError("vehicle_spawn_failed_all_candidates")

        report["spawn_index_selected"] = int(chosen_idx)
        report["spawn_transform"] = _transform_to_dict(spawn_tf)

        _write_run_status(
            out_dir,
            {
                "stage": "spawn_check_running",
                "success": False,
                "error": None,
                "exit_code": None,
                "spawn_index_selected": int(chosen_idx),
                "spawn_transform": _transform_to_dict(spawn_tf),
            },
        )

        # Run a short tick loop
        for _ in range(int(args.ticks)):
            _safe_tick(world, n=1, timeout_s=2.0)

        # Soft teardown
        teardown = _soft_teardown(
            world=world,
            ego=ego,
            sensors={},
            recorder=None,
            out_dir=out_dir,
            original_settings=original_settings,
        )
        report["teardown"] = teardown

        report["success"] = True
        report["elapsed_s"] = round(time.time() - t0, 3)
        _write_json(report_path, report)
        return 0

    except Exception as exc:
        report["success"] = False
        report["error"] = str(exc)
        report["elapsed_s"] = round(time.time() - t0, 3)
        report["traceback"] = traceback.format_exc()
        _write_json(report_path, report)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

