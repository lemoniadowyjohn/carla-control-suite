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
import os
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
from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map  # noqa: E402

# ---------------------------------------------------------------------------
# Pinned source constants (verified against probe PROBE_RESULT.json)
# ---------------------------------------------------------------------------
PINNED_BUILDINGS = (
    REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "source"
    / "ingolstadt_buildings_overpass.json"
)
_pinned = verify_pinned_map("auto_map_of_record")
PINNED_XODR = Path(_pinned["path"])


def _header_offset_from_registry(pin: Dict[str, Any]) -> Tuple[float, float]:
    """Extract (rebase_dx, rebase_dy) from a verified registry receipt (A2).

    The authoritative source is PINNED_MAP_REGISTRY's structured frame
    fields on the map-of-record entry, exposed via verify_pinned_map().
    Values match the XODR <offset> header (832671.676, 5458671.104) and the
    human-readable 'frame' text; they are never re-typed here so the frame
    cannot drift from the registration. A missing field is a registry
    schema violation and fails closed -- no developer-machine fallback.
    """
    dx = pin.get("rebase_dx")
    dy = pin.get("rebase_dy")
    if dx is None or dy is None:
        raise ValueError(
            f"Registry entry '{pin.get('registry_key', pin.get('key', 'auto_map_of_record'))}' "
            "is missing structured frame fields 'rebase_dx' / 'rebase_dy'. "
            "These must be present in PINNED_MAP_REGISTRY under "
            "ultimate_pipeline/carla_tools/map_registry.py for the "
            "frame_kind='rebased_local' entry. Check the 'frame' text string "
            "in that entry for the human-readable values and promote them to "
            "the structured fields."
        )
    return (float(dx), float(dy))


# HEADER_OFFSET_XY is the authoritative global-tmerc rebase origin for this
# map, resolved from the pinned map registry (not a re-typed literal).
HEADER_OFFSET_XY: Tuple[float, float] = _header_offset_from_registry(_pinned)
MAP_NAME = "Ingolstadt"
TILE_SIZE_M = 1000.0


def _resolve_default_osm2world_home() -> str:
    """Portable OSM2World default (A1, import-safe, never raises).

    Precedence: OSM2WORLD_HOME env (when set) > <repo>/carla_governed/
    OSM2World-latest-bin > <repo>/OSM2World-latest-bin. Returns the first
    candidate path even if missing; existence is validated at execution
    time with a precise error naming every mechanism checked.
    """
    env_home = os.environ.get("OSM2WORLD_HOME", "").strip()
    if env_home:
        return env_home
    governed = REPO_ROOT / "carla_governed" / "OSM2World-latest-bin"
    if governed.is_dir():
        return str(governed)
    return str(REPO_ROOT / "OSM2World-latest-bin")


def _require_osm2world_home(configured: Optional[str], *, context: str) -> str:
    """Validate the OSM2World home for execution (A1: precise failure).

    Checks, in order: --osm2world-home CLI value, OSM2WORLD_HOME env var,
    portable repo-relative defaults. Raises SystemExit with an actionable
    message when nothing resolves to an existing directory.
    """
    candidates: List[str] = []
    if configured and str(configured).strip():
        candidates.append(str(configured).strip())
    env_home = os.environ.get("OSM2WORLD_HOME", "").strip()
    if env_home and env_home not in candidates:
        candidates.append(env_home)
    for fallback in (
        str(REPO_ROOT / "carla_governed" / "OSM2World-latest-bin"),
        str(REPO_ROOT / "OSM2World-latest-bin"),
    ):
        if fallback not in candidates:
            candidates.append(fallback)
    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            return candidate
    checked = "; ".join(f"'{c}'" for c in candidates)
    raise SystemExit(
        f"[ERROR] {context}: OSM2World home not found. Checked in order: "
        f"CLI --osm2world-home, OSM2WORLD_HOME env var, portable repo defaults; "
        f"all candidates missing: {checked}. Provide a valid directory via "
        f"--osm2world-home <dir> or OSM2WORLD_HOME=<dir>."
    )


# OSM2World binary location (untracked binary). Resolution order (A1):
#   1. --osm2world-home CLI argument (validated at execution time)
#   2. OSM2WORLD_HOME environment variable
#   3. <repo_root>/carla_governed/OSM2World-latest-bin (canonical layout)
#   4. <repo_root>/OSM2World-latest-bin (legacy layout)
# Import-time default is the portable first-existing candidate (never a
# developer-machine absolute path); missing binaries fail at execution with
# a precise error from _require_osm2world_home().
DEFAULT_OSM2WORLD_HOME = _resolve_default_osm2world_home()

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
    semantic_non_buildings_total = sum(
        (r.get("semantic_classification") or {}).get("non_buildings_count", 0)
        for r in all_results
    )

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
        "semantic_non_buildings_total": semantic_non_buildings_total,
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
    # Verify pinned source files exist — O1: resolve through registry authority
    # at execution time (not just import-time PINNED_XODR) so a stale pin
    # cannot survive a re-promotion between import and execution.
    # ------------------------------------------------------------------
    # Re-resolve authoritative XODR via verify_pinned_map (fresh, fail-closed).
    try:
        _fresh = verify_pinned_map("auto_map_of_record")
        _fresh_path = Path(_fresh["path"])
        # _fresh["path"] is repo-relative; resolve to absolute via REPO_ROOT
        # when it is not already absolute after verify_pinned_map's own
        # resolve_contained_path.  verify_pinned_map already validated bytes+sha,
        # so we reuse its proven SHA directly (no second hash for XODR).
        if not _fresh_path.is_absolute():
            # verify_pinned_map's resolved_path is absolute and verified
            _fresh_path = Path(_fresh["resolved_path"])
        authoritative_xodr = _fresh_path
        authoritative_xodr_sha = _fresh["sha256"]
        authoritative_xodr_bytes = _fresh["bytes"]
    except Exception as exc:
        print(f"[ERROR] failed to resolve authoritative XODR via verify_pinned_map: {exc}", file=sys.stderr)
        return 1

    if not PINNED_BUILDINGS.exists():
        print(f"[ERROR] buildings source not found: {PINNED_BUILDINGS}", file=sys.stderr)
        return 1
    if not authoritative_xodr.exists():
        print(f"[ERROR] XODR map-of-record not found: {authoritative_xodr}", file=sys.stderr)
        return 1
    # Verify on-disk bytes still match the verified receipt (defends against a
    # race where the file was swapped after verify_pinned_map).
    try:
        actual_bytes = authoritative_xodr.stat().st_size
        if actual_bytes != authoritative_xodr_bytes:
            print(f"[ERROR] authoritative XODR byte-size drift after verification: expected {authoritative_xodr_bytes}, got {actual_bytes}", file=sys.stderr)
            return 1
        # Re-hash to ensure content matches receipt (verify_pinned_map already
        # did, but double-check after any potential race).
        authoritative_xodr_sha_rehash = _sha256(authoritative_xodr)
        if authoritative_xodr_sha_rehash != authoritative_xodr_sha:
            print(f"[ERROR] authoritative XODR sha drift after verification: expected {authoritative_xodr_sha}, got {authoritative_xodr_sha_rehash}", file=sys.stderr)
            return 1
    except OSError as exc:
        print(f"[ERROR] cannot stat/hash authoritative XODR: {exc}", file=sys.stderr)
        return 1

    buildings_sha = _sha256(PINNED_BUILDINGS)
    xodr_sha = authoritative_xodr_sha
    # Use authoritative (registry-resolved) XODR for all downstream provenance
    resolved_xodr_for_provenance = authoritative_xodr

    def _rel(p: Path) -> str:
        """Return path relative to REPO_ROOT when possible, else absolute."""
        try:
            return str(p.relative_to(REPO_ROOT))
        except ValueError:
            return str(p)

    source_provenance = {
        "buildings_source": _rel(PINNED_BUILDINGS),
        "buildings_source_sha256": buildings_sha,
        "map_of_record": _rel(resolved_xodr_for_provenance),
        "map_of_record_sha256": xodr_sha,
        "header_offset_xy": list(HEADER_OFFSET_XY),
        "tile_size_m": TILE_SIZE_M,
        "provenance_authority": "verify_pinned_map('auto_map_of_record')",
        "registry_sha256": _fresh.get("registry_sha256", ""),
    }
    print(f"[cook_grid] buildings sha256={buildings_sha[:16]}...")
    print(f"[cook_grid] xodr sha256={xodr_sha[:16]}... (verified via registry, bytes={authoritative_xodr_bytes})")

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

        # O1: Existing FBX is reusable only if its manifest proves current XODR SHA
        # (no mtime, no latest-file).  Check the existing tile's manifest+FBX
        # before deciding to regenerate.  This is the only reuse path — a stale
        # FBX (different source SHA) is never reused, and a missing manifest
        # forces regeneration (fail-closed).
        existing_tile_dir = artifacts_dir / f"tile_{tx}_{ty}"
        existing_manifest_path = existing_tile_dir / f"{MAP_NAME}_Tile_{tx}_{ty}.tile_fbx.json"
        existing_fbx_path = existing_tile_dir / f"{MAP_NAME}_Tile_{tx}_{ty}.fbx"
        reuse_candidate = False
        if existing_manifest_path.is_file() and existing_fbx_path.is_file():
            try:
                _existing_doc = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
                _existing_prov = _existing_doc.get("source_provenance") or {}
                _existing_sha = _existing_prov.get("map_of_record_sha256")
                _manifest_fbx_sha = (_existing_doc.get("fbx") or {}).get("sha256")
                _manifest_fbx_bytes = (_existing_doc.get("fbx") or {}).get("bytes")
                _existing_status = _existing_doc.get("status")
                if (
                    isinstance(_existing_sha, str)
                    and _existing_sha.strip().lower() == xodr_sha.lower()
                    and _existing_status == "ok"
                    and isinstance(_manifest_fbx_sha, str)
                    and _manifest_fbx_sha.strip()
                    and isinstance(_manifest_fbx_bytes, int)
                ):
                    # Verify FBX on disk still matches manifest (defends against
                    # FBX mutated without regenerating manifest)
                    try:
                        _actual_fbx_sha = _sha256(existing_fbx_path)
                        _actual_fbx_bytes = existing_fbx_path.stat().st_size
                        if _actual_fbx_sha.lower() == _manifest_fbx_sha.lower() and _actual_fbx_bytes == _manifest_fbx_bytes:
                            # Also buildings source must match (or be absent in old manifests)
                            _existing_buildings_sha = _existing_prov.get("buildings_source_sha256")
                            if _existing_buildings_sha is None or (isinstance(_existing_buildings_sha, str) and _existing_buildings_sha.strip().lower() == buildings_sha.lower()):
                                reuse_candidate = True
                    except (OSError, ValueError):
                        reuse_candidate = False
            except (json.JSONDecodeError, OSError, ValueError):
                reuse_candidate = False

        if reuse_candidate:
            print(f"[cook_grid]   -> reusing existing FBX (proven current: manifest SHA matches current XODR {xodr_sha[:16]}...)")
            # Construct a TileFbxResult-like dict from the existing manifest
            # so the summary/ checkpoint logic sees a consistent "ok" result
            # without invoking OSM2World/Blender.  We preserve the original
            # manifest's timing and roundtrip fields but override source_provenance
            # to the current run's provenance (they are equal by construction).
            _existing_doc = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
            _fbx_info = _existing_doc.get("fbx") or {}
            _rt = _existing_doc.get("roundtrip") or {}
            result_dict = {
                "status": _existing_doc.get("status", "ok"),
                "tile_index": list(_existing_doc.get("tile_index", [tx, ty])),
                "fbx_name": _existing_doc.get("fbx_name", f"{MAP_NAME}_Tile_{tx}_{ty}.fbx"),
                "reason": _existing_doc.get("reason", ""),
                "building_count": _existing_doc.get("clip", {}).get("buildings", n_bldgs),
                "osm_path": str(existing_tile_dir / f"{MAP_NAME}_Tile_{tx}_{ty}.osm"),
                "obj_path": str(existing_tile_dir / f"{MAP_NAME}_Tile_{tx}_{ty}.obj"),
                "fbx_path": str(existing_fbx_path),
                "fbx_bytes": _fbx_info.get("bytes", existing_fbx_path.stat().st_size),
                "fbx_sha256": _fbx_info.get("sha256", _sha256(existing_fbx_path)),
                "objects_total": _fbx_info.get("objects_total", 0),
                "vertices_total": _fbx_info.get("vertices_total", 0),
                "faces_total": _fbx_info.get("faces_total", 0),
                "roundtrip_ok": _rt.get("ok"),
                "roundtrip_verdict": _rt.get("verdict", ""),
                "osm2world_sec": _existing_doc.get("timing_sec", {}).get("osm2world", 0.0),
                "blender_sec": _existing_doc.get("timing_sec", {}).get("blender", 0.0),
                "roundtrip_sec": _existing_doc.get("timing_sec", {}).get("roundtrip", 0.0),
                "total_sec": _existing_doc.get("timing_sec", {}).get("total", 0.0),
                "manifest_path": str(existing_manifest_path),
                "semantic_classification": _existing_doc.get("semantic_classification", {}),
                "source_provenance": per_tile_source_prov,
                "reused_from_manifest": True,
            }
            # Append the reused dict directly (it is already in to_dict shape)
            all_results.append(result_dict)
            _write_checkpoint(
                checkpoint_path,
                run_id=run_id,
                completed=all_results,
                remaining=remaining,
                wall_elapsed_sec=time.time() - t_start,
            )
            if verbose:
                print(json.dumps(result_dict, indent=2))
            continue

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

    osm2world_home = _require_osm2world_home(
        args.osm2world_home, context="cook_full_grid_tiles"
    )
    return cook_all_tiles(
        osm2world_home=osm2world_home,
        blender_exe=args.blender_exe,
        report_dir=report_dir,
        artifacts_dir=artifacts_dir,
        run_roundtrip=not args.no_roundtrip,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    sys.exit(main())
