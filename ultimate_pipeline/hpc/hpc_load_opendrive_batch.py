#!/usr/bin/env python3
"""hpc_load_opendrive_batch.py

Batch-load OpenDRIVE files into CARLA and write a CSV summary.

This script prefers your canonical loader:
  ultimate_pipeline.core.carla_opendrive_loader.load_opendrive_world

Fallback:
  client.generate_opendrive_world(xodr_text)

Tip:
- Use --baseline-map Town01 to force a known clean starting map before each import.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
def _iter_xodr_paths(p: Path):
    if p.is_file():
        if p.suffix.lower() == ".xodr":
            yield p
        return
    for f in sorted(p.rglob("*.xodr")):
        yield f

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True, help="Path to .xodr file or directory containing .xodr files")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--do-reload", action="store_true", default=True)
    ap.add_argument("--no-do-reload", dest="do_reload", action="store_false")
    ap.add_argument("--baseline-map", default="", help="Optional built-in Town name to load first (e.g. Town01)")
    ap.add_argument("--csv-out", default="opendrive_load_results.csv")
    ap.add_argument("--sleep-between", type=float, default=0.0, help="Optional delay between loads (seconds)")
    args = ap.parse_args()

    try:
        import carla
    except Exception as e:
        print(f"❌ CARLA import failed: {e}")
        return 1

    client = carla.Client(args.host, args.port)
    client.set_timeout(max(10.0, args.timeout))

    # Prefer canonical loader
    loader = None
    default_params = None
    default_opendrive_generation_params = None
    try:
        from ultimate_pipeline.core.carla_opendrive_loader import (
            default_opendrive_generation_params,
            load_opendrive_world as loader,
        )
        loader_name = "canonical load_opendrive_world"
    except Exception:
        loader_name = "client.generate_opendrive_world fallback"

    xodr_path = Path(args.xodr)
    files = list(_iter_xodr_paths(xodr_path))
    if not files:
        print(f"❌ No .xodr files found at: {xodr_path}")
        return 1

    print(f"🔧 Loader: {loader_name}")
    print(f"📄 Files: {len(files)}")
    if args.baseline_map:
        print(f"🧼 Baseline map: {args.baseline_map}")

    rows = []
    for i, f in enumerate(files, start=1):
        print(f"\n[{i}/{len(files)}] Loading {f} ...")
        xodr_text = f.read_text(encoding="utf-8", errors="replace")

        t0 = time.time()
        try:
            if args.baseline_map:
                _reload_ready_for_sensors(client, map_name=args.baseline_map, tm_port=8000)

            if loader is not None:
                world = loader(
                    client,
                    xodr_text,
                    timeout_s=float(args.timeout),
                    retries=int(args.retries),
                    do_reload=bool(args.do_reload),
                )
            else:
                if default_params is None:
                    if default_opendrive_generation_params is not None:
                        default_params = default_opendrive_generation_params(carla)
                    else:
                        default_params = carla.OpendriveGenerationParameters()
                        default_params.map_layers = carla.MapLayer.NONE
                        default_params.wall_height = 0.0
                        default_params.additional_width = 0.0
                        default_params.vertex_distance = float(os.environ.get("UP_OD_VERTEX_DISTANCE", "1.0"))
                        default_params.smooth_junctions = True
                world = _reload_ready_for_sensors(client, xodr_string=xodr_text, tm_port=8000, xodr_generation_params=default_params)

            m = world.get_map()
            sp = m.get_spawn_points()
            elapsed = time.time() - t0

            row = {
                "file": str(f),
                "status": "ok",
                "map_name": getattr(m, "name", "<unknown>"),
                "spawn_points": len(sp) if sp is not None else -1,
                "seconds": round(elapsed, 3),
            }
            print(f"✅ OK  map={row['map_name']}  spawn_points={row['spawn_points']}  t={row['seconds']}s")
        except Exception as e:
            elapsed = time.time() - t0
            row = {
                "file": str(f),
                "status": "error",
                "map_name": "",
                "spawn_points": -1,
                "seconds": round(elapsed, 3),
                "error": str(e),
            }
            print(f"❌ ERROR after {row['seconds']}s: {e}")

        rows.append(row)

        if args.sleep_between > 0:
            time.sleep(args.sleep_between)

    # Write CSV
    out = Path(args.csv_out)
    fieldnames = sorted({k for r in rows for k in r.keys()})
    with out.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"\n📁 Wrote: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
