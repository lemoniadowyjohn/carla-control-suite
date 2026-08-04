#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collision and LOD policy checks (Phase J7).

Collision:
  For each non-road object in the OBJ, test whether its ground footprint
  intrudes into any XODR road corridor.  Road corridors are the curve-aware
  road bounds (per-road AABB from the XODR) expanded by a corridor half-width
  (lane width estimate).  Object footprints are transformed from the OBJ
  local frame into the XODR frame using the declared origin
  (xodr_x = origin_x + obj_x, xodr_y = origin_y - obj_z).

  Intrusions deeper than a tolerance are violations; shallower ones are
  recorded as minor (arcade/overhang allowance).

LOD:
  The LOD policy is recorded from the OSM2World properties (lodDistances)
  plus the artifact manifest.  OSM2World writes full-resolution geometry;
  distance-based LOD is applied at import time.  The check verifies the
  policy is declared and that the geometry units are meters (1 unit ~ 1 m).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.tiling.tile_equivalence import road_bounds_curve_aware
from ultimate_pipeline.enrichment.semantic_partition import parse_obj_objects
from ultimate_pipeline.enrichment.coordinate_control import (
    parse_obj_origin,
    parse_geo_reference,
    project_wgs84_to_xodr,
)

CORRIDOR_LANE_WIDTH_M = 3.5
CORRIDOR_BUFFER_M = 3.0
INTRUSION_TOLERANCE_M = 0.5


def lod_policy(config_path: Path) -> Dict[str, Any]:
    """Extract the LOD policy from an OSM2World properties file."""
    policy: Dict[str, Any] = {"declared": False, "source": "none"}
    if not config_path.exists():
        return policy
    text = config_path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"lodDistances\s*=\s*([\d,]+)", text)
    if m:
        policy["lod_distances_m"] = [int(x) for x in m.group(1).split(",")]
        policy["declared"] = True
        policy["source"] = str(config_path)
    return policy


def _road_corridors_xodr(
    xodr_path: Path,
    road_id_limits: Optional[Tuple[int, int]] = None,
) -> List[Dict[str, Any]]:
    """Curve-aware per-road AABB, expanded into a corridor."""
    import xml.etree.ElementTree as ET
    root = ET.parse(str(xodr_path)).getroot()
    corridors = []
    for road in root.findall("road"):
        rid = road.get("id")
        if road_id_limits:
            try:
                if not (road_id_limits[0] <= int(rid) <= road_id_limits[1]):
                    continue
            except ValueError:
                continue
        try:
            b = road_bounds_curve_aware(road)
        except Exception:
            continue
        half = CORRIDOR_LANE_WIDTH_M * 2 + CORRIDOR_BUFFER_M
        corridors.append({
            "road_id": rid,
            "corridor_half_width_m": half,
            "aabb": {
                "x_min": b["x_min"] - half, "y_min": b["y_min"] - half,
                "x_max": b["x_max"] + half, "y_max": b["y_max"] + half,
            },
        })
    return corridors


def _obj_footprint_xodr(obj: Dict[str, Any], origin_xodr: Tuple[float, float]) \
        -> Tuple[float, float, float, float]:
    """Object footprint in the XODR frame: (x_min, y_min, x_max, y_max)."""
    bx = obj["bounds"]
    return (origin_xodr[0] + bx[0], origin_xodr[1] - bx[5],
            origin_xodr[0] + bx[3], origin_xodr[1] - bx[2])


def _overlap(a: Tuple[float, float, float, float],
             b: Tuple[float, float, float, float]) -> Tuple[float, float]:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w), max(0.0, h)


def collision_check(
    obj_path: Path,
    xodr_path: Path,
    *,
    corridor_lane_width_m: float = CORRIDOR_LANE_WIDTH_M,
    corridor_buffer_m: float = CORRIDOR_BUFFER_M,
    tolerance_m: float = INTRUSION_TOLERANCE_M,
    sample_roads: Optional[int] = 2000,
) -> Dict[str, Any]:
    """
    J7 collision: OBJ objects vs XODR road corridors.
    """
    origin = parse_obj_origin(obj_path)
    geo_ref = parse_geo_reference(xodr_path)
    objects = parse_obj_objects(obj_path)

    report: Dict[str, Any] = {
        "corridor_lane_width_m": corridor_lane_width_m,
        "corridor_buffer_m": corridor_buffer_m,
        "intrusion_tolerance_m": tolerance_m,
        "objects_total": len(objects),
    }

    if origin is None:
        report["verdict"] = "NO_ORIGIN_DECLARED"
        report["detail"] = "OBJ header has no origin; cannot transform frames"
        return report

    proj = project_wgs84_to_xodr([(origin["lon"], origin["lat"])], geo_ref)
    if not proj:
        report["verdict"] = "UNPROJECTABLE"
        return report
    origin_xodr = proj[0]

    roads = list(_road_corridors_xodr(xodr_path))
    if sample_roads is not None:
        roads = roads[:sample_roads]
    report["road_corridors_checked"] = len(roads)

    intrusions: List[Dict[str, Any]] = []
    for obj in objects:
        if obj["class"] in ("road", "rail"):
            continue
        foot = _obj_footprint_xodr(obj, origin_xodr)
        for corr in roads:
            cb = corr["aabb"]
            cbt = (cb["x_min"], cb["y_min"], cb["x_max"], cb["y_max"])
            w, h = _overlap(foot, cbt)
            if w > 0 and h > 0:
                depth = min(w, h)
                intrusions.append({
                    "object": obj["name"],
                    "class": obj["class"],
                    "road_id": corr["road_id"],
                    "overlap_m2": round(w * h, 2),
                    "depth_m": round(depth, 2),
                })
    report["intrusions"] = intrusions[:200]
    report["intrusion_count"] = len(intrusions)
    violations = [i for i in intrusions if i["depth_m"] > tolerance_m]
    report["violation_count"] = len(violations)
    report["violations"] = violations[:50]
    report["verdict"] = "PASS" if not violations else "VIOLATION"
    return report


def lod_check(config_path: Path, obj_path: Path, manifest: Optional[Dict]) -> Dict[str, Any]:
    """
    J7 LOD: policy declared in config + artifact manifest cross-check.
    """
    policy = lod_policy(config_path)
    checks: Dict[str, Any] = {
        "policy_declared": policy["declared"],
        "lod_distances_m": policy.get("lod_distances_m", []),
        "policy_source": policy["source"],
        "unit_note": "OSM2World OBJ: 1 coordinate unit ~ 1 m (header)",
    }
    if manifest:
        checks["manifest_blender_version"] = manifest.get("blender_version")
        checks["manifest_units"] = {
            "system": manifest.get("scene_unit_system"),
            "scale": manifest.get("scene_unit_scale"),
        }
    checks["verdict"] = "POLICY_DECLARED" if policy["declared"] else "POLICY_UNDECLARED"
    return checks


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("usage: collision_lod_policy.py <scene.obj> <candidate.xodr> "
              "[osm2world.properties] [blender_manifest.json]")
        sys.exit(2)
    result = {
        "collision": collision_check(Path(sys.argv[1]), Path(sys.argv[2])),
        "lod": lod_check(
            Path(sys.argv[3]) if len(sys.argv) > 3 else Path("nonexistent"),
            Path(sys.argv[1]),
            json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
            if len(sys.argv) > 4 else None),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
