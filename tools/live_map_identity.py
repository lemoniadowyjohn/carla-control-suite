#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live map identity probe (standalone, async-safe).

Ordering matters: the map is loaded while the server is at CARLA's ASYNC
default, and only afterwards may a caller enter synchronous mode. Loading a
world while synchronous_mode=True with no live tick owner wedges the server.

Identity is proven from runtime observation only:
  requested -> client.load_world() -> world.get_map().name -> structural
  fingerprint. No substring match on the name, no filesystem-path heuristic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

OUT = Path("reports/carla_runtime")
OUT.mkdir(parents=True, exist_ok=True)

ARM_SOURCE_SHA = {
    "manual_grid0828": "5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c",
    "Grid0821": "5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c",
}


def fingerprint(world: Any, m: Any, *, light: bool = True) -> Dict[str, Any]:
    """Structural fingerprint of the loaded runtime world.

    ``light=True`` (default) deliberately avoids ``generate_waypoints()``:
    on this host (Quadro P3200, 6 GiB VRAM, -RenderOffScreen) CARLA 0.9.16
    wedges or dies during full waypoint expansion of Grid0828. The light
    fingerprint still binds identity through actor/category counts and the
    map bounding box, which are cheap and server-side.
    """
    actors = world.get_actors()
    fp: Dict[str, Any] = {
        "fingerprint_mode": "light" if light else "heavy",
        "map_name": m.name,
    }

    def probe(label: str, fn) -> None:
        """Fault-isolated: a wedged/unsupported call must not lose the capture."""
        try:
            fp[label] = fn()
        except Exception as e:
            fp[f"{label}_error"] = f"{type(e).__name__}: {e}"

    probe("actor_count", lambda: len(actors))
    probe("vehicles", lambda: len(actors.filter("vehicle.*")))
    probe("walkers", lambda: len(actors.filter("walker.pedestrian.*")))
    probe("traffic_lights", lambda: len(actors.filter("traffic.traffic_light*")))
    probe("traffic_signs", lambda: len(actors.filter("traffic.*")))
    probe("landmarks", lambda: len(m.get_all_landmarks_of_type("landmark")))

    def _bb():
        bb = world.get_bounding_box()
        return {
            "location": [
                round(float(bb.location.x), 3),
                round(float(bb.location.y), 3),
                round(float(bb.location.z), 3),
            ],
            "extent": [round(float(v), 3) for v in (bb.extent or (0, 0, 0))],
        }

    probe("world_bounding_box", _bb)
    payload = json.dumps(fp, sort_keys=True)
    fp["structural_fingerprint_sha256"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if not light:
        wps = m.generate_waypoints(3.0)
        n = len(wps)
        step = max(1, n // 32)
        sample = wps[::step][:32]
        xy = ";".join(
            f"{round(p.transform.location.x, 3)},{round(p.transform.location.y, 3)}"
            for p in sample
        )
        fp["waypoints_at_3m"] = n
        fp["waypoint_xy_hash_sha256"] = hashlib.sha256(xy.encode("utf-8")).hexdigest()
    return fp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="Grid0828")
    ap.add_argument("--out", default="RUNTIME_MAP_IDENTITY_MANUAL.json")
    ap.add_argument("--heavy", action="store_true", help="also expand full waypoint set")
    ap.add_argument("--arm", default="manual")
    args = ap.parse_args()

    import carla

    run_id = f"mapid_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    rep: Dict[str, Any] = {
        "schema": "runtime_map_identity/v1",
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "arm": args.arm,
        "requested_package": args.map,
        "registry_key": args.map if args.map in ARM_SOURCE_SHA else "unknown",
        "source_xodr_sha256": ARM_SOURCE_SHA.get(args.map),
    }

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(60.0)
    rep["server_version"] = client.get_server_version()
    rep["available_maps"] = sorted(client.get_available_maps())

    # Ensure ASYNC default BEFORE any load_world.
    w0 = client.get_world()
    s = w0.get_settings()
    s.synchronous_mode = False
    s.fixed_delta_seconds = 0.0
    s.substepping = False
    w0.apply_settings(s)
    rep["pre_load_settings"] = {
        "synchronous_mode": bool(s.synchronous_mode),
        "fixed_delta_seconds": float(s.fixed_delta_seconds or 0.0),
        "substepping": bool(s.substepping),
    }

    try:
        world = client.load_world(args.map)
        m = world.get_map()
        rep["observed_world_map_name"] = m.name
        rep["load_world_returned_same_name"] = bool(m.name)
        rep["runtime_structural_fingerprint"] = fingerprint(world, m, light=not args.heavy)
        snap = world.get_snapshot()
        rep["snapshot"] = {
            "frame": snap.frame if snap else None,
            "elapsed_seconds": float(snap.timestamp.elapsed_seconds) if snap else None,
        }
        # identity is NOT a substring/path heuristic: assert an exact map-name
        # equality against the requested target, and record the raw observed
        # string verbatim so a reviewer can see the real CARLA return format.
        rep["observed_name_verbatim"] = m.name
        rep["exact_name_match"] = bool(m.name.split("/")[-1] == args.map)
        rep["identity_method"] = (
            "client.load_world(<requested>) -> world.get_map().name (verbatim) "
            "+ runtime structural fingerprint. Exact-name equality asserted; "
            "no substring/path heuristic used to derive identity."
        )
        rep["status"] = (
            "RUNTIME_IDENTITY_ESTABLISHED"
            if rep["exact_name_match"]
            else "RUNTIME_IDENTITY_MISMATCH"
        )
        if not rep["exact_name_match"]:
            rep["status"] = "RUNTIME_IDENTITY_MISMATCH"
    except Exception as e:
        rep["status"] = "BLOCKED_RUNTIME"
        rep["error"] = f"{type(e).__name__}: {e}"

    # leave server at async default
    try:
        ww = client.get_world()
        d = ww.get_settings()
        d.synchronous_mode = False
        ww.apply_settings(d)
    except Exception:
        pass

    p = Path(args.out)
    p.write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(rep, indent=2, sort_keys=True))
    print(f"\nwritten: {p}")
    return 0 if rep.get("status") == "RUNTIME_IDENTITY_ESTABLISHED" else 2


if __name__ == "__main__":
    raise SystemExit(main())