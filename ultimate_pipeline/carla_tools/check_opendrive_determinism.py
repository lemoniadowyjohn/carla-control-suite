#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
carla_tools/check_opendrive_determinism.py

Thesis helper:
- Load the SAME .xodr into CARLA multiple times
- Compute a lightweight structural signature of the resulting CARLA map
- Report whether signatures differ across loads

This targets the requirement:
  "When converting OSM to CARLA, evaluate the map and check if the created map changes
   when converting the same OSM map into a CARLA map."
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Dict, Tuple

import carla

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world_from_file


def map_signature(world: carla.World) -> Dict[str, object]:
    m = world.get_map()
    topo = m.get_topology()  # list[(Waypoint, Waypoint)]

    # Signature from topology endpoints + lane metadata (order-independent)
    rows = []
    for a, b in topo:
        rows.append((
            int(a.road_id), int(a.section_id), int(a.lane_id),
            round(float(a.s), 3),
            round(float(a.transform.location.x), 2),
            round(float(a.transform.location.y), 2),
            round(float(a.transform.location.z), 2),
            int(b.road_id), int(b.section_id), int(b.lane_id),
            round(float(b.s), 3),
            round(float(b.transform.location.x), 2),
            round(float(b.transform.location.y), 2),
            round(float(b.transform.location.z), 2),
        ))
    rows.sort()

    sp = world.get_map().get_spawn_points()
    sig_obj = {
        "topology_edges": len(rows),
        "spawn_points": len(sp),
        "topology_rows": rows[:50],  # keep small sample for debugging
    }
    blob = json.dumps(sig_obj, sort_keys=True).encode("utf-8")
    sig_obj["md5"] = hashlib.md5(blob).hexdigest()
    return sig_obj


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("xodr", type=str, help="Path to .xodr file")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--host", type=str, default=SETTINGS.CARLA_HOST)
    ap.add_argument("--port", type=int, default=SETTINGS.CARLA_PORT)
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    client = carla.Client(args.host, int(args.port))
    client.set_timeout(60.0)

    sigs = []
    for i in range(int(args.reps)):
        print(f"\n=== Load {i+1}/{args.reps} ===")
        world = load_opendrive_world_from_file(
            client,
            args.xodr,
            timeout_s=180.0,
            retries=2,
            do_reload=True,
            # use settings fallback behavior (mainly to keep the script alive if CARLA refuses the xodr)
            fallback_enabled=getattr(SETTINGS, "CARLA_ENABLE_MAP_FALLBACK", False),
            fallback_maps=getattr(SETTINGS, "CARLA_FALLBACK_MAPS", None),
        )
        time.sleep(max(0.0, float(args.sleep)))
        s = map_signature(world)
        sigs.append(s)
        print(f"signature md5={s['md5']}  topology_edges={s['topology_edges']}  spawn_points={s['spawn_points']}")

    md5s = [s["md5"] for s in sigs]
    unique = sorted(set(md5s))
    if len(unique) == 1:
        print("\n✅ Deterministic (for this signature): all loads match.")
    else:
        print("\n⚠ Non-deterministic (for this signature): loads differ!")
        for i, m in enumerate(md5s):
            print(f"  load{i+1}: {m}")
        print("Tip: dump more of the topology or sample waypoints more densely if you need stronger guarantees.")


if __name__ == "__main__":
    main()
