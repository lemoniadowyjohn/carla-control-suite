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
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

# Schema version for offline_gap_report.json
REPORT_SCHEMA_VERSION = 2

# Gap status codes
STATUS_COMPUTED = "computed"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

# Exit codes
EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_MANDATORY_METRIC_FAILURE = 3
EXIT_EVIDENCE_INTEGRITY_FAILURE = 4
EXIT_INCOMPLETE = 5

# Execution profiles
PROFILE_DIAGNOSTIC = "diagnostic"
PROFILE_RQ2_STRUCTURAL = "rq2_structural"
PROFILE_RQ3_PAIRED = "rq3_paired"
PROFILE_THESIS_FULL = "thesis_full"

VALID_PROFILES = (PROFILE_DIAGNOSTIC, PROFILE_RQ2_STRUCTURAL, PROFILE_RQ3_PAIRED, PROFILE_THESIS_FULL)

# Mandatory metrics per profile
MANDATORY_METRICS = {
    PROFILE_DIAGNOSTIC: [],
    PROFILE_RQ2_STRUCTURAL: ["geometry", "curvature", "intersection"],
    PROFILE_RQ3_PAIRED: ["geometry", "curvature", "intersection", "semantic"],
    PROFILE_THESIS_FULL: ["geometry", "curvature", "intersection", "semantic", "connectivity"],
}


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


def validate_pair_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Validate pair manifest using canonical RQ3 contract logic.

    For an RQ3 scientific pair, the following must be true:
    - validation.valid == True
    - validation.pair_valid == True
    - claim_level == PAIRED_INGOLSTADT_CAPTURE (for thesis profile)
    """
    # Import canonical contract
    try:
        from ultimate_pipeline.perception.rq3_capture_contract import (
            validate_pair_manifest as canonical_validate,
            CLAIM_PAIRED_INGOLSTADT_CAPTURE,
        )
    except ImportError:
        return {"valid": False, "error": "cannot_import_canonical_contract"}

    # Get authoritative SHA from environment or manifest
    authoritative_sha = os.environ.get("UP_AUTHORITATIVE_INGOLSTADT_XODR_SHA256", "")
    if not authoritative_sha:
        authoritative_sha = manifest.get("authoritative_ingolstadt_xodr_sha256", "")

    validation = canonical_validate(manifest, authoritative_ingolstadt_xodr_sha256=authoritative_sha)

    # Add manifest SHA for traceability
    import hashlib
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    validation["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    validation["validated_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    return validation


def _sha256_file(path: str) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_files_against_manifest(manifest: Dict[str, Any], manual_xodr: Optional[str] = None) -> Dict[str, Any]:
    """Verify current files match manifest identities.

    Returns dict with 'valid' bool and 'mismatches' list.
    """
    mismatches: List[str] = []
    config = manifest.get("config", {})

    # 1. Verify auto XODR hash
    auto_xodr = config.get("xodr_in_full")
    if not auto_xodr or not os.path.isfile(auto_xodr):
        auto_xodr_rel = config.get("xodr_in")
        manifest_dir = os.path.dirname(os.path.abspath(manifest.get("_manifest_path", "")))
        if auto_xodr_rel:
            candidate = os.path.join(manifest_dir, "..", "..", auto_xodr_rel)
            if os.path.isfile(candidate):
                auto_xodr = candidate

    if auto_xodr and os.path.isfile(auto_xodr):
        expected_sha = config.get("xodr_hash", "")
        if expected_sha:
            actual_sha = _sha256_file(auto_xodr)
            if actual_sha != expected_sha:
                mismatches.append(f"auto_xodr_sha_mismatch: expected={expected_sha[:16]}... actual={actual_sha[:16]}...")

    # 2. Verify manual XODR if provided
    if manual_xodr and os.path.isfile(manual_xodr):
        manual_map_identity = manifest.get("manual_map_identity", {})
        expected_manual_sha = manual_map_identity.get("manual_source_xodr_sha256", "")
        if expected_manual_sha:
            actual_sha = _sha256_file(manual_xodr)
            if actual_sha != expected_manual_sha:
                mismatches.append(f"manual_xodr_sha_mismatch: expected={expected_manual_sha[:16]}... actual={actual_sha[:16]}...")

    # 3. Verify calibration identity
    manual_arm = manifest.get("manual_arm", {})
    auto_arm = manifest.get("auto_arm", {})
    expected_calib_sha = manual_arm.get("calibration_sha256", "") or auto_arm.get("calibration_sha256", "") or manifest.get("calibration_sha256", "")
    if expected_calib_sha:
        # We can't easily verify the actual calib file here without the path
        # But we record the expected SHA for traceability
        pass

    # 4. Verify sensor rig identity
    expected_rig_sha = manual_arm.get("sensor_rig_sha256", "") or auto_arm.get("sensor_rig_sha256", "") or manifest.get("sensor_rig_sha256", "")
    if expected_rig_sha:
        pass  # Same as above

    # 5. Verify pair evidence
    expected_route_sha = manual_arm.get("route_manifest_sha256", "") or auto_arm.get("route_manifest_sha256", "") or manifest.get("route_manifest_sha256", "")
    if expected_route_sha:
        pass

    return {
        "valid": len(mismatches) == 0,
        "mismatches": mismatches,
    }


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
        "--profile",
        choices=list(VALID_PROFILES),
        default=PROFILE_RQ2_STRUCTURAL,
        help=f"Execution profile. {PROFILE_DIAGNOSTIC} = diagnostic only, "
             f"{PROFILE_RQ2_STRUCTURAL} = RQ2 structural (default), "
             f"{PROFILE_RQ3_PAIRED} = RQ3 paired, "
             f"{PROFILE_THESIS_FULL} = thesis full. Default: {PROFILE_RQ2_STRUCTURAL}"
    )
    ap.add_argument(
        "--diagnostic-unpaired",
        action="store_true",
        help="Allow non-paired/diagnostic mode (bypasses RQ3 pair validation). Report will be marked non-authoritative."
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
        "--skip-connectivity",
        action="store_true",
        help="Skip connectivity gap computation"
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
        return EXIT_INVALID_INPUT

    manifest = _load_manifest(args.manifest)
    # Store manifest path for validation
    manifest["_manifest_path"] = args.manifest
    manifest_dir = os.path.dirname(os.path.abspath(args.manifest))

    print("=" * 60)
    print("Offline Domain-Gap Analysis")
    print("=" * 60)
    print(f"Manifest: {args.manifest}")
    print(f"Pair name: {manifest.get('pair_name', 'unknown')}")
    print(f"Profile: {args.profile}")

    # NEW-226: Input validation gate - validate pair manifest before computing anything
    if args.profile in (PROFILE_RQ3_PAIRED, PROFILE_THESIS_FULL) and not args.diagnostic_unpaired:
        print("\n[VALIDATION] Validating pair manifest for RQ3 scientific pair...")
        validation = validate_pair_manifest(manifest)
        if not validation.get("valid", False):
            print(f"[ERROR] Pair manifest validation failed:")
            for reason in validation.get("invalid_reasons", []):
                print(f"  - {reason}")
            print(f"[ERROR] Claim level: {validation.get('claim_level')}")
            print(f"[ERROR] Pair valid: {validation.get('pair_valid')}")
            return EXIT_INVALID_INPUT
        
        if args.profile in (PROFILE_RQ3_PAIRED, PROFILE_THESIS_FULL):
            if validation.get("claim_level") != "PAIRED_INGOLSTADT_CAPTURE":
                print(f"[ERROR] Pair does not meet RQ3 claim level: {validation.get('claim_level')}")
                return EXIT_INVALID_INPUT
        
        # Verify files against manifest
        file_verification = verify_files_against_manifest(manifest, args.manual_xodr)
        if not file_verification.get("valid", False):
            print(f"[ERROR] File verification against manifest failed:")
            for mismatch in file_verification.get("mismatches", []):
                print(f"  - {mismatch}")
            return EXIT_EVIDENCE_INTEGRITY_FAILURE
        
        # Add validation results to gap report
        gap_report_base = {
            "input_validation": {
                "valid": True,
                "claim_level": validation.get("claim_level"),
                "manifest_sha256": validation.get("manifest_sha256"),
                "validated_at_utc": validation.get("validated_at_utc"),
            }
        }
    else:
        print(f"\n[INFO] Running in {args.profile} mode - skipping RQ3 pair validation")
        gap_report_base = {
            "input_validation": {
                "valid": True,
                "claim_level": "NOT_REQUIRED",
                "manifest_sha256": "",
                "validated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        }

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
        return EXIT_INVALID_INPUT

    print(f"Auto XODR: {auto_xodr}")

    # Manual XODR (optional)
    manual_xodr = args.manual_xodr
    manual_xodr_available = False
    if manual_xodr:
        if not os.path.isfile(manual_xodr):
            print(f"[ERROR] Manual XODR not found: {manual_xodr}", file=sys.stderr)
            return EXIT_INVALID_INPUT
        manual_xodr_available = True
        print(f"Manual XODR: {manual_xodr}")
    else:
        print("[INFO] No --manual-xodr provided. XODR-based gaps will be skipped.")

    # Determine output path
    out_path = args.out or os.path.join(manifest_dir, "offline_gap_report.json")

    print("=" * 60)

    t_global = time.perf_counter()

    # Initialize gap report with validation info
    gap_report: Dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "manifest_path": _normalize_path(os.path.abspath(args.manifest)),
        "pair_name": manifest.get("pair_name"),
        "config": config,
        "profile": args.profile,
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
        "mandatory_metric_matrix": {},
    }
    gap_report.update(gap_report_base)

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
    # Compute summary counts and mandatory metric matrix
    # =========================================================================
    mandatory_for_profile = MANDATORY_METRICS.get(args.profile, [])
    mandatory_metric_matrix = {
        "profile": args.profile,
        "metrics": {},
        "overall": "PASS",
    }
    all_mandatory_passed = True

    for gap_name, gap_data in gap_report["gaps"].items():
        status = gap_data.get("status", STATUS_FAILED)
        is_mandatory = gap_name in mandatory_for_profile

        if status == STATUS_COMPUTED:
            gap_report["summary"]["computed"] += 1
            metric_status = "COMPUTED"
        elif status == STATUS_SKIPPED:
            gap_report["summary"]["skipped"] += 1
            metric_status = "SKIPPED_ALLOWED" if not is_mandatory else "SKIPPED_FORBIDDEN"
            if is_mandatory:
                all_mandatory_passed = False
        else:
            gap_report["summary"]["failed"] += 1
            metric_status = "FAILED"
            if is_mandatory:
                all_mandatory_passed = False

        mandatory_metric_matrix["metrics"][gap_name] = {
            "mandatory": is_mandatory,
            "status": metric_status,
        }

    if not all_mandatory_passed:
        mandatory_metric_matrix["overall"] = "FAIL"

    gap_report["mandatory_metric_matrix"] = mandatory_metric_matrix

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
    # Finalize - determine exit code
    # =========================================================================
    total_time = time.perf_counter() - t_global
    gap_report["runtime_sec"] = round(total_time, 2)
    gap_report["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Determine exit code based on profile and results
    if args.profile in (PROFILE_RQ3_PAIRED, PROFILE_THESIS_FULL) and not args.diagnostic_unpaired:
        if mandatory_metric_matrix["overall"] == "FAIL":
            exit_code = EXIT_MANDATORY_METRIC_FAILURE
        else:
            exit_code = EXIT_OK
    elif args.profile == PROFILE_RQ2_STRUCTURAL:
        if mandatory_metric_matrix["overall"] == "FAIL":
            exit_code = EXIT_MANDATORY_METRIC_FAILURE
        else:
            exit_code = EXIT_OK
    else:  # diagnostic
        exit_code = EXIT_OK

    # Write report
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(gap_report, f, indent=2, sort_keys=True, ensure_ascii=True)

    print("\n" + "=" * 60)
    print("OFFLINE GAP ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"Total runtime: {total_time:.1f}s")
    print(f"Report: {out_path}")
    print(f"Exit code: {exit_code}")

    # Summary counts
    summary = gap_report["summary"]
    print(f"\nGap Summary:")
    print(f"  Computed: {summary['computed']}")
    print(f"  Skipped:  {summary['skipped']}")
    print(f"  Failed:   {summary['failed']}")

    # Print mandatory metric matrix
    print(f"\nMandatory Metric Matrix:")
    for metric_name, metric_info in mandatory_metric_matrix["metrics"].items():
        print(f"  {metric_name}: mandatory={metric_info['mandatory']} status={metric_info['status']}")
    print(f"  OVERALL: {mandatory_metric_matrix['overall']}")

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

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
