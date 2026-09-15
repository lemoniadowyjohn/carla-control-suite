#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Go/no-go probe: cook the single densest 1 km tile's FBX from the pinned map.

This is the concrete validation the tile-based UE4 cooking design
(``reports/production_readiness/20260915T140000Z_TILE_BASED_UE4_COOKING_DESIGN/DESIGN.md``
§4.5, §5 item 5) called for -- run it, don't describe it. It:

  1. Loads the pinned Overpass-JSON building source.
  2. Partitions all buildings across a 1000 m grid by footprint centroid.
  3. Identifies the densest occupied tile by building count.
  4. Runs the full clip -> OSM2World -> Blender -> FBX -> roundtrip path for that
     one tile via ``ultimate_pipeline.tiling.tile_fbx_generator.generate_tile_fbx``.
  5. Writes real numbers (object/vertex/face counts, file size, roundtrip
     pass/fail, timings) to a dated evidence directory.

It does NOT run any UE4/UE5 Editor (none exists on this machine); the FBX side is
fully offline.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.tiling.tile_fbx_generator import (  # noqa: E402
    TileGridSpec,
    assign_buildings_to_tiles,
    generate_tile_fbx,
    load_buildings_from_overpass_json,
)

# Pinned artifacts (DESIGN.md §0; hashes verified there).
PINNED_BUILDINGS = (
    REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "source"
    / "ingolstadt_buildings_overpass.json"
)
PINNED_XODR = (
    REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate"
    / "ingolstadt_perception_map_of_record_20260905_202847.xodr"
)
# XODR header offset (global tmerc metres) -> XODR-local frame (map_stats.json).
HEADER_OFFSET_XY = (832671.676, 5458671.104)
MAP_NAME = "Ingolstadt"
TILE_SIZE_M = 1000.0

# OSM2World jar is an untracked/gitignored binary; default to the canonical
# install in the primary checkout so a git-worktree run still finds it.
DEFAULT_OSM2WORLD_HOME = str(
    Path(r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main")
    / "carla_governed" / "OSM2World-latest-bin"
)


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm2world-home", default=DEFAULT_OSM2WORLD_HOME)
    parser.add_argument("--blender-exe", default=None)
    parser.add_argument("--out-dir", default=None,
                        help="tile artifact dir (default: reports/.../artifacts)")
    parser.add_argument("--tile", default=None,
                        help="force a specific tile 'tx,ty' (default: densest)")
    parser.add_argument("--no-roundtrip", action="store_true")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_dir = (REPO_ROOT / "reports" / "production_readiness"
                  / f"{run_id}_TILE_BASED_FBX_GENERATION_PROBE")
    artifacts_dir = Path(args.out_dir) if args.out_dir else report_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    print(f"[probe] run_id={run_id}")
    print(f"[probe] loading buildings from {PINNED_BUILDINGS.name}")
    buildings = load_buildings_from_overpass_json(str(PINNED_BUILDINGS))
    grid = TileGridSpec(tile_size_m=TILE_SIZE_M, header_offset_xy=HEADER_OFFSET_XY)
    assignment = assign_buildings_to_tiles(buildings, grid)

    placed = assignment.total_placed()
    print(f"[probe] loaded {len(buildings)} buildings, placed {placed}, "
          f"unplaceable {len(assignment.unplaceable)}, "
          f"occupied cells {len(assignment.tiles)}")

    # partition self-check
    placed_ids = [b.source_id for cell in assignment.tiles.values() for b in cell]
    assert len(placed_ids) == len(set(placed_ids)), "PARTITION VIOLATION: duplicate building"
    assert placed + len(assignment.unplaceable) == len(buildings), "buildings lost"

    density = sorted(
        ((cell, len(bs)) for cell, bs in assignment.tiles.items()),
        key=lambda kv: (-kv[1], kv[0]),
    )
    if args.tile:
        tx, ty = (int(v) for v in args.tile.split(","))
        target = (tx, ty)
    else:
        target = density[0][0]
    target_buildings = assignment.tiles.get(target, [])
    print(f"[probe] densest tile = {density[0][0]} ({density[0][1]} buildings)")
    print(f"[probe] cooking tile {target} with {len(target_buildings)} buildings")

    result = generate_tile_fbx(
        buildings=target_buildings,
        tile_index=target,
        map_name=MAP_NAME,
        output_dir=str(artifacts_dir),
        osm2world_home=args.osm2world_home,
        blender_exe=args.blender_exe,
        run_roundtrip=not args.no_roundtrip,
        source_provenance={
            "buildings_source": str(PINNED_BUILDINGS),
            "buildings_source_sha256": _sha256(PINNED_BUILDINGS),
            "map_of_record": str(PINNED_XODR),
            "map_of_record_sha256_prefix": _sha256(PINNED_XODR)[:16],
            "header_offset_xy": list(HEADER_OFFSET_XY),
            "tile_size_m": TILE_SIZE_M,
        },
    )

    print("[probe] result:")
    print(json.dumps(result.to_dict(), indent=2))

    probe_doc = {
        "run_id": run_id,
        "map_name": MAP_NAME,
        "tile_size_m": TILE_SIZE_M,
        "buildings_loaded": len(buildings),
        "buildings_placed": placed,
        "buildings_unplaceable": len(assignment.unplaceable),
        "occupied_cells": len(assignment.tiles),
        "partition_verified_disjoint": len(placed_ids) == len(set(placed_ids)),
        "density_top10": [
            {"tile": list(cell), "buildings": n} for cell, n in density[:10]
        ],
        "probe_tile": list(target),
        "probe_result": result.to_dict(),
        "source_provenance": {
            "buildings_source": str(PINNED_BUILDINGS.relative_to(REPO_ROOT)),
            "buildings_source_sha256": _sha256(PINNED_BUILDINGS),
            "map_of_record": str(PINNED_XODR.relative_to(REPO_ROOT)),
            "map_of_record_sha256": _sha256(PINNED_XODR),
        },
    }
    (report_dir / "PROBE_RESULT.json").write_text(
        json.dumps(probe_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[probe] wrote {report_dir / 'PROBE_RESULT.json'}")
    return 0 if result.status == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
