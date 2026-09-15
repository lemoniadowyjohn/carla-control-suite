#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Full-grid per-tile FBX cook for CARLA Large-Map cooking (all 20 occupied tiles).

This script extends the single-tile probe (``tools/probe_tile_fbx_densest.py``)
to cook **every occupied tile** in the 1 km grid for the pinned Ingolstadt
map-of-record.  It reuses *exactly* the same per-tile API
(``generate_tile_fbx``) without modifying it.

Key design decisions
--------------------
Checkpointing
    Results are written incrementally as each tile finishes -- to a
    ``CHECKPOINT.json`` that is overwritten after every tile -- so a partial run
    is never entirely wasted.  A full ``COOK_RESULTS.json`` is written only once
    all tiles finish (or the run is manually interrupted, in which case the last
    CHECKPOINT.json is the recoverable record).

Order
    Tiles are cooked densest-first (descending building count).  This means the
    slowest tile goes first, so timing predictions are conservative.

Error handling
    A tile that fails OSM2World or Blender is recorded with ``status=failed``
    and its error reason; the cook continues.  Only tiles with *new* failure
    modes (different from the known probe pass/OSM2World elevator bug) are
    flagged in the summary.  The exit code is 0 only if every tile is ``ok``.

Claim boundary
    This is offline FBX generation only.  No UE4/UE5 Editor is invoked.
    Runtime streaming/seam behavior remains UNCONFIRMED until the live UE4 track
    runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.tiling.tile_fbx_generator import (  # noqa: E402
    TileAssignment,
    TileGridSpec,
    assign_buildings_to_tiles,
    generate_tile_fbx,
    load_buildings_from_overpass_json,
)

# ---------------------------------------------------------------------------
# Pinned source constants (verified against probe PROBE_RESULT.json)
# ---------------------------------------------------------------------------
PINNED_BUILDINGS = (
    REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "source"
    / "ingolstadt_buildings_overpass.json"
)
PINNED_XODR = (
    REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate"
    / "ingolstadt_perception_map_of_record_20260905_202847.xodr"
)
# The XODR header offset (global tmerc metres) used by the probe and unit tests.
HEADER_OFFSET_XY: Tuple[float, float] = (832671.676, 5458671.104)
MAP_NAME = "Ingolstadt"
TILE_SIZE_M = 1000.0

# OSM2World binary location (same as probe script; untracked binary).
DEFAULT_OSM2WORLD_HOME = str(
    Path(r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main")
    / "carla_governed" / "OSM2World-latest-bin"
)

# Expected counts from the probe (for cross-check).
EXPECTED_OCCUPIED_CELLS = 20
EXPECTED_BUILDINGS_TOTAL = 5712


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_checkpoint(
    checkpoint_path: Path,
    run_id: str,
    completed: List[Dict[str, Any]],
    remaining: List[Tuple[int, int]],
    wall_elapsed_sec: float,
) -> None:
    """Overwrite CHECKPOINT.json with the latest partial result."""
    doc = {
        "schema_version": 1,
        "run_id": run_id,
        "wall_elapsed_sec": round(wall_elapsed_sec, 2),
        "tiles_completed": len(completed),
        "tiles_remaining": len(remaining),
        "results": completed,
    }
    checkpoint_path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _build_summary(
    run_id: str,
    assignment: TileAssignment,
    all_results: List[Dict[str, Any]],
    wall_elapsed_sec: float,
    source_provenance: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble the final COOK_RESULTS.json document."""
    ok_count = sum(1 for r in all_results if r.get("status") == "ok")
    failed_count = sum(1 for r in all_results if r.get("status") == "failed")
    empty_count = sum(1 for r in all_results if r.get("status") == "empty")
    roundtrip_pass = sum(1 for r in all_results if r.get("roundtrip_ok") is True)
    roundtrip_fail = sum(1 for r in all_results if r.get("roundtrip_ok") is False)

    # Anomalies: any non-ok tile.
    anomalies = [
        {
            "tile": r.get("tile_index"),
            "status": r.get("status"),
            "reason": r.get("reason", ""),
            "roundtrip_ok": r.get("roundtrip_ok"),
            "roundtrip_verdict": r.get("roundtrip_verdict", ""),
        }
        for r in all_results
        if r.get("status") != "ok"
    ]

    return {
        "schema_version": 1,
        "artifact_type": "carla_large_map_full_grid_fbx_cook",
        "run_id": run_id,
        "map_name": MAP_NAME,
        "tile_size_m": TILE_SIZE_M,
        "wall_elapsed_sec": round(wall_elapsed_sec, 2),
        "buildings_loaded": assignment.total_placed() + len(assignment.unplaceable),
        "buildings_placed": assignment.total_placed(),
        "buildings_unplaceable": len(assignment.unplaceable),
        "occupied_cells": len(assignment.tiles),
        "tiles_attempted": len(all_results),
        "tiles_ok": ok_count,
        "tiles_failed": failed_count,
        "tiles_empty": empty_count,
        "roundtrip_pass": roundtrip_pass,
        "roundtrip_fail": roundtrip_fail,
        "anomalies": anomalies,
        "results": all_results,
        "source_provenance": source_provenance,
        "claim_boundary": (
            "Offline FBX generation only. No UE4/UE5 Editor was invoked. "
            "Runtime streaming/seam behavior is UNCONFIRMED until the live UE4 track runs."
        ),
    }


def cook_all_tiles(
    *,
    osm2world_home: str,
    blender_exe: Optional[str],
    report_dir: Path,
    artifacts_dir: Path,
    run_roundtrip: bool,
    verbose: bool,
) -> int:
    """Load, partition, cook all occupied tiles; write incremental + final evidence.

    Returns 0 if every tile produced status ``ok``, non-zero otherwise.
    """
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = report_dir / "CHECKPOINT.json"

    print(f"[cook_grid] run_id={run_id}")
    print(f"[cook_grid] report_dir={report_dir}")
    print(f"[cook_grid] artifacts_dir={artifacts_dir}")

    # ------------------------------------------------------------------
    # Verify pinned source files exist
    # ------------------------------------------------------------------
    if not PINNED_BUILDINGS.exists():
        print(f"[ERROR] buildings source not found: {PINNED_BUILDINGS}", file=sys.stderr)
        return 1
    if not PINNED_XODR.exists():
        print(f"[ERROR] XODR map-of-record not found: {PINNED_XODR}", file=sys.stderr)
        return 1

    buildings_sha = _sha256(PINNED_BUILDINGS)
    xodr_sha = _sha256(PINNED_XODR)

    def _rel(p: Path) -> str:
        """Return path relative to REPO_ROOT when possible, else absolute."""
        try:
            return str(p.relative_to(REPO_ROOT))
        except ValueError:
            return str(p)

    source_provenance = {
        "buildings_source": _rel(PINNED_BUILDINGS),
        "buildings_source_sha256": buildings_sha,
        "map_of_record": _rel(PINNED_XODR),
        "map_of_record_sha256": xodr_sha,
        "header_offset_xy": list(HEADER_OFFSET_XY),
        "tile_size_m": TILE_SIZE_M,
    }
    print(f"[cook_grid] buildings sha256={buildings_sha[:16]}...")
    print(f"[cook_grid] xodr sha256={xodr_sha[:16]}...")

    # ------------------------------------------------------------------
    # Load and partition
    # ------------------------------------------------------------------
    t_start = time.time()
    print("[cook_grid] loading buildings ...")
    buildings = load_buildings_from_overpass_json(str(PINNED_BUILDINGS))
    grid = TileGridSpec(tile_size_m=TILE_SIZE_M, header_offset_xy=HEADER_OFFSET_XY)
    assignment = assign_buildings_to_tiles(buildings, grid)

    placed = assignment.total_placed()
    n_cells = len(assignment.tiles)
    print(
        f"[cook_grid] loaded {len(buildings)} buildings, placed {placed}, "
        f"unplaceable {len(assignment.unplaceable)}, occupied cells {n_cells}"
    )

    # Partition self-check (mirrors probe assertion).
    placed_ids = [b.source_id for cell in assignment.tiles.values() for b in cell]
    assert len(placed_ids) == len(set(placed_ids)), "PARTITION VIOLATION: duplicate building id"
    assert placed + len(assignment.unplaceable) == len(buildings), "building count mismatch"

    if n_cells != EXPECTED_OCCUPIED_CELLS:
        print(
            f"[WARN] expected {EXPECTED_OCCUPIED_CELLS} occupied cells, got {n_cells}. "
            "Continuing; cross-check the buildings source.",
            file=sys.stderr,
        )

    # Cook densest-first (slowest tile goes first for conservative timing).
    ordered: List[Tuple[Tuple[int, int], int]] = sorted(
        ((cell, len(bs)) for cell, bs in assignment.tiles.items()),
        key=lambda kv: (-kv[1], kv[0]),
    )
    tile_order = [cell for cell, _ in ordered]

    print(f"[cook_grid] will cook {len(tile_order)} tiles in density order:")
    for i, (cell, n) in enumerate(ordered, 1):
        print(f"  {i:2d}. tile {cell} -- {n} buildings")

    # ------------------------------------------------------------------
    # Per-tile cook loop with checkpointing
    # ------------------------------------------------------------------
    all_results: List[Dict[str, Any]] = []
    per_tile_source_prov = {
        **source_provenance,
        "osm2world_home": osm2world_home,
    }

    for idx, tile_index in enumerate(tile_order, 1):
        tx, ty = tile_index
        tile_buildings = assignment.tiles[tile_index]
        n_bldgs = len(tile_buildings)
        remaining = tile_order[idx:]

        print(
            f"\n[cook_grid] [{idx}/{len(tile_order)}] tile ({tx},{ty}) -- "
            f"{n_bldgs} buildings ..."
        )
        tile_t0 = time.time()

        result = generate_tile_fbx(
            buildings=tile_buildings,
            tile_index=tile_index,
            map_name=MAP_NAME,
            output_dir=str(artifacts_dir / f"tile_{tx}_{ty}"),
            osm2world_home=osm2world_home,
            blender_exe=blender_exe,
            run_roundtrip=run_roundtrip,
            source_provenance=per_tile_source_prov,
        )

        elapsed_tile = round(time.time() - tile_t0, 2)
        status_str = result.status.upper()
        rt_str = result.roundtrip_verdict if result.roundtrip_verdict else "N/A"
        print(
            f"[cook_grid]   -> status={status_str} "
            f"objects={result.objects_total} vertices={result.vertices_total} "
            f"faces={result.faces_total} "
            f"fbx={result.fbx_bytes / 1024:.1f} KB "
            f"roundtrip={rt_str} "
            f"total={elapsed_tile}s"
        )
        if result.reason:
            print(f"[cook_grid]   reason: {result.reason}")

        all_results.append(result.to_dict())

        # Write checkpoint after every tile (recovery safety net).
        _write_checkpoint(
            checkpoint_path,
            run_id=run_id,
            completed=all_results,
            remaining=remaining,
            wall_elapsed_sec=time.time() - t_start,
        )
        if verbose:
            print(json.dumps(result.to_dict(), indent=2))

    # ------------------------------------------------------------------
    # Final summary documents
    # ------------------------------------------------------------------
    wall_elapsed = time.time() - t_start
    summary = _build_summary(
        run_id=run_id,
        assignment=assignment,
        all_results=all_results,
        wall_elapsed_sec=wall_elapsed,
        source_provenance=source_provenance,
    )

    results_path = report_dir / "COOK_RESULTS.json"
    results_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"\n[cook_grid] -- SUMMARY --")
    print(f"  tiles attempted : {summary['tiles_attempted']}")
    print(f"  tiles ok        : {summary['tiles_ok']}")
    print(f"  tiles failed    : {summary['tiles_failed']}")
    print(f"  roundtrip pass  : {summary['roundtrip_pass']}")
    print(f"  roundtrip fail  : {summary['roundtrip_fail']}")
    print(f"  wall clock      : {wall_elapsed:.1f}s")
    if summary["anomalies"]:
        print(f"  ANOMALIES ({len(summary['anomalies'])}):")
        for a in summary["anomalies"]:
            print(
                f"    tile {a['tile']}: status={a['status']} "
                f"reason={a['reason']!r}"
            )
    print(f"[cook_grid] wrote {results_path}")

    # Build per-tile Markdown table.
    table_lines = [
        "| tile (tx,ty) | buildings | objects | vertices | faces "
        "| FBX size (KB) | roundtrip | total_sec | status |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in all_results:
        ti = r.get("tile_index", [])
        tile_str = f"({ti[0]},{ti[1]})" if len(ti) == 2 else str(ti)
        fb_kb = round(r.get("fbx_bytes", 0) / 1024, 1)
        table_lines.append(
            f"| {tile_str} "
            f"| {r.get('building_count', 0)} "
            f"| {r.get('objects_total', 0)} "
            f"| {r.get('vertices_total', 0)} "
            f"| {r.get('faces_total', 0)} "
            f"| {fb_kb} "
            f"| {r.get('roundtrip_verdict', 'N/A')} "
            f"| {r.get('total_sec', 0.0)} "
            f"| {r.get('status', '?')} |"
        )
    table_md = "\n".join(table_lines)

    anomaly_text = (
        "\n".join(
            f"- tile {a['tile']}: status={a['status']} reason={a['reason']!r} "
            f"roundtrip={a.get('roundtrip_verdict', '')}"
            for a in summary["anomalies"]
        )
        if summary["anomalies"]
        else "None."
    )
    design_md = (
        f"# Full-Grid Per-Tile FBX Cook -- {run_id}\n\n"
        f"- **Run ID:** `{run_id}`\n"
        f"- **Branch:** `feature/full-grid-tile-fbx-cook-v1-20260915`\n"
        f"- **Tiles attempted:** {summary['tiles_attempted']}\n"
        f"- **Tiles OK:** {summary['tiles_ok']}\n"
        f"- **Tiles failed:** {summary['tiles_failed']}\n"
        f"- **Roundtrip PASS:** {summary['roundtrip_pass']}\n"
        f"- **Roundtrip FAIL:** {summary['roundtrip_fail']}\n"
        f"- **Wall clock:** {wall_elapsed:.1f}s\n"
        f"- **Claim boundary:** Offline FBX generation only. "
        f"No UE4/UE5 Editor invoked.\n\n"
        f"## Per-Tile Results\n\n"
        f"{table_md}\n\n"
        f"## Source Provenance\n\n"
        f"```json\n{json.dumps(source_provenance, indent=2)}\n```\n\n"
        f"## Anomalies\n\n"
        f"{anomaly_text}\n"
    )
    (report_dir / "COOK_RESULTS.md").write_text(design_md, encoding="utf-8")

    return 0 if summary["tiles_ok"] == summary["tiles_attempted"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--osm2world-home", default=DEFAULT_OSM2WORLD_HOME,
        help="Path to OSM2World binary directory",
    )
    parser.add_argument(
        "--blender-exe", default=None,
        help="Path to Blender executable (default: BlenderRunner default)",
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="Override report root dir (default: reports/production_readiness/…)",
    )
    parser.add_argument(
        "--artifacts-dir", default=None,
        help="Override per-tile artifact dir (default: <out-dir>/artifacts)",
    )
    parser.add_argument(
        "--no-roundtrip", action="store_true",
        help="Skip FBX roundtrip check (faster, less evidence)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print full JSON result for each tile",
    )
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.out_dir:
        report_dir = Path(args.out_dir)
    else:
        report_dir = (
            REPO_ROOT / "reports" / "production_readiness"
            / f"{ts}_FULL_GRID_TILE_FBX_COOK"
        )

    artifacts_dir = (
        Path(args.artifacts_dir) if args.artifacts_dir
        else report_dir / "artifacts"
    )

    return cook_all_tiles(
        osm2world_home=args.osm2world_home,
        blender_exe=args.blender_exe,
        report_dir=report_dir,
        artifacts_dir=artifacts_dir,
        run_roundtrip=not args.no_roundtrip,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    sys.exit(main())
