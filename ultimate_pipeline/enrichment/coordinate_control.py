#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coordinate control points between OSM2World output, source OSM and the XODR
frame (Phase J5).

OSM2World emits a local projection whose origin is declared in the OBJ header:

    # Coordinate origin (0,0,0): lat <lat>, lon <lon>, ele <ele>

The OBJ frame is: x = east, y = up, z = south; 1 unit ~ 1 m.
Given the local origin projected into the XODR frame (EPSG:32632 via the
OpenDRIVE geoReference), the mapping is:

    xodr_x = origin_x + obj_x
    xodr_y = origin_y - obj_z
    xodr_z = obj_y

J5 compares:
  1. the projected OBJ origin against sampled XODR road control points
     (planView evaluated at geometry-element endpoints),
  2. the source OSM window bounds (WGS84 -> XODR frame) against the XODR
     roads actually present.

A large residual displacement means the OSM input and the XODR map do not
describe the same geographic region (origin-shift class of bug).
"""
from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from pyproj import CRS, Transformer
    _HAS_PYPROJ = True
except Exception:  # pragma: no cover
    _HAS_PYPROJ = False


def parse_obj_origin(path: Path) -> Optional[Dict[str, float]]:
    """Parse the 'Coordinate origin (0,0,0): lat ..., lon ..., ele ...' header."""
    pattern = re.compile(
        r"Coordinate origin \(0,0,0\): lat ([-\d.]+),\s*lon ([-\d.]+),"
        r"\s*ele ([-\d.]+)")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            if not stripped.startswith("#"):
                break
            m = pattern.search(line)
            if m:
                return {"lat": float(m.group(1)), "lon": float(m.group(2)),
                        "ele": float(m.group(3))}
    return None


def parse_geo_reference(xodr_path: Path) -> str:
    root = ET.parse(str(xodr_path)).getroot()
    return (root.find("header/geoReference").text or "").strip() if \
        root.find("header/geoReference") is not None else ""


def _xodr_crs(geo_reference: str):
    if not _HAS_PYPROJ:
        return None
    try:
        if "EPSG:" in geo_reference.upper():
            return CRS.from_user_input(geo_reference.strip())
        return CRS.from_proj4(geo_reference)
    except Exception:
        return None


def project_wgs84_to_xodr(
    points: List[Tuple[float, float]],
    geo_reference: str,
) -> List[Tuple[float, float]]:
    """Project (lon, lat) points into the XODR frame via geoReference."""
    crs = _xodr_crs(geo_reference)
    if crs is None:
        return []
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return [tuple(transformer.transform(lon, lat)) for lon, lat in points]


def sample_xodr_road_points(
    xodr_path: Path,
    max_roads: int = 400,
    max_geometries: int = 200000,
) -> List[Tuple[float, float]]:
    """
    Sample planView control points: every geometry element start and end
    position for up to max_roads roads.
    """
    from opendrive_geometry.primitives import (
        evaluate_arc, evaluate_line, evaluate_param_poly3,
        evaluate_poly3, evaluate_spiral,
    )
    root = ET.parse(str(xodr_path)).getroot()
    points: List[Tuple[float, float]] = []
    geometry_count = 0
    road_count = 0
    for road in root.findall("road"):
        if road_count >= max_roads:
            break
        road_count += 1
        for geom in road.findall("planView/geometry"):
            if geometry_count >= max_geometries:
                return points
            geometry_count += 1
            x0 = float(geom.get("x", "0.0"))
            y0 = float(geom.get("y", "0.0"))
            hdg = float(geom.get("hdg", "0.0"))
            length = float(geom.get("length", "0.0"))
            child = None
            for tag in ("line", "arc", "spiral", "poly3", "paramPoly3"):
                c = geom.find(f"./{tag}")
                if c is not None:
                    child = c
                    tag = c.tag
                    break
            if child is None:
                continue
            try:
                if tag == "line":
                    end = evaluate_line(x0, y0, hdg, length, length)
                elif tag == "arc":
                    end = evaluate_arc(x0, y0, hdg, length,
                                       float(child.get("curvature", "0.0")), length)
                elif tag == "spiral":
                    end = evaluate_spiral(x0, y0, hdg, length,
                                          float(child.get("curvStart", "0.0")),
                                          float(child.get("curvEnd", "0.0")), length)
                elif tag == "poly3":
                    end = evaluate_poly3(x0, y0, hdg, length,
                                         float(child.get("a", "0.0")),
                                         float(child.get("b", "0.0")),
                                         float(child.get("c", "0.0")),
                                         float(child.get("d", "0.0")), length)
                else:  # paramPoly3
                    end = evaluate_param_poly3(
                        x0, y0, hdg, length,
                        float(child.get("aU", "0.0")), float(child.get("bU", "0.0")),
                        float(child.get("cU", "0.0")), float(child.get("dU", "0.0")),
                        float(child.get("aV", "0.0")), float(child.get("bV", "0.0")),
                        float(child.get("cV", "0.0")), float(child.get("dV", "0.0")),
                        child.get("pRange", "arcLength"), length)
                points.append((x0, y0))
                points.append((end.x, end.y))
            except Exception:
                continue
        if len(points) >= max_geometries:
            break
    return points


def _aabb(points: List[Tuple[float, float]]) -> Dict[str, float]:
    if not points:
        return {"x_min": 0.0, "y_min": 0.0, "x_max": 0.0, "y_max": 0.0}
    return {
        "x_min": min(p[0] for p in points),
        "y_min": min(p[1] for p in points),
        "x_max": max(p[0] for p in points),
        "y_max": max(p[1] for p in points),
    }


def _nearest(point: Tuple[float, float],
             points: List[Tuple[float, float]]) -> Tuple[float, float, int]:
    best_d = float("inf")
    best_i = -1
    best_p = (0.0, 0.0)
    for i, p in enumerate(points):
        d = math.hypot(p[0] - point[0], p[1] - point[1])
        if d < best_d:
            best_d, best_i, best_p = d, i, p
    return best_d, best_p, best_i


def coordinate_control_check(
    obj_path: Path,
    xodr_path: Path,
    os_window_bounds_wgs84: Optional[Dict[str, float]] = None,
    sample_limit: int = 400,
) -> Dict[str, Any]:
    """
    J5: verify OSM2World/OSM window placement against XODR control points.

    Args:
        obj_path: OSM2World OBJ output
        xodr_path: candidate XODR (same geoReference used by OSM2World)
        os_window_bounds_wgs84: {"lat_min","lon_min","lat_max","lon_max"} of the
            source OSM window (optional)
        sample_limit: max XODR roads to sample
    """
    origin = parse_obj_origin(obj_path)
    geo_ref = parse_geo_reference(xodr_path)
    xodr_points = sample_xodr_road_points(xodr_path, max_roads=sample_limit)
    xodr_aabb = _aabb(xodr_points)

    report: Dict[str, Any] = {
        "obj_header_origin_wgs84": origin,
        "xodr_geo_reference": geo_ref,
        "xodr_roads_sampled": sample_limit,
        "xodr_road_points_sampled": len(xodr_points),
        "xodr_road_aabb": xodr_aabb,
        "mapping": {
            "xodr_x = origin_x + obj_x": True,
            "xodr_y = origin_y - obj_z": True,
            "xodr_z = obj_y": True,
        },
    }

    if origin is None:
        report["verdict"] = "NO_ORIGIN_DECLARED"
        report["detail"] = "OBJ header does not declare a coordinate origin"
        return report

    if not _HAS_PYPROJ:
        report["verdict"] = "PYPROJ_UNAVAILABLE"
        return report

    proj = project_wgs84_to_xodr([(origin["lon"], origin["lat"])], geo_ref)
    if not proj:
        report["verdict"] = "GEO_REFERENCE_UNPROJECTABLE"
        return report
    origin_xodr = proj[0]
    report["obj_origin_xodr_frame"] = list(origin_xodr)

    if xodr_points:
        dist, nearest, idx = _nearest(origin_xodr, xodr_points)
        report["nearest_xodr_road_point_m"] = round(dist, 1)
        report["nearest_xodr_road_point"] = list(nearest)
    else:
        dist = float("inf")
        report["nearest_xodr_road_point_m"] = None

    # expected XODR region from the source OSM window
    if os_window_bounds_wgs84:
        b = os_window_bounds_wgs84
        corners = [
            (b["lon_min"], b["lat_min"]), (b["lon_max"], b["lat_min"]),
            (b["lon_max"], b["lat_max"]), (b["lon_min"], b["lat_max"]),
        ]
        proj_corners = project_wgs84_to_xodr(corners, geo_ref)
        os_aabb = _aabb(proj_corners)
        report["os_window_xodr_aabb"] = os_aabb
        overlap_w = max(0.0, min(os_aabb["x_max"], xodr_aabb["x_max"])
                        - max(os_aabb["x_min"], xodr_aabb["x_min"]))
        overlap_h = max(0.0, min(os_aabb["y_max"], xodr_aabb["y_max"])
                        - max(os_aabb["y_min"], xodr_aabb["y_min"]))
        report["overlap_m2"] = round(overlap_w * overlap_h, 1)
        center_os = ((os_aabb["x_min"] + os_aabb["x_max"]) / 2.0,
                     (os_aabb["y_min"] + os_aabb["y_max"]) / 2.0)
        gap, _, _ = _nearest(center_os, xodr_points) if xodr_points else (float("inf"), (), -1)
        report["os_center_to_nearest_xodr_road_m"] = round(gap, 1)

    if math.isinf(dist) or dist is None:
        report["verdict"] = "MISALIGNED"
        report["detail"] = "no XODR road points to compare"
    elif dist < 100.0:
        report["verdict"] = "ALIGNED"
        report["detail"] = (f"OBJ origin within {dist:.1f} m of an XODR road "
                            "control point")
    else:
        report["verdict"] = "MISALIGNED"
        report["detail"] = (f"OBJ origin is {dist:.1f} m from the nearest XODR "
                            "road control point: the source OSM and the XODR "
                            "map do not describe the same region (origin-shift)")
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("usage: coordinate_control.py <scene.obj> <candidate.xodr> "
              "[os_window_bounds.json]")
        sys.exit(2)
    bounds = None
    if len(sys.argv) > 3:
        bounds = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    print(json.dumps(coordinate_control_check(
        Path(sys.argv[1]), Path(sys.argv[2]), bounds), indent=2, sort_keys=True))
