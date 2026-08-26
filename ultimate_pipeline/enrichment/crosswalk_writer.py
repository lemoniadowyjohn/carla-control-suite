# ultimate_pipeline/enrichment/crosswalk_writer.py
"""Wire real OSM footway=crossing data into XODR <object type="crosswalk"> elements.

crosswalk_schema.py provides the low-level CARLA-0.9.16-exact coordinate codec
(world <-> local u/v/z corner transform for crosswalk outlines) but nothing that
extracts real crossing data or matches it to a road -- that piece did not exist
before this module.

Pipeline: OSM footway=crossing way (real node geometry) -> project to the auto
map's local frame (same bare-tmerc + header-offset frame roads use, matching
osm_polygon_loader.py's corrected projection and local_registration.py's offset
handling -- see C29) -> geometric nearest-match to a road (s-position along its
planView) -> buffer the crossing's own line into a rectangle (real width from
OSM geometry, a fixed depth along the road) -> encode to CARLA-local corners via
crosswalk_schema.carla_local_corners -> insert as an <object type="crosswalk">.

Verified against the real pinned OSM (2026-08-26): 179 footway=crossing ways
exist (0 crossing-tagged nodes) -- real usable data, not a hypothetical feature.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from pyproj import CRS, Transformer

from ultimate_pipeline.enrichment.crosswalk_schema import (
    carla_local_corners,
    reference_pose_at_s,
)

# Same bare-tmerc frame Osm2Odr uses for road geometry (matches
# osm_polygon_loader.PROJ_STRING and local_registration.BARE_TMERC_DEFAULT).
_BARE_TMERC = "+proj=tmerc +datum=WGS84 +units=m +no_defs"
_TO_LOCAL = Transformer.from_crs("EPSG:4326", CRS.from_proj4(_BARE_TMERC), always_xy=True)

DEFAULT_MAX_MATCH_DIST_M = 5.0
DEFAULT_CROSSING_DEPTH_M = 3.0  # typical marked-crossing depth along the road


# ---------------------------------------------------------------------------
# OSM extraction
# ---------------------------------------------------------------------------

def extract_osm_crossings(osm_path: str) -> List[Dict[str, Any]]:
    """Parse *osm_path* for footway=crossing ways with resolvable node geometry.

    Returns a list of {"way_id": str, "nodes": [(lon, lat), ...]}. Ways whose
    footway tag isn't "crossing", or where fewer than 2 referenced nodes are
    resolvable (missing/malformed), are excluded -- not a usable crossing line.
    """
    try:
        tree = ET.parse(osm_path)
    except (FileNotFoundError, ET.ParseError):
        return []
    root = tree.getroot()

    node_coords: Dict[str, Tuple[float, float]] = {}
    for n in root.findall("node"):
        nid = n.get("id")
        try:
            lat = float(n.get("lat", ""))
            lon = float(n.get("lon", ""))
        except (TypeError, ValueError):
            continue
        if nid is not None:
            node_coords[nid] = (lon, lat)

    crossings: List[Dict[str, Any]] = []
    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        if tags.get("footway") != "crossing":
            continue
        refs = [nd.get("ref") for nd in way.findall("nd")]
        nodes = [node_coords[r] for r in refs if r in node_coords]
        if len(nodes) < 2:
            continue
        crossings.append({"way_id": way.get("id"), "nodes": nodes})

    return crossings


def project_crossing_to_local(
    lonlat_points: List[Tuple[float, float]],
    auto_offset: Tuple[float, float],
) -> List[Tuple[float, float]]:
    """Project (lon, lat) points into the auto map's local frame (bare-tmerc minus offset)."""
    ox, oy = auto_offset
    out = []
    for lon, lat in lonlat_points:
        gx, gy = _TO_LOCAL.transform(lon, lat)
        out.append((gx - ox, gy - oy))
    return out


# ---------------------------------------------------------------------------
# Geometric matching
# ---------------------------------------------------------------------------

def nearest_point_on_road(road: ET.Element, x: float, y: float) -> Tuple[float, float, Tuple[float, float]]:
    """Nearest point on `road`'s planView polyline to (x, y).

    Returns (distance_m, s, (px, py)). Approximates each geometry segment as a
    straight line between its start point and the next segment's start point
    (or, for the final segment, its own start + length along its own heading) --
    sufficiently precise for crossing-matching given real road segments here
    average ~46m and crossings are narrow (a few meters).
    """
    plan = road.find("planView")
    if plan is None:
        return float("inf"), 0.0, (0.0, 0.0)
    geoms = sorted(plan.findall("geometry"), key=lambda g: float(g.get("s", "0") or "0"))
    if not geoms:
        return float("inf"), 0.0, (0.0, 0.0)

    best_dist = float("inf")
    best_s = 0.0
    best_pt = (0.0, 0.0)
    for geom in geoms:
        gs = float(geom.get("s", "0") or "0")
        gx = float(geom.get("x", "0") or "0")
        gy = float(geom.get("y", "0") or "0")
        hdg = float(geom.get("hdg", "0") or "0")
        glen = float(geom.get("length", "0") or "0")
        ex = gx + glen * math.cos(hdg)
        ey = gy + glen * math.sin(hdg)

        seg_dx, seg_dy = ex - gx, ey - gy
        seg_len_sq = seg_dx * seg_dx + seg_dy * seg_dy
        if seg_len_sq < 1e-12:
            t = 0.0
        else:
            t = ((x - gx) * seg_dx + (y - gy) * seg_dy) / seg_len_sq
            t = max(0.0, min(1.0, t))
        px, py = gx + t * seg_dx, gy + t * seg_dy
        dist = math.hypot(x - px, y - py)
        if dist < best_dist:
            best_dist = dist
            best_s = gs + t * glen
            best_pt = (px, py)

    return best_dist, best_s, best_pt


def match_crossing_to_road(
    root: ET.Element,
    point_xy: Tuple[float, float],
    max_dist_m: float = DEFAULT_MAX_MATCH_DIST_M,
) -> Optional[Dict[str, Any]]:
    """Find the road whose planView polyline is nearest to `point_xy`, within max_dist_m."""
    x, y = point_xy
    best: Optional[Dict[str, Any]] = None
    best_dist = max_dist_m
    for road in root.findall("road"):
        dist, s, pt = nearest_point_on_road(road, x, y)
        if dist <= best_dist:
            best_dist = dist
            best = {"road": road, "s": s, "point": pt, "dist": dist}
    return best


# ---------------------------------------------------------------------------
# Outline construction
# ---------------------------------------------------------------------------

def crossing_outline_world(
    line_points: List[Tuple[float, float]],
    depth_m: float = DEFAULT_CROSSING_DEPTH_M,
) -> List[Tuple[float, float, float]]:
    """Buffer a 2-point crossing line into a 4-corner rectangle (world x, y, z=0).

    The line's own length/orientation (real OSM geometry) becomes one dimension;
    `depth_m` (a fixed default -- OSM rarely tags marked-crossing depth) is
    buffered perpendicular to the line to form the other.
    """
    (x0, y0), (x1, y1) = line_points[0], line_points[-1]
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-9:
        nx, ny = 1.0, 0.0
    else:
        nx, ny = -dy / length, dx / length  # unit perpendicular
    half = depth_m / 2.0
    return [
        (x0 + nx * half, y0 + ny * half, 0.0),
        (x1 + nx * half, y1 + ny * half, 0.0),
        (x1 - nx * half, y1 - ny * half, 0.0),
        (x0 - nx * half, y0 - ny * half, 0.0),
    ]


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def apply_crosswalks(
    root: ET.Element,
    crossings: List[Dict[str, Any]],
    *,
    max_match_dist_m: float = DEFAULT_MAX_MATCH_DIST_M,
    crossing_depth_m: float = DEFAULT_CROSSING_DEPTH_M,
) -> int:
    """Insert <object type="crosswalk"> elements for OSM crossings that match a real road.

    `crossings`: list of dicts with "way_id" and "nodes_local" ([(x, y), ...] in
    the auto map's local frame -- see project_crossing_to_local). Crossings with
    no road within max_match_dist_m are skipped, not forced onto the nearest
    road regardless of distance.

    Returns the number of <object> elements inserted.
    """
    inserted = 0
    counter = 0
    for crossing in crossings:
        nodes_local = crossing.get("nodes_local")
        if not nodes_local or len(nodes_local) < 2:
            continue
        midpoint = (
            sum(p[0] for p in nodes_local) / len(nodes_local),
            sum(p[1] for p in nodes_local) / len(nodes_local),
        )
        match = match_crossing_to_road(root, midpoint, max_dist_m=max_match_dist_m)
        if match is None:
            continue

        road = match["road"]
        s = match["s"]
        pose = reference_pose_at_s(road, s)
        if pose is None:
            continue

        world_outline = crossing_outline_world(nodes_local, depth_m=crossing_depth_m)
        local_corners = carla_local_corners(world_outline, pose, t=0.0, hdg=0.0)

        objects_elem = road.find("objects")
        if objects_elem is None:
            objects_elem = ET.SubElement(road, "objects")

        counter += 1
        obj = ET.SubElement(objects_elem, "object", {
            "id": f"crosswalk_{counter}",
            "type": "crosswalk",
            "name": f"osm_way_{crossing.get('way_id', '?')}",
            "s": f"{s:.3f}",
            "t": "0.0",
            "zOffset": "0.0",
            "hdg": "0.0",
            "orientation": "none",
        })
        outline = ET.SubElement(obj, "outline", {"id": "0", "fillType": "concrete"})
        for u, v, z in local_corners:
            ET.SubElement(outline, "cornerLocal", u=f"{u:.3f}", v=f"{v:.3f}", z=f"{z:.3f}")

        inserted += 1

    return inserted
