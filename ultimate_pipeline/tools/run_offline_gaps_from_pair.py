#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Offline domain-gap analysis from pair_manifest.json.

Reads the pair_manifest.json produced by run_perception_pair.py and computes
offline domain-gap metrics using the existing gap modules:
  - geometry_gap
  - curvature_gap
  - intersection_gap
  - semantic_gap (if available)

No CARLA required - pure offline analysis on XODR files.

Example:
  python -m ultimate_pipeline.tools.run_offline_gaps_from_pair \
    --manifest recordings/pairs/pair_Grid0821_20260111_120000/pair_manifest.json

  # With custom XODR for manual reference (optional):
  python -m ultimate_pipeline.tools.run_offline_gaps_from_pair \
    --manifest recordings/pairs/pair_Grid0821_20260111_120000/pair_manifest.json \
    --manual-xodr manual_maps/Grid0821.xodr
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

# Schema version for offline_gap_report.json
REPORT_SCHEMA_VERSION = 2

# Gap status codes
STATUS_COMPUTED = "computed"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


def _normalize_path(path: str) -> str:
    """Normalize path to forward slashes for consistent JSON output."""
    return path.replace("\\", "/")


def _load_manifest(manifest_path: str) -> Dict[str, Any]:
    """Load and validate pair_manifest.json."""
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "arms" not in data:
        raise ValueError("Invalid manifest: missing 'arms' key")
    if "config" not in data:
        raise ValueError("Invalid manifest: missing 'config' key")

    return data


def _find_meta_json(arm_dir: str) -> Optional[str]:
    """Find meta.json in arm directory."""
    for root, dirs, files in os.walk(arm_dir):
        if "meta.json" in files:
            return os.path.join(root, "meta.json")
    return None


def _truncate_error(error: str, max_len: int = 500) -> str:
    """Truncate error message deterministically."""
    if len(error) <= max_len:
        return error
    return error[:max_len] + "...[truncated]"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Compute offline domain-gap metrics from pair_manifest.json."
    )

    ap.add_argument(
        "--manifest",
        required=True,
        help="Path to pair_manifest.json produced by run_perception_pair.py"
    )
    ap.add_argument(
        "--manual-xodr",
        help="Optional: explicit path to manual map XODR for geometry comparison. "
             "If not provided, XODR-based gaps are skipped with clear status."
    )
    ap.add_argument(
        "--skip-hausdorff",
        action="store_true",
        help="Skip Hausdorff distance computation (faster)"
    )
    ap.add_argument(
        "--skip-geometry",
        action="store_true",
        help="Skip geometry gap computation"
    )
    ap.add_argument(
        "--skip-curvature",
        action="store_true",
        help="Skip curvature gap computation"
    )
    ap.add_argument(
        "--skip-intersection",
        action="store_true",
        help="Skip intersection gap computation"
    )
    ap.add_argument(
        "--skip-semantic",
        action="store_true",
        help="Skip semantic gap computation"
    )
    ap.add_argument(
        "--compute-composite",
        action="store_true",
        help="Compute composite domain-gap score"
    )
    ap.add_argument(
        "--out",
        help="Output JSON path. Default: same dir as manifest, offline_gap_report.json"
    )

    return ap.parse_args()


def _wrap_gap_result(
    gap_name: str,
    result: Dict[str, Any],
    *,
    skipped: bool = False,
    skip_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Wrap gap result with status field.
    Returns dict with: status, reason (if skipped), error (if failed), data (if computed).
    """
    if skipped:
        return {
            "status": STATUS_SKIPPED,
            "reason": skip_reason or "unknown",
        }

    if result.get("error") or result.get("disabled"):
        return {
            "status": STATUS_FAILED,
            "error": _truncate_error(str(result.get("error", result.get("reason", "unknown")))),
        }

    # Success - computed
    return {
        "status": STATUS_COMPUTED,
        "data": result,
    }


def compute_geometry_gap(
    manual_xodr: str,
    auto_xodr: str,
    *,
    skip_hausdorff: bool = False,
) -> Dict[str, Any]:
    """Compute geometry gap between two XODR files."""
    try:
        from ultimate_pipeline.domain_gap.geometry_gap import GeometryGap

        return GeometryGap.compute(
            manual_xodr,
            auto_xodr,
            skip_hausdorff=skip_hausdorff,
        )
    except Exception as e:
        return {"error": str(e), "disabled": True}


def compute_curvature_gap(
    manual_xodr: str,
    auto_xodr: str,
) -> Dict[str, Any]:
    """Compute curvature gap between two XODR files."""
    try:
        from ultimate_pipeline.domain_gap.curvature_gap import CurvatureGap

        return CurvatureGap.compute(manual_xodr, auto_xodr)
    except Exception as e:
        return {"error": str(e), "disabled": True}


def compute_intersection_gap(
    manual_xodr: str,
    auto_xodr: str,
) -> Dict[str, Any]:
    """Compute intersection gap between two XODR files."""
    try:
        from ultimate_pipeline.domain_gap.intersection_gap import IntersectionGap
        import xml.etree.ElementTree as ET

        manual_root = ET.parse(manual_xodr).getroot()
        auto_root = ET.parse(auto_xodr).getroot()

        manual_counts = IntersectionGap.count_types(manual_root)
        auto_counts = IntersectionGap.count_types(auto_root)

        # Compute deltas
        deltas = {}
        for itype in IntersectionGap.TYPES:
            deltas[itype] = auto_counts.get(itype, 0) - manual_counts.get(itype, 0)

        return {
            "manual_counts": manual_counts,
            "auto_counts": auto_counts,
            "deltas": deltas,
            "total_manual": sum(manual_counts.values()),
            "total_auto": sum(auto_counts.values()),
        }
    except Exception as e:
        return {"error": str(e), "disabled": True}


def compute_semantic_gap(
    manual_xodr: str,
    auto_xodr: str,
) -> Dict[str, Any]:
    """Compute semantic gap (object density, etc.) between two XODR files."""
    try:
        from ultimate_pipeline.domain_gap.semantic_gap import SemanticGap

        return SemanticGap.compute(manual_xodr, auto_xodr)
    except ImportError:
        return {"error": "SemanticGap module not available", "disabled": True}
    except Exception as e:
        return {"error": str(e), "disabled": True}


def main() -> int:
    args = parse_args()

    # Load manifest
    if not os.path.isfile(args.manifest):
        print(f"[ERROR] Manifest not found: {args.manifest}", file=sys.stderr)
        return 1

    manifest = _load_manifest(args.manifest)
    manifest_dir = os.path.dirname(os.path.abspath(args.manifest))

    print("=" * 60)
    print("Offline Domain-Gap Analysis")
    print("=" * 60)
    print(f"Manifest: {args.manifest}")
    print(f"Pair name: {manifest.get('pair_name', 'unknown')}")

    # Get paths from manifest
    config = manifest.get("config", {})

    # Auto XODR path
    auto_xodr = config.get("xodr_in_full")
    if not auto_xodr or not os.path.isfile(auto_xodr):
        # Try relative path
        auto_xodr_rel = config.get("xodr_in")
        if auto_xodr_rel:
            # Try relative to manifest dir
            candidate = os.path.join(manifest_dir, "..", "..", auto_xodr_rel)
            if os.path.isfile(candidate):
                auto_xodr = candidate

    if not auto_xodr or not os.path.isfile(auto_xodr):
        print(f"[ERROR] Auto XODR not found. Expected: {config.get('xodr_in_full')}", file=sys.stderr)
        return 1

    print(f"Auto XODR: {auto_xodr}")

    # Manual XODR (optional)
    manual_xodr = args.manual_xodr
    manual_xodr_available = False
    if manual_xodr:
        if not os.path.isfile(manual_xodr):
            print(f"[ERROR] Manual XODR not found: {manual_xodr}", file=sys.stderr)
            return 1
        manual_xodr_available = True
        print(f"Manual XODR: {manual_xodr}")
    else:
        print("[INFO] No --manual-xodr provided. XODR-based gaps will be skipped.")

    # Determine output path
    out_path = args.out or os.path.join(manifest_dir, "offline_gap_report.json")

    print("=" * 60)

    t_global = time.perf_counter()

    # Initialize gap report
    gap_report: Dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "manifest_path": _normalize_path(os.path.abspath(args.manifest)),
        "pair_name": manifest.get("pair_name"),
        "config": config,
        "manual_xodr_provided": manual_xodr_available,
        "manual_xodr_path": _normalize_path(manual_xodr) if manual_xodr else None,
        "auto_xodr_path": _normalize_path(auto_xodr),
        "gaps": {},
        "summary": {
            "computed": 0,
            "skipped": 0,
            "failed": 0,
        },
        "aggregated": None,
    }

    # =========================================================================
    # Geometry Gap
    # =========================================================================
    if args.skip_geometry:
        print("[SKIP] Geometry gap (--skip-geometry)")
        gap_report["gaps"]["geometry"] = _wrap_gap_result(
            "geometry", {}, skipped=True, skip_reason="cli_flag_skip_geometry"
        )
    elif not manual_xodr_available:
        print("[SKIP] Geometry gap (no --manual-xodr provided)")
        gap_report["gaps"]["geometry"] = _wrap_gap_result(
            "geometry", {}, skipped=True, skip_reason="manual_xodr_not_provided"
        )
    else:
        print("\n[GEOMETRY] Computing geometry gap...")
        result = compute_geometry_gap(
            manual_xodr,
            auto_xodr,
            skip_hausdorff=args.skip_hausdorff,
        )
        gap_report["gaps"]["geometry"] = _wrap_gap_result("geometry", result)

    # =========================================================================
    # Curvature Gap
    # =========================================================================
    if args.skip_curvature:
        print("[SKIP] Curvature gap (--skip-curvature)")
        gap_report["gaps"]["curvature"] = _wrap_gap_result(
            "curvature", {}, skipped=True, skip_reason="cli_flag_skip_curvature"
        )
    elif not manual_xodr_available:
        print("[SKIP] Curvature gap (no --manual-xodr provided)")
        gap_report["gaps"]["curvature"] = _wrap_gap_result(
            "curvature", {}, skipped=True, skip_reason="manual_xodr_not_provided"
        )
    else:
        print("\n[CURVATURE] Computing curvature gap...")
        result = compute_curvature_gap(manual_xodr, auto_xodr)
        gap_report["gaps"]["curvature"] = _wrap_gap_result("curvature", result)

    # =========================================================================
    # Intersection Gap
    # =========================================================================
    if args.skip_intersection:
        print("[SKIP] Intersection gap (--skip-intersection)")
        gap_report["gaps"]["intersection"] = _wrap_gap_result(
            "intersection", {}, skipped=True, skip_reason="cli_flag_skip_intersection"
        )
    elif not manual_xodr_available:
        print("[SKIP] Intersection gap (no --manual-xodr provided)")
        gap_report["gaps"]["intersection"] = _wrap_gap_result(
            "intersection", {}, skipped=True, skip_reason="manual_xodr_not_provided"
        )
    else:
        print("\n[INTERSECTION] Computing intersection gap...")
        result = compute_intersection_gap(manual_xodr, auto_xodr)
        gap_report["gaps"]["intersection"] = _wrap_gap_result("intersection", result)

    # =========================================================================
    # Semantic Gap
    # =========================================================================
    if args.skip_semantic:
        print("[SKIP] Semantic gap (--skip-semantic)")
        gap_report["gaps"]["semantic"] = _wrap_gap_result(
            "semantic", {}, skipped=True, skip_reason="cli_flag_skip_semantic"
        )
    elif not manual_xodr_available:
        print("[SKIP] Semantic gap (no --manual-xodr provided)")
        gap_report["gaps"]["semantic"] = _wrap_gap_result(
            "semantic", {}, skipped=True, skip_reason="manual_xodr_not_provided"
        )
    else:
        print("\n[SEMANTIC] Computing semantic gap...")
        result = compute_semantic_gap(manual_xodr, auto_xodr)
        gap_report["gaps"]["semantic"] = _wrap_gap_result("semantic", result)

    # =========================================================================
    # Compute summary counts
    # =========================================================================
    for gap_name, gap_data in gap_report["gaps"].items():
        status = gap_data.get("status", STATUS_FAILED)
        if status == STATUS_COMPUTED:
            gap_report["summary"]["computed"] += 1
        elif status == STATUS_SKIPPED:
            gap_report["summary"]["skipped"] += 1
        else:
            gap_report["summary"]["failed"] += 1

    # =========================================================================
    # Aggregation (optional)
    # =========================================================================
    if args.compute_composite:
        print("\n[AGGREGATE] Computing composite score...")
        try:
            from ultimate_pipeline.domain_gap.domain_gap_aggregator import DomainGapAggregator

            # Extract data from wrapped results
            geom_data = gap_report["gaps"].get("geometry", {}).get("data")
            curv_data = gap_report["gaps"].get("curvature", {}).get("data")
            inter_data = gap_report["gaps"].get("intersection", {}).get("data")
            sem_data = gap_report["gaps"].get("semantic", {}).get("data")

            gap_report["aggregated"] = DomainGapAggregator.aggregate(
                gap_geometry=geom_data,
                gap_curvature=curv_data,
                gap_intersection=inter_data,
                gap_semantic=sem_data,
                compute_composite=True,
            )
        except Exception as e:
            gap_report["aggregated"] = {"error": _truncate_error(str(e))}

    # =========================================================================
    # Finalize
    # =========================================================================
    total_time = time.perf_counter() - t_global
    gap_report["runtime_sec"] = round(total_time, 2)
    gap_report["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Write report
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(gap_report, f, indent=2, sort_keys=True, ensure_ascii=True)

    print("\n" + "=" * 60)
    print("OFFLINE GAP ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"Total runtime: {total_time:.1f}s")
    print(f"Report: {out_path}")

    # Summary counts
    summary = gap_report["summary"]
    print(f"\nGap Summary:")
    print(f"  Computed: {summary['computed']}")
    print(f"  Skipped:  {summary['skipped']}")
    print(f"  Failed:   {summary['failed']}")

    # Detailed results
    geom = gap_report["gaps"].get("geometry", {})
    curv = gap_report["gaps"].get("curvature", {})
    inter = gap_report["gaps"].get("intersection", {})

    if geom.get("status") == STATUS_COMPUTED:
        geom_data = geom.get("data", {})
        print(f"\nGeometry RMSE: {geom_data.get('rmse', 'N/A'):.3f} m")
        if geom_data.get("hausdorff") is not None:
            print(f"Geometry Hausdorff: {geom_data.get('hausdorff'):.3f} m")

    if curv.get("status") == STATUS_COMPUTED:
        curv_data = curv.get("data", {})
        print(f"\nCurvature KL divergence: {curv_data.get('kl_divergence', 'N/A')}")

    if inter.get("status") == STATUS_COMPUTED:
        inter_data = inter.get("data", {})
        print(f"\nIntersection counts (manual): {inter_data.get('total_manual', 'N/A')}")
        print(f"Intersection counts (auto): {inter_data.get('total_auto', 'N/A')}")

    if args.compute_composite and gap_report.get("aggregated"):
        aggregated = gap_report["aggregated"]
        if "error" not in aggregated:
            composite = aggregated.get("composite")
            if composite is not None:
                print(f"\nComposite score: {composite:.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
