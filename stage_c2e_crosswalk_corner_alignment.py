#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 Step C - crosswalk corner alignment residuals (C2E).

For each of the 66 authored crosswalk objects, decode the <outline>
<cornerLocal u v z> corners back to world (CARLA 0.9.16 GetAllCrosswalkZones
codec via crosswalk_schema.carla_world_corners, exactly the inverse of the
S07 authoring encoder), then measure the distance of each decoded corner to
the nearest XODR road reference line in the promoted governed payload
(EPSG:32632 native frame).  Reports mean/median/P95/P99/max across corners
and the worst objects (outlier road IDs).
"""
from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))

from ultimate_pipeline.enrichment.crosswalk_schema import (
    carla_world_corners,
    reference_pose_at_s,
)
from ultimate_pipeline.enrichment.structure_classifier import road_centerline_polyline

C2 = REPO / "reports" / "post_audit_hardening" / "20260809T000000Z_C2_3DPACKAGE"
XODR = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "ingolstadt_perception_final.xodr"


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return d


def main() -> int:
    root = ET.parse(XODR).getroot()
    pts_all: List[Tuple[float, float]] = []
    road_ids: List[str] = []
    for road in root.findall("road"):
        poly = road_centerline_polyline(road, 10.0)
        if len(poly) < 2:
            continue
        pts_all.extend(poly)
        road_ids.extend([road.get("id")] * len(poly))
    tree = cKDTree(np.asarray(pts_all, dtype=np.float64))

    def nearest_m(x: float, y: float) -> float:
        d, _ = tree.query([x, y])
        return float(np.atleast_1d(d)[0])

    records: List[Dict[str, Any]] = []
    corners_all: List[float] = []
    for road in root.findall("road"):
        for obj in road.findall("objects/object"):
            if obj.get("type") != "crosswalk":
                continue
            obj_id = obj.get("id")
            s = _f(obj.get("s"))
            t = _f(obj.get("t"))
            hdg = _f(obj.get("hdg"))
            pose = reference_pose_at_s(road, s)
            if pose is None:
                continue
            local = []
            for c in obj.findall("outline/cornerLocal"):
                local.append((_f(c.get("u")), _f(c.get("v")), _f(c.get("z"))))
            if not local:
                continue
            world = carla_world_corners(local, pose, t, hdg)
            ds = [nearest_m(x, y) for (x, y, _) in world]
            corners_all.extend(ds)
            records.append({
                "object": obj_id,
                "road_id": road.get("id"),
                "corners": len(world),
                "nearest_road_m_min": round(min(ds), 3),
                "nearest_road_m_mean": round(sum(ds) / len(ds), 3),
                "nearest_road_m_max": round(max(ds), 3),
            })
    arr = np.asarray(corners_all)
    oa = np.asarray([r["nearest_road_m_mean"] for r in records])
    worst = sorted(records, key=lambda r: -r["nearest_road_m_mean"])[:10]
    stats = {
        "objects": len(records),
        "corners_total": int(len(arr)),
        "min_m": round(float(arr.min()), 3),
        "mean_m": round(float(arr.mean()), 3),
        "median_m": round(float(np.median(arr)), 3),
        "p95_m": round(float(np.percentile(arr, 95)), 3),
        "p99_m": round(float(np.percentile(arr, 99)), 3),
        "max_m": round(float(arr.max()), 3),
        "object_mean_median_m": round(float(np.median(oa)), 3) if len(oa) else 0.0,
        "object_mean_p95_m": round(float(np.percentile(oa, 95)), 3) if len(oa) else 0.0,
        "object_mean_max_m": round(float(np.max(oa)), 3) if len(oa) else 0.0,
    }
    out = {
        "schema": "C2E_CROSSWALK_CORNER_ALIGNMENT/v1",
        "producer": "stage_c2e_crosswalk_corner_alignment.py",
        "candidate": str(XODR),
        "frame": "EPSG:32632 native (XODR geometry frame)",
        "corner_to_road_stats_m": stats,
        "worst_objects": worst,
        "verdict": "CROSSWALK_ALIGNMENT_RESIDUALS_CAPTURED",
    }
    (C2 / "C2E_CROSSWALK_CORNER_ALIGNMENT.json").write_text(
        json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())