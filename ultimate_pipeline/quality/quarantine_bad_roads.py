#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Quarantine the worst geometric continuity offenders by removing road elements.
"""

from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple

from ultimate_pipeline.artifacts.map_event_record import append_event, build_record


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _road_scores(continuity_report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    scores: Dict[str, Dict[str, Any]] = {}
    issues = continuity_report.get("issues") if isinstance(continuity_report, dict) else None
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
                {"road_id": rid, "issue_count": 0, "dxy_max": 0.0, "dhdg_max": 0.0},
            )
            entry["issue_count"] += 1
            dxy = _safe_float(issue.get("dxy"), 0.0)
            dhdg = abs(_safe_float(issue.get("dhdg"), 0.0))
            entry["dxy_max"] = max(entry["dxy_max"], dxy)
            entry["dhdg_max"] = max(entry["dhdg_max"], dhdg)

    for entry in scores.values():
        entry["score"] = max(float(entry["dxy_max"]), float(entry["dhdg_max"]))

    return scores


def _sorted_roads(scores: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = list(scores.values())
    ordered.sort(
        key=lambda r: (float(r.get("score", 0.0)), float(r.get("dxy_max", 0.0)), r.get("issue_count", 0)),
        reverse=True,
    )
    return ordered


def quarantine_bad_roads(
    xodr_in: str,
    continuity_report: dict,
    out_xodr: str,
    max_fraction: float = 0.01,
) -> dict:
    """
    Remove the worst continuity offenders from the XODR.

    Returns:
        {
            "removed_road_ids": [...],
            "count": int,
            "fraction": float,
            "total_roads": int,
            "per_road_metrics": {road_id: {...}}
        }
    """
    scores = _road_scores(continuity_report)
    ordered = _sorted_roads(scores)

    total_roads = int(continuity_report.get("num_roads") or 0)
    if total_roads <= 0:
        try:
            tree = ET.parse(xodr_in)
            root = tree.getroot()
            total_roads = len(root.findall("road"))
        except Exception:
            total_roads = 0

    if max_fraction <= 0 or total_roads <= 0 or not ordered:
        return {
            "removed_road_ids": [],
            "count": 0,
            "fraction": 0.0,
            "total_roads": total_roads,
            "per_road_metrics": {},
        }

    max_remove = int(math.floor(total_roads * float(max_fraction)))
    if max_remove <= 0:
        max_remove = 1
    max_remove = min(max_remove, len(ordered))

    to_remove = ordered[:max_remove]
    remove_ids = [r["road_id"] for r in to_remove]

    tree = ET.parse(xodr_in)
    root = tree.getroot()
    road_lengths = {
        str(road.get("id", "")).strip(): _safe_float(road.get("length"), 0.0)
        for road in root.findall("road")
    }

    removed = []
    for road in list(root.findall("road")):
        rid = (road.get("id") or "").strip()
        if rid in remove_ids:
            root.remove(road)
            removed.append(rid)

    tree.write(out_xodr, encoding="utf-8", xml_declaration=True)

    out_dir = os.path.dirname(out_xodr)
    for rid in removed:
        road_len = road_lengths.get(rid, 0.0)
        record = build_record(
            out_dir=out_dir,
            final_xodr_path=out_xodr,
            stage_name="quarantine_bad_roads",
            gate_name="quarantine_bad_roads",
            event_type="remove",
            road_id=rid,
            lane_section_id=None,
            lane_id=None,
            junction_id=None,
            s_from=0.0,
            s_to=road_len if road_len > 0 else None,
            removed_length_m=road_len if road_len > 0 else None,
            removed_length_pct=1.0 if road_len > 0 else None,
        )
        append_event(out_dir, record)

    per_road_metrics = {r["road_id"]: r for r in to_remove}
    fraction = float(len(removed)) / float(total_roads) if total_roads > 0 else 0.0
    return {
        "removed_road_ids": removed,
        "count": len(removed),
        "fraction": fraction,
        "total_roads": total_roads,
        "per_road_metrics": per_road_metrics,
    }
