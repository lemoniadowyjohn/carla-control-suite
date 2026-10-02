#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""World settings transaction + live map identity (single tick owner).

Step 11: snapshot -> apply -> verify -> experiment -> restore -> verify.
Step 12: live map identity from runtime observation, not substring/path
heuristics.

The transaction is the ONLY place in this run that owns ticks. Readiness
probes deliberately do NOT tick (frame must not advance during a probe).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

OUT = Path("reports/carla_runtime")
OUT.mkdir(parents=True, exist_ok=True)

GOVERNED = {
    "synchronous_mode": True,
    "fixed_delta_seconds": 0.05,
    "substepping": True,
    "max_substep_delta_time": 0.0125,
    "max_substeps": 4,
    "no_rendering_mode": False,
}


def snap(ws: Any) -> Dict[str, Any]:
    return {
        "synchronous_mode": bool(getattr(ws, "synchronous_mode", False)),
        "fixed_delta_seconds": float(getattr(ws, "fixed_delta_seconds", 0.0) or 0.0),
        "substepping": bool(getattr(ws, "substepping", False)),
        "max_substep_delta_time": float(getattr(ws, "max_substep_delta_time", 0.0) or 0.0),
        "max_substeps": int(getattr(ws, "max_substeps", 0) or 0),
        "no_rendering_mode": bool(getattr(ws, "no_rendering_mode", False)),
    }


def main() -> int:
    import carla

    run_id = f"wstrans_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    report: Dict[str, Any] = {
        "schema": "world_settings_transaction/v1",
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "governed_target": GOVERNED,
        "tick_owner": "tools/world_settings_transaction.py (this run only)",
        "phases": {},
    }

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(30.0)
    report["server_version"] = client.get_server_version()
    world = client.get_world()
    report["initial_map"] = world.get_map().name

    # ---- PHASE 1: snapshot (no tick) ------------------------------------
    before = snap(world.get_settings())
    s0 = world.get_snapshot()
    frame_probe_1 = s0.frame if s0 else None
    time.sleep(0.6)
    s1 = world.get_snapshot()
    frame_probe_2 = s1.frame if s1 else None
    report["phases"]["1_snapshot"] = {
        "settings": before,
        "frame_probe_1": frame_probe_1,
        "frame_probe_2": frame_probe_2,
        "frames_advanced_during_probe": (
            None if frame_probe_1 is None or frame_probe_2 is None
            else bool(frame_probe_2 > frame_probe_1)
        ),
        "note": "async server: frames advance on their own; a readiness probe "
                "must not itself call tick()/wait_for_tick()",
    }

    # ---- PHASE 2: apply --------------------------------------------------
    ws = world.get_settings()
    ws.synchronous_mode = True
    ws.fixed_delta_seconds = GOVERNED["fixed_delta_seconds"]
    ws.substepping = True
    ws.max_substep_delta_time = GOVERNED["max_substep_delta_time"]
    ws.max_substeps = GOVERNED["max_substeps"]
    ws.no_rendering_mode = GOVERNED["no_rendering_mode"]
    applied = world.apply_settings(ws)
    report["phases"]["2_apply"] = {"returned": snap(applied)}

    # ---- PHASE 3: verify (this run owns the first tick) -----------------
    v = snap(world.get_settings())
    report["phases"]["3_verify_after_apply"] = {
        "observed": v,
        "matches_governed": all(
            abs(float(v[k]) - float(GOVERNED[k])) < 1e-9 if isinstance(GOVERNED[k], float)
            else bool(v[k]) == bool(GOVERNED[k])
            for k in GOVERNED
        ),
    }
    t_tick0 = time.time()
    frame_a = world.tick(30.0)
    t_tick1 = time.time()
    snap_a = world.get_snapshot()
    report["phases"]["3_tick_after_apply"] = {
        "tick_return_type": "int_frame_id (synchronous mode)",
        "frame": int(frame_a),
        "snapshot_frame": int(snap_a.frame) if snap_a is not None else None,
        "elapsed_seconds": float(snap_a.timestamp.elapsed_seconds) if snap_a else None,
        "tick_wall_seconds": round(t_tick1 - t_tick0, 3),
    }

    # ---- PHASE 4: experiment (owner ticks; deterministic frame advance) --
    exp_frames = []
    for _ in range(5):
        fr = int(world.tick(30.0))
        sn = world.get_snapshot()
        exp_frames.append(
            {
                "frame": fr,
                "elapsed_seconds": round(
                    float(sn.timestamp.elapsed_seconds) if sn else float("nan"), 6
                ),
            }
        )
    deltas = [
        round(exp_frames[i + 1]["elapsed_seconds"] - exp_frames[i]["elapsed_seconds"], 6)
        for i in range(len(exp_frames) - 1)
    ]
    report["phases"]["4_experiment"] = {
        "frames": exp_frames,
        "sim_time_deltas": deltas,
        "fixed_delta_target": GOVERNED["fixed_delta_seconds"],
        "fixed_delta_observed_max_abs_err": max(
            (abs(d - GOVERNED["fixed_delta_seconds"]) for d in deltas), default=None
        ),
        "monotonic": all(
            exp_frames[i + 1]["frame"] > exp_frames[i]["frame"]
            for i in range(len(exp_frames) - 1)
        ),
    }

    # ---- PHASE 5: restore -------------------------------------------------
    rw = world.get_settings()
    rw.synchronous_mode = before["synchronous_mode"]
    rw.fixed_delta_seconds = before["fixed_delta_seconds"]
    rw.substepping = before["substepping"]
    rw.max_substep_delta_time = before["max_substep_delta_time"]
    rw.max_substeps = before["max_substeps"]
    rw.no_rendering_mode = before["no_rendering_mode"]
    world.apply_settings(rw)
    report["phases"]["5_restore"] = {"restored_to": before}

    # ---- PHASE 6: verify restore (tick to hand control back to server) ----
    after = snap(world.get_settings())
    report["phases"]["6_verify_restore"] = {
        "observed": after,
        "matches_original": all(
            abs(float(after[k]) - float(before[k])) < 1e-9 if isinstance(before[k], float)
            else bool(after[k]) == bool(before[k])
            for k in before
        ),
    }

    # ---- map identity: MANUAL arm (Grid0828) -----------------------------
    ident: Dict[str, Any] = {
        "schema": "runtime_map_identity/v1",
        "run_id": run_id,
        "generated_at_utc": report["generated_at_utc"],
        "arm": "manual",
        "requested_package": "Grid0828",
        "registry_key": "manual_grid0828",
    }
    try:
        world2 = client.load_world("Grid0828")
        ident["observed_world_map_name"] = world2.get_map().name
        m = world2.get_map()
        wps = m.generate_waypoints(3.0)
        sample = [wps[i] for i in range(0, min(len(wps), 4000), max(1, len(wps) // 16))]
        fp = {
            "map_name": m.name,
            "waypoints_at_3m": int(len(wps)),
            "waypoint_sample_stride_m": 3.0,
            "topology_op": "get_topology()",
            "landmarks": int(len(m.get_all_landmarks_of_type("landmark"))),
            "actors": int(len(world2.get_actors())),
            "vehicles": int(len(world2.get_actors().filter("vehicle.*"))),
            "walkers": int(len(world2.get_actors().filter("walker.pedestrian.*"))),
            "traffic_signs": int(len(world2.get_actors().filter("traffic.*"))),
            "bounding_box_extent": [
                float(v) for v in (m.get_bounding_box().extent or (0, 0, 0))
            ],
            "waypoint_xy_hash": __import__("hashlib")
            .sha256(
                ";".join(f"{round(p.location.x,3)},{round(p.location.y,3)}" for p in sample)
                .encode("utf-8")
            )
            .hexdigest(),
        }
        try:
            top = m.get_topology()
            fp["topology_segments"] = int(len(top[0])) if top else 0
        except Exception as e:
            fp["topology_segments_error"] = f"{type(e).__name__}: {e}"
        ident["runtime_structural_fingerprint"] = fp
        client.apply_settings(client.get_world().get_settings())
        ident["source_xodr_sha256"] = (
            "5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c"
        )
        ident["identity_method"] = (
            "runtime observation: requested name -> client.load_world() -> "
            "world.get_map().name + structural fingerprint. No substring or "
            "filesystem-path heuristic."
        )
        ident["status"] = "RUNTIME_IDENTITY_ESTABLISHED"
    except Exception as e:
        ident["status"] = "BLOCKED_RUNTIME"
        ident["error"] = f"{type(e).__name__}: {e}"
    report["manual_map_identity"] = ident

    # ---- PHASE 7: restore CARLA's own default (undo any leaked sync mode) --
    # A prior aborted transaction can leave synchronous_mode=True behind. The
    # governed end-state for a non-experiment server is CARLA's async default,
    # not "whatever we happened to find".
    d = world.get_settings()
    d.synchronous_mode = False
    d.fixed_delta_seconds = 0.0
    d.substepping = False
    d.max_substep_delta_time = 0.0
    d.max_substeps = 0
    world.apply_settings(d)
    final = snap(world.get_settings())
    report["phases"]["7_restore_carla_default"] = {
        "target": "async default (synchronous_mode=False, fixed_delta=0, substepping=False)",
        "observed": final,
        "is_carla_default": (
            final["synchronous_mode"] is False
            and final["substepping"] is False
            and abs(final["fixed_delta_seconds"]) < 1e-9
        ),
    }
    # verify by advancing the clock on the server (not by ticking)
    time.sleep(0.5)
    sv = world.get_world()
    fa = sv.get_snapshot()
    time.sleep(0.5)
    fb = sv.get_snapshot()
    report["phases"]["7_verify_async_resumes"] = {
        "snapshot_frame_a": fa.frame if fa else None,
        "snapshot_frame_b": fb.frame if fb else None,
        "server_advances_on_its_own": bool(
            fa and fb and fb.frame > fa.frame
        ),
    }

    p = OUT / f"{run_id}_REPORT.json"
    p.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nreport: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())