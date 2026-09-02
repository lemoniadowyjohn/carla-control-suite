#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone acceptance measurement for a generated candidate XODR.

Runs the corrected quality gates (C6/C9/C10) directly against a candidate
file, writes the per-gate reports to --out-dir, and produces the same
map_acceptance payload the pipeline would emit (build_map_acceptance).

Usage:
    python scripts/measure_candidate_acceptance.py <candidate.xodr> --out-dir <dir> [--dem <dem.tif>] [--require-enrichment]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ultimate_pipeline.quality.check_geometric_continuity import check_geometric_continuity
from ultimate_pipeline.quality.check_lane_link_targets_exist import check_lane_link_targets_exist
from ultimate_pipeline.quality.check_lane_section_successors import (
    repair_and_assert_lane_section_successors,
)
from ultimate_pipeline.quality.check_elevation_seams import check_elevation_seams
from ultimate_pipeline.quality.check_elevation_continuity import check_elevation_continuity
from ultimate_pipeline.quality.check_dem_full_coverage import check_dem_full_coverage
from ultimate_pipeline.quality.check_origin_sanity import check_origin_sanity
from ultimate_pipeline.quality.check_junction_integrity import JunctionIntegrityGate
from ultimate_pipeline.diagnostics.elevation_summary import summarize_elevation
from ultimate_pipeline.quality.map_acceptance import (
    build_map_acceptance,
    component_reachability_summary,
)
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEM = REPO_ROOT / "cities" / "ingolstadt" / "dem" / "dem_ing.tif"


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")


def run_gates(xodr: Path, out_dir: Path, dem: Optional[Path]) -> Dict[str, Any]:
    reports: Dict[str, Any] = {}

    rep = check_geometric_continuity(str(xodr), eps_xy=0.05, eps_hdg=0.01)
    reports["geometric_continuity"] = rep
    _write_json(out_dir / "geometric_continuity.json", rep)
    print(f"[gate] geometric_continuity: ok={rep.get('ok')} broken={rep.get('broken_count', rep.get('still_broken_count', '?'))}")

    rep = check_lane_link_targets_exist(str(xodr), allow_dead_ends=True)
    reports["lane_connectivity"] = rep
    _write_json(out_dir / "lane_link_target_report.json", rep)
    print(f"[gate] lane_connectivity: ok={rep.get('ok')} broken={rep.get('still_broken_count', rep.get('num_issues', '?'))}")

    rep = repair_and_assert_lane_section_successors(str(xodr), out_path=None, strict=True)
    reports["lane_section_successors"] = rep
    _write_json(out_dir / "lane_section_successors.json", rep)
    print(f"[gate] lane_section_successors: ok={rep.get('ok')} broken={rep.get('still_broken_count', rep.get('num_issues', '?'))}")

    rep = check_elevation_seams(str(xodr))
    reports["elevation_seams"] = rep
    _write_json(out_dir / "elevation_seam_report.json", rep)
    print(f"[gate] elevation_seams: ok={rep.get('ok')}")

    rep = check_elevation_continuity(str(xodr), eps_z=0.5)
    _write_json(out_dir / "elevation_continuity.json", rep)
    print(f"[gate] elevation_continuity (info): ok={rep.get('ok')}")

    rep = check_origin_sanity(str(xodr))
    reports["origin_sanity"] = rep
    _write_json(out_dir / "origin_sanity.json", rep)
    print(f"[gate] origin_sanity: ok={rep.get('ok')} centroid_dist_m={rep.get('centroid_distance_m')}")

    rep = JunctionIntegrityGate.validate(str(xodr))
    reports["junction_integrity"] = rep
    _write_json(out_dir / "junction_integrity.json", rep)
    print(f"[gate] junction_integrity: ok={rep.get('ok')} issue_count={rep.get('issue_count')}")

    if dem is not None and dem.is_file():
        rep = check_dem_full_coverage(str(xodr), str(dem), str(out_dir / "dem_coverage.json"))
        reports["dem_coverage"] = rep
        print(f"[gate] dem_coverage: ok={rep.get('ok')} valid_ratio={rep.get('valid_ratio')}")
    else:
        print(f"[gate] dem_coverage: SKIPPED (dem not found at {dem})")

    try:
        elev_summary = summarize_elevation(str(xodr))
        _write_json(out_dir / "elevation_summary.json", elev_summary)
        print(f"[info] elevation_summary: min={elev_summary.get('min')} max={elev_summary.get('max')} segments={elev_summary.get('elevation_segment_count')} roads={elev_summary.get('road_count')}")
    except Exception as exc:  # noqa: BLE001
        print(f"[info] elevation_summary failed: {exc}")

    try:
        comp_root = ET.parse(str(xodr)).getroot()
        comp_rep = component_reachability_summary(comp_root)
        if comp_rep is not None:
            reports["component_reachability"] = comp_rep
            _write_json(out_dir / "component_reachability.json", comp_rep)
            print(f"[gate] component_reachability: components={comp_rep.get('component_count')} largest_fraction={comp_rep.get('largest_component_fraction')} isolated={comp_rep.get('isolated_lane_component_count')}")
    except Exception as exc:  # noqa: BLE001
        print(f"[info] component_reachability failed: {exc}")

    return reports


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure corrected acceptance gates for a candidate XODR.")
    ap.add_argument("xodr", type=Path, help="Candidate OpenDRIVE file to measure")
    ap.add_argument("--out-dir", type=Path, default=None, help="Where to write gate reports (default: <xodr>_acceptance_<ts>)")
    ap.add_argument("--dem", type=Path, default=DEFAULT_DEM, help="DEM GeoTIFF (default: campaign dem)")
    ap.add_argument("--require-enrichment", action="store_true", help="Hard-fail acceptance on empty buildings/signals")
    ap.add_argument(
        "--require-component-reachability",
        action="store_true",
        help="Hard-fail acceptance if >5% of lanes are off the main drivable component",
    )
    args = ap.parse_args()

    xodr = args.xodr.expanduser().resolve()
    if not xodr.is_file():
        print(f"ERROR: candidate not found: {xodr}", file=sys.stderr)
        return 2

    out_dir = args.out_dir or xodr.parent / f"{xodr.stem}_acceptance_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}"
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"candidate: {xodr} ({xodr.stat().st_size / 1e6:.1f} MB)")
    reports = run_gates(xodr, out_dir, args.dem)

    acceptance = build_map_acceptance(
        reports,
        run_id=xodr.stem,
        final_xodr_path=str(xodr),
        out_dir=str(out_dir),
        require_enrichment=args.require_enrichment,
        require_component_reachability=args.require_component_reachability,
    )
    _write_json(out_dir / "map_acceptance.json", acceptance)

    print("\n=== MAP ACCEPTANCE ===")
    print(f"valid_for_experiments: {acceptance['valid_for_experiments']}")
    for gate in acceptance.get("hard_fail_reasons", []):
        print(f"  FAIL {gate['gate']}: {gate['reason']}")
    for warn in acceptance.get("soft_warnings", []):
        print(f"  WARN {warn['gate']}: {warn['reason']}")
    for key, value in sorted(acceptance.get("metrics", {}).items()):
        print(f"  metric {key}: {value}")
    print(f"sha256: {acceptance.get('final_xodr_sha256')}")
    print(f"reports written to: {out_dir}")
    return 0 if acceptance["valid_for_experiments"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
