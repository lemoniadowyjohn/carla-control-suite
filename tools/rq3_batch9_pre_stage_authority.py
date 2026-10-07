#!/usr/bin/env python3
"""Batch 9 step 3/4: discover and verify the governed tile release.

Does NOT glob for FBX files. The expected tile set is resolved from the
governed release checkpoint (tiles_completed + the per-result tile_index
list), and every tile is then verified against that contract. Any tile
present on disk but absent from the contract is reported as a stray; any
contract tile absent from disk is reported as missing.

Writes PRE_STAGE_TILESET_AUTHORITY.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.tiling.large_map_package import parse_tile_fbx_filename

RELEASE_DIR = WORKTREE / "reports" / "production_readiness" / "20260924T100614Z_FULL_GRID_TILE_FBX_COOK"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _candidate_sha() -> str:
    return subprocess.run(
        ["git", "-C", str(WORKTREE), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="RQ3 pre-stage tileset authority")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--registry-key", default="auto_map_of_record")
    ap.add_argument("--release-dir", type=Path, default=RELEASE_DIR)
    args = ap.parse_args()

    release: Path = args.release_dir
    ckpt_path = release / "CHECKPOINT.json"
    out: Dict[str, Any] = {
        "schema": "rq3_pre_stage_tileset_authority/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_sha": _candidate_sha(),
        "source_output_directory": str(release.relative_to(WORKTREE)).replace("\\", "/"),
        "release_contract": {
            "checkpoint": str(ckpt_path.relative_to(WORKTREE)).replace("\\", "/"),
            "checkpoint_sha256": _sha256(ckpt_path),
            "run_id": None,
            "declared_tile_count": None,
            "declared_tiles": None,
        },
        "map_authority": {},
        "frame_authority": {},
        "placement_authority": {},
        "tiles": [],
        "stray_tiles": [],
        "missing_tiles": [],
        "duplicate_coordinates": [],
        "checks": {},
        "overall": "PASS",
    }

    def fail(msg: str) -> None:
        out["overall"] = "FAIL"
        out.setdefault("failures", []).append(msg)

    # --- map authority (registry-resolved, never glob/mtime) ---
    pinned = verify_pinned_map(args.registry_key)
    out["map_authority"] = {
        "registry_key": args.registry_key,
        "resolved_path": pinned["resolved_path"],
        "sha256_expected": pinned["sha256_expected"],
        "sha256_actual": pinned["sha256_actual"],
        "bytes": pinned.get("bytes"),
        "frame_id": pinned.get("frame_id"),
        "frame": pinned.get("frame"),
        "rebase_dx": pinned.get("rebase_dx"),
        "rebase_dy": pinned.get("rebase_dy"),
    }
    if pinned["sha256_expected"] != pinned["sha256_actual"]:
        fail("MAP_AUTHORITY_DRIFT: pinned XODR SHA256 does not match registry")
    out["frame_authority"] = {
        "frame_id": pinned.get("frame_id"),
        "rebase_offset_xy": [pinned.get("rebase_dx"), pinned.get("rebase_dy")],
    }
    out["placement_authority"] = {
        "status": "PENDING",
        "note": (
            "Placement authority is produced by stage_large_map_package and is "
            "checked downstream by RQ3 lineage validation "
            "(tiles_placement_offsets in the package sidecar). No placement "
            "record exists in the tile release itself."
        ),
    }

    ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
    declared = [tuple(r["tile_index"]) for r in ckpt["results"]]
    out["release_contract"]["run_id"] = ckpt.get("run_id")
    out["release_contract"]["declared_tile_count"] = ckpt.get("tiles_completed")
    out["release_contract"]["declared_tiles"] = [list(t) for t in sorted(declared)]
    out["release_contract"]["tiles_remaining"] = ckpt.get("tiles_remaining")

    seen: Dict[tuple, str] = {}
    for idx in sorted(declared):
        tx, ty = idx
        tdir = release / "artifacts" / f"tile_{tx}_{ty}"
        fbx = tdir / f"Ingolstadt_Tile_{tx}_{ty}.fbx"
        prov = tdir / f"Ingolstadt_Tile_{tx}_{ty}.fbx.provenance.json"
        tilef = tdir / f"Ingolstadt_Tile_{tx}_{ty}.tile_fbx.json"
        rec: Dict[str, Any] = {
            "tile_index": [tx, ty],
            "fbx_path": str(fbx.relative_to(WORKTREE)).replace("\\", "/"),
            "exists": fbx.is_file(),
            "provenance_path": str(prov.relative_to(WORKTREE)).replace("\\", "/"),
            "tile_manifest_path": str(tilef.relative_to(WORKTREE)).replace("\\", "/"),
            "problems": [],
        }
        if not fbx.is_file():
            rec["problems"].append("FBX_MISSING")
            out["missing_tiles"].append([tx, ty])
            fail(f"tile {tx},{ty}: FBX missing")
            out["tiles"].append(rec)
            continue

        rec["bytes"] = fbx.stat().st_size
        if rec["bytes"] == 0:
            rec["problems"].append("FBX_ZERO_BYTES")
            fail(f"tile {tx},{ty}: FBX is zero bytes")
        rec["fbx_sha256"] = _sha256(fbx)

        # governed CARLA naming, parsed by the governed parser
        parsed = parse_tile_fbx_filename(fbx.name)
        rec["parsed"] = list(parsed) if parsed else None
        if not parsed or parsed[1:] != (tx, ty):
            rec["problems"].append(f"TILE_NAME_PARSE_MISMATCH:{parsed}")
            fail(f"tile {tx},{ty}: filename does not parse to its own coordinate")
        if not fbx.name.startswith("Ingolstadt_Tile_"):
            rec["problems"].append("TILE_PREFIX_INVALID")
            fail(f"tile {tx},{ty}: unexpected tile filename prefix")

        key = (tx, ty)
        if key in seen:
            rec["problems"].append("DUPLICATE_COORDINATE")
            out["duplicate_coordinates"].append([tx, ty])
            fail(f"tile {tx},{ty}: duplicate coordinate")
        seen[key] = fbx.name

        # Map/frame/toolchain lineage lives in the per-tile .tile_fbx.json
        # (source_provenance). The .fbx.provenance.json is a Blender-side
        # conversion record and does not carry map lineage.
        if prov.is_file():
            rec["fbx_conversion_provenance_sha256"] = _sha256(prov)
            p = json.loads(prov.read_text(encoding="utf-8"))
            rec["blender_version"] = p.get("blender_version")
            rec["blender_exe_sha256"] = p.get("blender_exe_sha256")
            rec["conversion_script_sha256"] = p.get("conversion_script_sha256")
            rec["conversion_run_id"] = p.get("run_id")
            if p.get("artifact_sha256") != rec["fbx_sha256"]:
                rec["problems"].append("CONVERSION_PROVENANCE_FBX_SHA_MISMATCH")
                fail(f"tile {tx},{ty}: conversion provenance FBX SHA does not match file")
            if not (p.get("verification") or {}).get("output_hash_match", False):
                rec["problems"].append("CONVERSION_OUTPUT_HASH_UNVERIFIED")
                fail(f"tile {tx},{ty}: conversion provenance did not verify its own output hash")
        else:
            rec["problems"].append("FBX_CONVERSION_PROVENANCE_MISSING")

        if tilef.is_file():
            rec["tile_manifest_sha256"] = _sha256(tilef)
            t = json.loads(tilef.read_text(encoding="utf-8"))
            sp = t.get("source_provenance", {})
            rec["declared_map_of_record_sha256"] = sp.get("map_of_record_sha256")
            rec["declared_header_offset_xy"] = sp.get("header_offset_xy")
            rec["declared_buildings_source_sha256"] = sp.get("buildings_source_sha256")
            rec["declared_tile_size_m"] = sp.get("tile_size_m")
            rec["declared_osm2world_home"] = sp.get("osm2world_home")
            rec["tile_manifest_fbx_sha256"] = (t.get("fbx") or {}).get("sha256")
            rec["tile_manifest_status"] = t.get("status")
            rec["roundtrip_verdict"] = (t.get("roundtrip") or {}).get("verdict")
            rec["seam_strategy"] = t.get("seam_strategy")
            if (t.get("fbx") or {}).get("sha256") != rec["fbx_sha256"]:
                rec["problems"].append("TILE_MANIFEST_FBX_SHA_MISMATCH")
                fail(f"tile {tx},{ty}: per-tile manifest FBX SHA does not match file")
            if sp.get("map_of_record_sha256") != out["map_authority"]["sha256_actual"]:
                rec["problems"].append("TILE_MAP_LINEAGE_MISMATCH")
                fail(f"tile {tx},{ty}: declares a different map-of-record SHA")
            if sp.get("header_offset_xy") != [pinned.get("rebase_dx"), pinned.get("rebase_dy")]:
                rec["problems"].append("TILE_FRAME_OFFSET_MISMATCH")
                fail(f"tile {tx},{ty}: header offset differs from frame authority")
            if t.get("tile_index") != [tx, ty]:
                rec["problems"].append("TILE_MANIFEST_INDEX_MISMATCH")
                fail(f"tile {tx},{ty}: manifest declares a different tile index")
        else:
            rec["problems"].append("PER_TILE_MANIFEST_MISSING")

        out["tiles"].append(rec)

    # stray FBX on disk not named by the contract
    declared_names = {f"Ingolstadt_Tile_{x}_{y}.fbx" for x, y in declared}
    for f in sorted((release / "artifacts").rglob("*.fbx")):
        if f.name not in declared_names:
            out["stray_tiles"].append(
                str(f.relative_to(WORKTREE)).replace("\\", "/")
            )
    if out["stray_tiles"]:
        fail(f"{len(out['stray_tiles'])} stray FBX file(s) not named by the release contract")

    # all tiles must derive from one map SHA / frame / tile size / toolchain
    map_shas = {t.get("declared_map_of_record_sha256") for t in out["tiles"] if t.get("declared_map_of_record_sha256")}
    offsets = {tuple(t["declared_header_offset_xy"]) for t in out["tiles"] if t.get("declared_header_offset_xy")}
    sizes = {t.get("declared_tile_size_m") for t in out["tiles"] if t.get("declared_tile_size_m")}
    osm2world = {t.get("declared_osm2world_home") for t in out["tiles"] if t.get("declared_osm2world_home")}
    blenders = {t.get("blender_version") for t in out["tiles"] if t.get("blender_version")}
    conv_scripts = {t.get("conversion_script_sha256") for t in out["tiles"] if t.get("conversion_script_sha256")}
    buildings = {t.get("declared_buildings_source_sha256") for t in out["tiles"] if t.get("declared_buildings_source_sha256")}
    out["checks"] = {
        "tile_count_matches_contract": len(out["tiles"]) == len(declared),
        "no_missing_tiles": not out["missing_tiles"],
        "no_stray_tiles": not out["stray_tiles"],
        "no_duplicate_coordinates": not out["duplicate_coordinates"],
        "single_map_sha256": len(map_shas) == 1,
        "single_frame_offset": len(offsets) == 1,
        "single_tile_size_m": len(sizes) == 1,
        "single_osm2world_toolchain": len(osm2world) == 1,
        "single_blender_version": len(blenders) == 1,
        "single_conversion_script": len(conv_scripts) == 1,
        "single_buildings_source": len(buildings) == 1,
        "distinct_map_shas": sorted(map_shas),
        "distinct_frame_offsets": sorted([list(o) for o in offsets]),
        "distinct_tile_sizes_m": sorted(sizes),
        "distinct_osm2world_toolchains": sorted(osm2world),
        "distinct_blender_versions": sorted(blenders),
        "distinct_conversion_scripts": sorted(conv_scripts),
        "distinct_buildings_sources": sorted(buildings),
    }
    for key in ("tile_count_matches_contract", "no_missing_tiles", "no_stray_tiles",
                "no_duplicate_coordinates", "single_map_sha256",
                "single_frame_offset", "single_tile_size_m",
                "single_osm2world_toolchain", "single_blender_version",
                "single_conversion_script", "single_buildings_source"):
        if not out["checks"][key]:
            fail(f"campaign-coherence check failed: {key}")
    out["tile_count"] = len(out["tiles"])

    text = json.dumps(out, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(f"overall={out['overall']} tiles={out['tile_count']} failures={len(out.get('failures', []))}")
    return 0 if out["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())