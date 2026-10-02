#!/usr/bin/env python3
"""RQ1A: OSM→XODR Determinism Experiment.

Tests whether the OSM→XODR conversion (sanitization + optional SUMO repair)
produces byte-for-byte identical XODR output given the same OSM input.

This isolates the OSM→XODR stage from the rest of the pipeline, allowing
determinism testing of just the OSM→XODR conversion independent of
post-generation pipeline stages.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Set OSM_FILE env var BEFORE importing settings to override the default path
# Authoritative OSM for Ingolstadt campaign
AUTHORITATIVE_OSM = Path(__file__).resolve().parents[1] / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"
os.environ["UP_OSM_FILE"] = str(AUTHORITATIVE_OSM)

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))
os.chdir(str(WORKTREE))

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.osm.osm_to_xodr_wrapper import convert_osm_to_xodr, OSMToXODRConfig
from ultimate_pipeline.config.settings import Settings


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_osm_input(settings_obj: Settings, cache_dir: Path) -> Dict[str, Any]:
    """Resolve OSM input path (roads + buildings merge), mirroring main pipeline logic."""
    from ultimate_pipeline.enrichment.overpass_to_osm_xml import (
        convert_overpass_json_to_osm_xml,
        merge_osm_xml_files,
    )

    roads_path = str(getattr(settings_obj, "OSM_FILE", "") or "")
    result: Dict[str, Any] = {
        "osm_path": roads_path,
        "source": "roads_only",
        "buildings_source": None,
        "reason": "no pinned buildings source configured",
        "convert_stats": None,
        "merge_stats": None,
    }

    buildings_path = str(getattr(settings_obj, "PINNED_BUILDINGS_SOURCE", "") or "")
    if not buildings_path or not os.path.isfile(buildings_path):
        return result
    if not roads_path or not os.path.isfile(roads_path):
        result["reason"] = "roads OSM_FILE missing; nothing to merge buildings into"
        return result

    suffix = Path(buildings_path).suffix.lower()
    if suffix != ".json":
        result["reason"] = f"buildings source is not Overpass JSON (suffix={suffix!r}); skipping merge"
        return result

    try:
        os.makedirs(cache_dir, exist_ok=True)
        buildings_osm_path = cache_dir / "converted_buildings.osm"
        convert_stats = convert_overpass_json_to_osm_xml(buildings_path, str(buildings_osm_path))

        merged_osm_path = cache_dir / "merged_roads_and_buildings.osm"
        merge_stats = merge_osm_xml_files(roads_path, str(buildings_osm_path), str(merged_osm_path))

        return {
            "osm_path": str(merged_osm_path),
            "source": "merged",
            "buildings_source": buildings_path,
            "reason": (
                f"merged {convert_stats['ways_written']} building ways from "
                f"{os.path.basename(buildings_path)} into roads OSM"
            ),
            "convert_stats": convert_stats,
            "merge_stats": merge_stats,
        }
    except Exception as e:
        return {
            "osm_path": roads_path,
            "source": "roads_only",
            "buildings_source": None,
            "reason": f"buildings conversion/merge failed ({type(e).__name__}: {e}); falling back to roads_only",
            "convert_stats": None,
            "merge_stats": None,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="RQ1A: OSM→XODR Determinism Test")
    parser.add_argument("run_index", type=int, help="Run index (0-4 for 5-run matrix)")
    parser.add_argument("--output-base", type=Path, default=Path("reports/rq1a_runs"),
                        help="Base output directory")
    parser.add_argument("--runs", type=int, default=5, help="Number of runs (default 5)")
    parser.add_argument("--run-summo", action="store_true", help="Enable SUMO repair")
    args = parser.parse_args()

    # Load settings and verify pinned map
    from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
    pinned = verify_pinned_map("auto_map_of_record")
    assert pinned.get("verification_status") == "VERIFIED", pinned

    run_idx = args.run_index
    base = args.output_base
    base.mkdir(parents=True, exist_ok=True)

    # Create run-specific output directory
    run_dir = base / f"run_{args.run_index:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: Resolve OSM input (roads + buildings merge)
    cache_dir = Path(run_dir) / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    osm_result = _resolve_osm_input(SETTINGS, Path(run_dir) / "cache")
    osm_path = Path(osm_result["osm_path"])

    # Stage 2: OSM→XODR conversion
    output_xodr = run_dir / f"rq1a_generated_run_{args.run_index:02d}.xodr"

    t0 = time.time()
    cfg = OSMToXODRConfig(overwrite=True)
    convert_osm_to_xodr(
        osm_path=osm_result["osm_path"],
        xodr_path=output_xodr,
        cfg=cfg
    )
    duration = time.time() - t0

    output_xodr_path = output_xodr
    output_sha = _sha256(output_xodr)

    receipt = {
        "schema": "rq1a_run_receipt/v1",
        "run_index": args.run_index,
        "status": "ok",
        "duration_s": round(duration, 3),
        "input_osm_sha256": _sha256(Path(osm_result["osm_path"])),
        "output_xodr_sha256": _sha256(output_xodr),
        "osm_source": osm_result.get("source", "unknown"),
        "buildings_source": osm_result.get("buildings_source"),
        "run_summo": args.run_summo,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    out_file = run_dir / f"rq1a_receipt_run_{args.run_index:02d}.json"
    out_file.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"run": args.run_index, "output_sha": receipt["output_xodr_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())