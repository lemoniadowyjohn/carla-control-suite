#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Quarantine geometrically problematic roads based on thresholded metrics.
"""

from __future__ import annotations

import json
import math
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ultimate_pipeline.utils.file_hashing import safe_sha256_file


DEFAULT_THRESHOLDS = {
    "continuity_dxy_max_m": 1.0,
    "continuity_dhdg_max_deg": 10.0,
    "heading_jump_max_deg": 30.0,
    "curvature_abs_max": 0.5,
    "curvature_jump_max": 0.5,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _angle_diff_rad(a: float, b: float) -> float:
    diff = (a - b + math.pi) % (2.0 * math.pi) - math.pi
    return abs(diff)


def _road_ids(root: ET.Element) -> List[str]:
    ids = []
    for road in root.findall("road"):
        rid = str(road.get("id", "")).strip()
        if rid:
            ids.append(rid)
    return ids


def _parse_continuity_report(report: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    scores: Dict[str, Dict[str, Any]] = {}
    if not isinstance(report, dict):
        return scores
    issues = report.get("issues")
    if not isinstance(issues, list):
        return scores
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        for key in ("from_road", "to_road"):
            rid = str(issue.get(key, "")).strip()
            if not rid:
                continue
            entry = scores.setdefault(
                rid,
                {
                    "continuity_issue_count": 0,
                    "continuity_dxy_max_m": 0.0,
                    "continuity_dhdg_max_deg": 0.0,
                },
            )
            entry["continuity_issue_count"] += 1
            dxy = _safe_float(issue.get("dxy"), 0.0)
            dhdg = abs(_safe_float(issue.get("dhdg"), 0.0))
            entry["continuity_dxy_max_m"] = max(entry["continuity_dxy_max_m"], dxy)
            entry["continuity_dhdg_max_deg"] = max(entry["continuity_dhdg_max_deg"], dhdg)
    return scores


def _collect_geometry_metrics(root: ET.Element) -> Dict[str, Dict[str, Any]]:
    metrics: Dict[str, Dict[str, Any]] = {}
    for road in root.findall("road"):
        rid = str(road.get("id", "")).strip()
        if not rid:
            continue
        planview = road.find("planView")
        if planview is None:
            continue
        geometries = planview.findall("geometry")
        if not geometries:
            continue
        geometries_sorted = sorted(geometries, key=lambda g: _safe_float(g.get("s"), 0.0))
        prev_hdg: Optional[float] = None
        prev_curv: Optional[float] = None
        heading_jump_max_deg = 0.0
        curvature_jump_max = 0.0
        curvature_abs_max = 0.0
        for geom in geometries_sorted:
            hdg = _safe_float(geom.get("hdg"), 0.0)
            child = None
            for tag in ("arc", "spiral", "line"):
                child = geom.find(tag)
                if child is not None:
                    break
            if child is not None and child.tag == "arc":
                curvature = _safe_float(child.get("curvature"), 0.0)
            else:
                curvature = 0.0
            curvature_abs_max = max(curvature_abs_max, abs(curvature))
            if prev_hdg is not None:
                heading_jump_max_deg = max(
                    heading_jump_max_deg, math.degrees(_angle_diff_rad(hdg, prev_hdg))
                )
            if prev_curv is not None:
                curvature_jump_max = max(curvature_jump_max, abs(curvature - prev_curv))
            prev_hdg = hdg
            prev_curv = curvature
        metrics[rid] = {
            "heading_jump_max_deg": heading_jump_max_deg,
            "curvature_jump_max": curvature_jump_max,
            "curvature_abs_max": curvature_abs_max,
        }
    return metrics


def _merge_metrics(
    road_ids: Iterable[str],
    continuity: Dict[str, Dict[str, Any]],
    geometry: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for rid in road_ids:
        entry: Dict[str, Any] = {"road_id": rid}
        if rid in continuity:
            entry.update(continuity[rid])
        if rid in geometry:
            entry.update(geometry[rid])
        merged[rid] = entry
    return merged


def _score_and_reasons(entry: Dict[str, Any], thresholds: Dict[str, float]) -> Tuple[float, List[str]]:
    reasons: List[str] = []
    score = 0.0

    def _check(value: float, threshold_key: str, reason: str) -> None:
        nonlocal score
        threshold = float(thresholds.get(threshold_key, 0.0))
        if threshold <= 0:
            return
        if value > threshold:
            reasons.append(reason)
            score = max(score, value / threshold)

    _check(
        float(entry.get("continuity_dxy_max_m", 0.0)),
        "continuity_dxy_max_m",
        "continuity_dxy",
    )
    _check(
        float(entry.get("continuity_dhdg_max_deg", 0.0)),
        "continuity_dhdg_max_deg",
        "continuity_dhdg",
    )
    _check(
        float(entry.get("heading_jump_max_deg", 0.0)),
        "heading_jump_max_deg",
        "heading_jump",
    )
    _check(
        float(entry.get("curvature_jump_max", 0.0)),
        "curvature_jump_max",
        "curvature_jump",
    )
    _check(
        float(entry.get("curvature_abs_max", 0.0)),
        "curvature_abs_max",
        "curvature_abs",
    )
    return score, reasons


def quarantine_bad_roads(
    xodr_in: str,
    out_xodr: str,
    *,
    continuity_report: Optional[Dict[str, Any]] = None,
    max_fraction: float = 0.01,
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Remove the worst offending roads from the XODR based on thresholds.
    """
    thresholds = dict(DEFAULT_THRESHOLDS) if thresholds is None else {**DEFAULT_THRESHOLDS, **thresholds}

    tree = ET.parse(xodr_in)
    root = tree.getroot()

    road_ids = sorted(_road_ids(root))
    continuity = _parse_continuity_report(continuity_report)
    geometry_metrics = _collect_geometry_metrics(root)
    merged = _merge_metrics(road_ids, continuity, geometry_metrics)

    candidates: List[Dict[str, Any]] = []
    for rid in road_ids:
        entry = merged[rid]
        score, reasons = _score_and_reasons(entry, thresholds)
        if reasons:
            entry = dict(entry)
            entry["score"] = score
            entry["reasons"] = sorted(set(reasons))
            candidates.append(entry)

    candidates.sort(key=lambda e: (-float(e.get("score", 0.0)), str(e.get("road_id", ""))))

    total_roads = len(road_ids)
    max_remove = int(math.floor(total_roads * float(max_fraction))) if total_roads > 0 else 0
    if max_remove <= 0 and candidates:
        max_remove = 1
    to_remove = candidates[: max_remove if max_remove > 0 else 0]
    remove_ids = {entry["road_id"] for entry in to_remove}

    for road in list(root.findall("road")):
        rid = str(road.get("id", "")).strip()
        if rid in remove_ids:
            root.remove(road)

    tree.write(out_xodr, encoding="utf-8", xml_declaration=True)

    input_hash = safe_sha256_file(xodr_in) if os.path.exists(xodr_in) else ""
    output_hash = safe_sha256_file(out_xodr) if os.path.exists(out_xodr) else ""

    per_road_metrics = {entry["road_id"]: entry for entry in to_remove}
    fraction = float(len(remove_ids)) / float(total_roads) if total_roads else 0.0
    report = {
        "ok": True,
        "status": "applied" if remove_ids else "no_roads_removed",
        "road_ids_quarantined": sorted(remove_ids),
        "count_removed": len(remove_ids),
        "fraction_removed": fraction,
        "total_roads": total_roads,
        "thresholds": thresholds,
        "per_road_metrics": per_road_metrics,
        "input_xodr": xodr_in,
        "output_xodr": out_xodr,
        "input_xodr_sha256": input_hash,
        "output_xodr_sha256": output_hash,
    }
    return report


def write_quarantine_report(path: str, report: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True, ensure_ascii=True)
