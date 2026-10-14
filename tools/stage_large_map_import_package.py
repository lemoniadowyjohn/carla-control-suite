#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage a CARLA Large-Map ``Import/<PackageName>/`` package from the pinned
map-of-record XODR plus whatever ``_Tile_<x>_<y>.fbx`` files have been
generated so far (e.g. by ``tools/probe_tile_fbx_densest.py`` or a future full
tile-generation run over ``ultimate_pipeline.tiling.tile_fbx_generator``).

This is the concrete driver for
``ultimate_pipeline.tiling.large_map_package`` (DESIGN.md §5 extension 3-4):
it closes the "make import / Import.py filename-matching + Import/<Package>/
staging" gap by producing the exact on-disk layout CARLA's asset-import
tooling scans for, and then runs the offline pre-cook validation gate against
what it staged. It does NOT invoke ``make import`` or any UE4/UE5 process --
that step is blocked on the separate UE4-build track documented in DESIGN.md.

Usage
-----
    python tools/stage_large_map_import_package.py \\
        --tile-fbx-glob "reports/production_readiness/*_TILE_BASED_FBX_GENERATION_PROBE/artifacts/*_Tile_*.fbx" \\
        --import-root Import

Defaults point at the pinned map-of-record XODR and package name "Ingolstadt"
so a bare invocation with just ``--tile-fbx-glob`` (or none, for an xodr-only
package) works out of the box.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.tiling.large_map_package import (  # noqa: E402
    stage_large_map_package,
    validate_staged_package,
)
from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map  # noqa: E402

# Resolve pin through the C13 registry instead of hardcoding — prevents
# stale path/sha256 when the map-of-record is re-promoted.
_pinned = verify_pinned_map("auto_map_of_record")
PINNED_XODR = Path(_pinned["path"])
PINNED_XODR_SHA256 = _pinned["sha256"]
MAP_NAME = "Ingolstadt"
TILE_SIZE_M = 1000.0


def _find_tile_fbx(glob_pattern: str) -> List[str]:
    if not glob_pattern:
        return []
    matches = sorted(str(p) for p in REPO_ROOT.glob(glob_pattern))
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xodr", default=None, help="whole-map XODR to stage (default: authoritative XODR via verify_pinned_map)")
    parser.add_argument("--expected-xodr-sha256", default=None,
                        help="refuse to stage if the xodr's sha256 does not match "
                             "(default: authoritative XODR SHA via verify_pinned_map; pass '' to skip the check)")
    parser.add_argument("--map-name", default=MAP_NAME)
    parser.add_argument("--package-name", default=None,
                        help="Import/<PackageName>/ directory name (default: --map-name)")
    parser.add_argument("--tile-size-m", type=float, default=TILE_SIZE_M)
    parser.add_argument("--tile-fbx-glob", action="append", default=[],
                        help="glob (relative to repo root) matching tile FBX files to "
                             "stage; may be passed multiple times")
    parser.add_argument("--tile-fbx", action="append", default=[],
                        help="explicit tile FBX path to stage; may be passed multiple times")
    parser.add_argument("--import-root", default=str(REPO_ROOT / "Import"))
    parser.add_argument("--no-carla-materials", action="store_true")
    args = parser.parse_args()

    # O1: Re-resolve authoritative XODR at execution time (not import-time
    # PINNED_XODR) so a stale import-time pin cannot survive a re-promotion.
    try:
        _fresh = verify_pinned_map("auto_map_of_record")
        _fresh_path = Path(_fresh["resolved_path"])
        _fresh_sha = _fresh["sha256"]
    except Exception as exc:
        print(f"[ERROR] failed to resolve authoritative XODR via verify_pinned_map: {exc}", file=sys.stderr)
        return 1

    # Determine XODR to stage: explicit --xodr overrides, otherwise authoritative
    xodr_to_stage = args.xodr if args.xodr is not None else str(_fresh_path)
    # Determine expected SHA: explicit --expected-xodr-sha256 overrides,
    # None means use authoritative (fresh), '' means skip check
    if args.expected_xodr_sha256 is None:
        expected_sha = _fresh_sha
    elif args.expected_xodr_sha256 == "":
        expected_sha = None
    else:
        expected_sha = args.expected_xodr_sha256

    tile_paths: List[str] = list(args.tile_fbx)
    for pattern in args.tile_fbx_glob:
        tile_paths.extend(_find_tile_fbx(pattern))
    # de-dupe, preserve order — O1 protection 2/8: never by mtime, only by
    # deterministic sort later in stage_large_map_package (tx,ty), stale
    # presence never influences selection except via fail-closed provenance.
    seen = set()
    deduped = []
    for p in tile_paths:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    tile_paths = deduped

    print(f"[stage] authoritative XODR: {_fresh_path} sha256={_fresh_sha[:16]}... (registry {_fresh.get('registry_sha256','')[:16]}...)")
    print(f"[stage] using xodr={xodr_to_stage} expected_sha={expected_sha[:16]+'...' if expected_sha else 'None (skip)'}")

    print(f"[stage] map_name={args.map_name!r} xodr={xodr_to_stage!r}")
    print(f"[stage] {len(tile_paths)} tile FBX candidate(s) found")
    for p in tile_paths:
        print(f"[stage]   - {p}")

    result = stage_large_map_package(
        map_name=args.map_name,
        xodr_path=xodr_to_stage,
        tile_fbx_paths=tile_paths,
        import_root=args.import_root,
        package_name=args.package_name,
        tile_size_m=args.tile_size_m,
        use_carla_materials=not args.no_carla_materials,
        expected_xodr_sha256=expected_sha,
    )

    print(f"[stage] status={result.status}")
    if result.status != "ok":
        print(f"[stage] FAILED: {result.reason}")
        return 2
    print(f"[stage] package_dir={result.package_dir}")
    print(f"[stage] staged {len(result.tiles_staged)} tile(s), "
          f"skipped {len(result.tiles_skipped_missing)} missing source(s)")
    if result.tiles_skipped_missing:
        for p in result.tiles_skipped_missing:
            print(f"[stage]   skipped (not found / bad name): {p}")

    validation = validate_staged_package(result.package_dir, expected_xodr_sha256=expected_sha)
    print(f"[validate] status={validation.status}")
    for f in validation.failures:
        print(f"[validate] FAILURE: {f}")
    for w in validation.warnings:
        print(f"[validate] warning: {w}")

    combined = {
        "stage": result.to_dict(),
        "validate": validation.to_dict(),
    }
    summary_path = Path(result.package_dir) / f"{result.package_name}.stage_and_validate.json"
    summary_path.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[stage] wrote {summary_path}")

    return 0 if validation.status == "PASS" else 3


if __name__ == "__main__":
    sys.exit(main())
