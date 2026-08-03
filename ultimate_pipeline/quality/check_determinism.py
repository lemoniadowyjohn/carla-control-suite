# ultimate_pipeline/quality/check_determinism.py
# -*- coding: utf-8 -*-

"""
Determinism check for OpenDRIVE pipeline outputs.

Why:
- Scientific reproducibility requires deterministic outputs.
- Same input + seed should produce identical structural results.

What it checks:
- Hash structural elements (road count, junction count, lane count)
- Compare two runs with same seed
- Warn if results differ (no hard failure yet)

Outputs:
- A dict report with ok, hashes, comparison results.
"""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional


def _safe_float(x: Optional[str], default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except Exception:
        return default


def compute_structural_hash(xodr_path: str) -> Dict[str, Any]:
    """
    Compute a structural hash of an OpenDRIVE file.

    This hash captures structural elements that should be deterministic:
    - Road count
    - Junction count
    - Lane count (per road)
    - Total geometry segments
    - Aggregate road length

    Parameters
    ----------
    xodr_path : str
        Path to the OpenDRIVE file.

    Returns
    -------
    dict
        {
            "hash": str,  # SHA256 of structural fingerprint
            "road_count": int,
            "junction_count": int,
            "total_lane_count": int,
            "geometry_segment_count": int,
            "total_road_length": float,
            "road_ids": [str],  # sorted
            "junction_ids": [str],  # sorted
        }
    """
    result: Dict[str, Any] = {
        "hash": "",
        "road_count": 0,
        "junction_count": 0,
        "total_lane_count": 0,
        "geometry_segment_count": 0,
        "total_road_length": 0.0,
        "road_ids": [],
        "junction_ids": [],
        "error": None,
    }

    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as e:
        result["error"] = str(e)
        return result

    roads = root.findall("road")
    junctions = root.findall("junction")

    result["road_count"] = len(roads)
    result["junction_count"] = len(junctions)

    road_ids: List[str] = []
    junction_ids: List[str] = []
    total_lanes = 0
    total_geom_segments = 0
    total_length = 0.0

    for road in roads:
        rid = (road.get("id") or "").strip()
        if rid:
            road_ids.append(rid)

        total_length += _safe_float(road.get("length"))

        # Count geometry segments
        plan_view = road.find("planView")
        if plan_view is not None:
            total_geom_segments += len(plan_view.findall("geometry"))

        # Count lanes
        lanes_elem = road.find("lanes")
        if lanes_elem is not None:
            for lane_section in lanes_elem.findall("laneSection"):
                for side in ("left", "center", "right"):
                    side_elem = lane_section.find(side)
                    if side_elem is not None:
                        total_lanes += len(side_elem.findall("lane"))

    for junction in junctions:
        jid = (junction.get("id") or "").strip()
        if jid:
            junction_ids.append(jid)

    result["road_ids"] = sorted(road_ids)
    result["junction_ids"] = sorted(junction_ids)
    result["total_lane_count"] = total_lanes
    result["geometry_segment_count"] = total_geom_segments
    result["total_road_length"] = round(total_length, 2)

    # Compute hash of structural fingerprint
    fingerprint = {
        "road_count": result["road_count"],
        "junction_count": result["junction_count"],
        "total_lane_count": result["total_lane_count"],
        "geometry_segment_count": result["geometry_segment_count"],
        "total_road_length": result["total_road_length"],
        "road_ids": result["road_ids"],
        "junction_ids": result["junction_ids"],
    }

    fingerprint_str = json.dumps(fingerprint, sort_keys=True)
    result["hash"] = hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]

    return result


def check_determinism(
    xodr_path_a: str,
    xodr_path_b: str,
    stage: str = "determinism_check",
) -> Dict[str, Any]:
    """
    Compare two OpenDRIVE files for structural determinism.

    Parameters
    ----------
    xodr_path_a : str
        Path to first OpenDRIVE file.
    xodr_path_b : str
        Path to second OpenDRIVE file.
    stage : str
        Stage name for reporting.

    Returns
    -------
    dict
        {
            "ok": bool,
            "stage": str,
            "deterministic": bool,
            "hash_a": str,
            "hash_b": str,
            "differences": {...},
            "warnings": [str]
        }
    """
    report: Dict[str, Any] = {
        "ok": True,  # Warning only, not failure
        "stage": stage,
        "deterministic": False,
        "hash_a": "",
        "hash_b": "",
        "stats_a": {},
        "stats_b": {},
        "differences": {},
        "warnings": [],
    }

    hash_a = compute_structural_hash(xodr_path_a)
    hash_b = compute_structural_hash(xodr_path_b)

    if hash_a.get("error"):
        report["warnings"].append(f"Failed to hash file A: {hash_a['error']}")
        return report

    if hash_b.get("error"):
        report["warnings"].append(f"Failed to hash file B: {hash_b['error']}")
        return report

    report["hash_a"] = hash_a["hash"]
    report["hash_b"] = hash_b["hash"]
    report["stats_a"] = {k: v for k, v in hash_a.items() if k not in ("hash", "error", "road_ids", "junction_ids")}
    report["stats_b"] = {k: v for k, v in hash_b.items() if k not in ("hash", "error", "road_ids", "junction_ids")}

    # Compare
    if hash_a["hash"] == hash_b["hash"]:
        report["deterministic"] = True
    else:
        report["deterministic"] = False
        # Find specific differences
        diffs: Dict[str, Any] = {}

        for key in ("road_count", "junction_count", "total_lane_count", "geometry_segment_count"):
            if hash_a[key] != hash_b[key]:
                diffs[key] = {"a": hash_a[key], "b": hash_b[key]}

        if abs(hash_a["total_road_length"] - hash_b["total_road_length"]) > 0.1:
            diffs["total_road_length"] = {"a": hash_a["total_road_length"], "b": hash_b["total_road_length"]}

        # Check for missing/extra roads
        roads_a = set(hash_a["road_ids"])
        roads_b = set(hash_b["road_ids"])
        if roads_a != roads_b:
            diffs["road_ids_only_in_a"] = sorted(roads_a - roads_b)[:10]  # Limit output
            diffs["road_ids_only_in_b"] = sorted(roads_b - roads_a)[:10]

        report["differences"] = diffs
        report["warnings"].append("Non-deterministic output detected - results differ between runs")

    return report


def check_determinism_single(
    xodr_path: str,
    expected_hash: Optional[str] = None,
    stage: str = "determinism_check",
) -> Dict[str, Any]:
    """
    Compute structural hash for a single file and optionally compare to expected.

    Parameters
    ----------
    xodr_path : str
        Path to OpenDRIVE file.
    expected_hash : str, optional
        Expected hash to compare against.
    stage : str
        Stage name for reporting.

    Returns
    -------
    dict
        {
            "ok": bool,
            "stage": str,
            "hash": str,
            "stats": {...},
            "matches_expected": bool or None,
            "warnings": [str]
        }
    """
    report: Dict[str, Any] = {
        "ok": True,
        "stage": stage,
        "hash": "",
        "stats": {},
        "matches_expected": None,
        "warnings": [],
    }

    hash_result = compute_structural_hash(xodr_path)

    if hash_result.get("error"):
        report["ok"] = False
        report["warnings"].append(f"Failed to compute hash: {hash_result['error']}")
        return report

    report["hash"] = hash_result["hash"]
    report["stats"] = {
        "road_count": hash_result["road_count"],
        "junction_count": hash_result["junction_count"],
        "total_lane_count": hash_result["total_lane_count"],
        "geometry_segment_count": hash_result["geometry_segment_count"],
        "total_road_length": hash_result["total_road_length"],
    }

    if expected_hash is not None:
        report["matches_expected"] = (hash_result["hash"] == expected_hash)
        if not report["matches_expected"]:
            report["warnings"].append(
                f"Hash mismatch: expected {expected_hash}, got {hash_result['hash']}"
            )

    return report


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Check OpenDRIVE determinism")
    ap.add_argument("xodr_path", help="Path to OpenDRIVE file")
    ap.add_argument("--compare", help="Second file to compare against")
    ap.add_argument("--expected-hash", help="Expected hash value")
    args = ap.parse_args()

    if args.compare:
        rep = check_determinism(args.xodr_path, args.compare)
    else:
        rep = check_determinism_single(args.xodr_path, expected_hash=args.expected_hash)

    print(json.dumps(rep, indent=2))
    sys.exit(0 if rep.get("ok", False) else 2)
