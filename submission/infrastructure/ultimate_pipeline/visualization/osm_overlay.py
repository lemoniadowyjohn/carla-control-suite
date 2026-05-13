# ultimate_pipeline/visualization/osm_overlay.py

from __future__ import annotations
import math
import xml.etree.ElementTree as ET
from typing import Dict, Tuple, List

import matplotlib.pyplot as plt


def _latlon_to_xy(lat: float, lon: float, ref_lat: float, ref_lon: float) -> Tuple[float, float]:
    """Simple equirectangular projection."""
    R = 6371000.0
    lat0 = math.radians(ref_lat)
    x = R * math.radians(lon - ref_lon) * math.cos(lat0)
    y = R * math.radians(lat - ref_lat)
    return x, y


def _load_osm_ways(
    osm_path: str,
    ref_lat: float,
    ref_lon: float,
) -> List[List[Tuple[float, float]]]:
    tree = ET.parse(osm_path)
    root = tree.getroot()

    # nodes: id -> (x,y)
    nodes: Dict[int, Tuple[float, float]] = {}
    for n in root.findall("node"):
        nid = n.get("id")
        lat = n.get("lat")
        lon = n.get("lon")
        if nid is None or lat is None or lon is None:
            continue
        nid_i = int(nid)
        nodes[nid_i] = _latlon_to_xy(float(lat), float(lon), ref_lat, ref_lon)

    ways: List[List[Tuple[float, float]]] = []
    for w in root.findall("way"):
        pts = []
        for nd in w.findall("nd"):
            ref = nd.get("ref")
            if ref is None:
                continue
            nid = int(ref)
            if nid in nodes:
                pts.append(nodes[nid])
        if len(pts) >= 2:
            ways.append(pts)
    return ways


def _load_xodr_polylines(xodr_path: str, step: float = 10.0) -> List[List[Tuple[float, float]]]:
    import xml.etree.ElementTree as ET
    import math

    def safe_float(val: str, default: float = 0.0) -> float:
        try:
            return float(val)
        except Exception:
            return default

    def sample_geom(geom: ET.Element) -> List[Tuple[float, float]]:
        x0 = safe_float(geom.get("x", "0"))
        y0 = safe_float(geom.get("y", "0"))
        hdg = safe_float(geom.get("hdg", "0"))
        length = safe_float(geom.get("length", "0"))
        if length <= 0:
            return []
        n = max(4, int(length / step))
        pts = []
        for i in range(n + 1):
            ds = length * (i / n)
            x = x0 + ds * math.cos(hdg)
            y = y0 + ds * math.sin(hdg)
            pts.append((x, y))
        return pts

    tree = ET.parse(xodr_path)
    root = tree.getroot()

    polylines: List[List[Tuple[float, float]]] = []
    for road in root.findall("road"):
        plan = road.find("planView")
        if plan is None:
            continue
        road_pts: List[Tuple[float, float]] = []
        for g in plan.findall("geometry"):
            pts = sample_geom(g)
            if not pts:
                continue
            if not road_pts:
                road_pts.extend(pts)
            else:
                road_pts.extend(pts[1:])
        if road_pts:
            polylines.append(road_pts)
    return polylines


def plot_osm_over_xodr(
    xodr_path: str,
    osm_path: str,
    ref_lat: float,
    ref_lon: float,
    out_png: str,
    figsize=(8, 8),
) -> None:
    """
    Draw XODR roads + OSM ways in the same approximate coordinate frame.
    """
    xodr_polys = _load_xodr_polylines(xodr_path)
    osm_ways = _load_osm_ways(osm_path, ref_lat=ref_lat, ref_lon=ref_lon)

    plt.figure(figsize=figsize)

    # XODR roads
    for pts in xodr_polys:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        plt.plot(xs, ys, linewidth=0.7, color="black", alpha=0.7, label="XODR" if "xodr_label" not in locals() else "")
        xodr_label = True  # type: ignore

    # OSM ways
    for pts in osm_ways:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
