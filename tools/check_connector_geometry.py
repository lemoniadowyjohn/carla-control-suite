from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import xml.etree.ElementTree as ET

# Worktree root must be on sys.path for direct invocation
# (`python tools/check_connector_geometry.py ...`) to import the package.
_WORKTREE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WORKTREE_ROOT not in sys.path:
    sys.path.insert(0, _WORKTREE_ROOT)

from ultimate_pipeline.quality.connector_geometry_validator import (
    OK, FLAGGED, UNVERIFIED, INVALID,
    analyze_geometry, g0_gap,
    analyze_all_junctions_full,
    INVALID as _INVALID,
)

TOOL_NAME = "connector_geometry_validator"
TOOL_VERSION = "1.0.0-o13"

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check_connector_geometry",
        description="Connector-geometry validator report (O13; report-only, no PASS verdict)",
    )
    parser.add_argument("--xodr", required=True, help="Path to .xodr file")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--samples", type=int, default=200,
                        help="Adaptive integration / sample count (default: 200)")
    parser.add_argument("--thresholds", type=str, default=None,
                        help="Thresholds JSON (optional; if absent threshold fields are 'unset')")
    parser.add_argument("--mode", choices=["per_geom", "junctions"],
                        default="per_geom",
                        help="Analysis mode: per_geom (Part A geometry invariants) or junctions (Part B+C laneLink analysis)")
    return parser.parse_args(argv)

def load_xodr(path: str) -> ET.Element:
    return ET.parse(path).getroot()

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    xodr_path = args.xodr
    root = load_xodr(xodr_path)
    sha = sha256_file(xodr_path)
    
    if args.mode == "junctions":
        return main_junctions(root, sha, args)
    else:
        return main_per_geom(root, sha, args)

def main_per_geom(root: ET.Element, sha: str, args: argparse.Namespace) -> int:
    report_items = []
    summary = {
        "total_roads": len(root.findall("road")),
        "roads_with_junction_neq_minus1": 0,
        "items": [],
    }

    # sha256 record
    report_items.append({
        "sha256": sha,
        "tool": TOOL_NAME,
        "version": TOOL_VERSION,
        "samples": args.samples,
    })

    # per-geometry analysis
    for road in root.findall("road"):
        try:
            plan = road.find("planView")
            if plan is None:
                continue
            geoms = plan.findall("geometry")
            if not geoms:
                continue
            rj = road.get("junction", "-1")
            if rj == "-1":
                for g in geoms:
                    res = analyze_geometry(g, samples=args.samples)
                    report_items.append({
                        "road_id": road.get("id", "?"),
                        "road_name": road.get("name", ""),
                        "geometry_index": geoms.index(g),
                        **{f"geom_{k}": v for k, v in res.items()},
                    })
                continue

            for g in geoms:
                res = analyze_geometry(g, samples=args.samples)
                report_items.append({
                    "road_id": road.get("id", "?"),
                    "road_name": road.get("name", ""),
                    "geometry_index": geoms.index(g),
                    **{f"geom_{k}": v for k, v in res.items()},
                })
            summary["roads_with_junction_neq_minus1"] += 1
        except Exception as e:
            report_items.append({
                "road_id": road.get("id", "?"),
                "road_name": road.get("name", ""),
                "status": _INVALID,
                "error": str(e),
            })

    # G0 gaps
    g0_items = []
    for road in root.findall("road"):
        try:
            plan = road.find("planView")
            if plan is None:
                continue
            geoms = plan.findall("geometry")
            for i in range(1, len(geoms)):
                gap = g0_gap(geoms[i - 1], geoms[i])
                gap_ok = gap is not None and not math.isnan(gap)
                g0_items.append({
                    "road_id": road.get("id", "?"),
                    "from_geom_index": i - 1,
                    "to_geom_index": i,
                    "g0_gap_m": gap if gap_ok else None,
                    "g0_status": "OK" if gap_ok else "UNVERIFIED",
                })
        except Exception:
            pass

    # output assembly
    output = {
        "tool": TOOL_NAME,
        "version": TOOL_VERSION,
        "samples": args.samples,
        "thresholds": args.thresholds if args.thresholds else "unset",
        "sha256": sha,
        "items": report_items,
        "g0_gaps": g0_items,
    }

    out_path = args.out
    out_path_parent = os.path.dirname(out_path)
    if out_path_parent:
        os.makedirs(out_path_parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    return 0


def main_junctions(root: ET.Element, sha: str, args: argparse.Namespace) -> int:
    # Junction mode: analyze all junctions and their laneLinks
    started = time.perf_counter()
    result = analyze_all_junctions_full(root)
    runtime_seconds = time.perf_counter() - started

    # output assembly
    output = {
        "tool": TOOL_NAME,
        "version": TOOL_VERSION,
        "samples": args.samples,
        "thresholds": args.thresholds if args.thresholds else "unset",
        "sha256": sha,
        "runtime_seconds": round(runtime_seconds, 3),
        "junctions": result["junctions"],
        "lane_links": result["lane_links"],
        "summary": result["summary"],
    }

    out_path = args.out
    out_path_parent = os.path.dirname(out_path)
    if out_path_parent:
        os.makedirs(out_path_parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as e:
        raise
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        sys.exit(1)