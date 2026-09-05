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
from ultimate_pipeline.quality.check_geometric_continuity import (
    _parse_geometries,
    _pose_for_geometry,
)

# Sampling step for curve-aware road matching (round-6 fix). Coarser than this
# risks missing narrow crossings; finer wastes time over 32k+ roads x ~179
# crossings without meaningfully changing the match outcome.
_CURVE_SAMPLE_STEP_M = 2.0

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
    """Nearest point on `road`'s planView TRUE curve to (x, y).

    Returns (distance_m, s, (px, py)).

    Round-6 fix: the original implementation approximated every geometry
    segment as a straight line from its own start point extended by its own
    length along its own INITIAL heading -- for a curved segment (arc,
    spiral, poly3, paramPoly3) this ignores the curvature entirely, so the
    "endpoint" it draws the chord to can be many meters away from the
    segment's real endpoint. Verified against the real pinned OSM/candidate
    pair: of 51 unmatched real crossings, 14 were "near misses" (5-9.3m,
    just outside the 5m default threshold) and 10 of those 14 were on
    paramPoly3 segments specifically -- confirming the straight-chord
    approximation was systematically overstating distance-to-road on curves
    and causing real, legitimate crossings to be silently dropped.

    Reuses check_geometric_continuity's _parse_geometries/_pose_for_geometry
    (the same correct pose evaluation used to validate road-to-road
    continuity elsewhere in this codebase) to sample each geometry along its
    real shape every _CURVE_SAMPLE_STEP_M, rather than reimplementing
    per-primitive curve math here.
    """
    geoms, _warnings = _parse_geometries(road)
    if not geoms:
        return float("inf"), 0.0, (0.0, 0.0)

    best_dist = float("inf")
    best_s = 0.0
    best_pt = (0.0, 0.0)
    for g in geoms:
        length = max(float(g.length), 0.0)
        n_samples = max(2, int(length / _CURVE_SAMPLE_STEP_M) + 1) if length > 0 else 1
        s_locals = [length * i / (n_samples - 1) if n_samples > 1 else 0.0 for i in range(n_samples)]
        poses = [_pose_for_geometry(g, sl) for sl in s_locals]

        if len(poses) == 1:
            p = poses[0]
            dist = math.hypot(x - p.x, y - p.y)
            if dist < best_dist:
                best_dist, best_s, best_pt = dist, g.s0 + s_locals[0], (p.x, p.y)
            continue

        # Project onto each small sample-to-sample sub-segment (not just the
        # nearest discrete sample) -- for a straight line this reduces to
        # exactly the same projection math the old implementation used
        # (colinear samples), and for a curve it follows the true shape far
        # more closely than one whole-segment chord.
        for i in range(len(poses) - 1):
            p0, p1 = poses[i], poses[i + 1]
            seg_dx, seg_dy = p1.x - p0.x, p1.y - p0.y
            seg_len_sq = seg_dx * seg_dx + seg_dy * seg_dy
            if seg_len_sq < 1e-12:
                t = 0.0
            else:
                t = ((x - p0.x) * seg_dx + (y - p0.y) * seg_dy) / seg_len_sq
                t = max(0.0, min(1.0, t))
            px, py = p0.x + t * seg_dx, p0.y + t * seg_dy
            dist = math.hypot(x - px, y - py)
            if dist < best_dist:
                best_dist = dist
                best_s = g.s0 + s_locals[i] + t * (s_locals[i + 1] - s_locals[i])
                best_pt = (px, py)

    return best_dist, best_s, best_pt


class RoadSpatialIndex:
    """Grid index of sampled road-curve positions, built ONCE per XODR root
    and reused across many crossing-match queries.

    Needed after switching nearest_point_on_road from an O(1)-per-geometry
    straight-chord approximation to curve-aware sampling: a naive "check
    every road for every crossing" scan took 882s (14m42s) against the real
    32k-road candidate and 179 real crossings. A first attempt at a cheap
    per-road distance-lower-bound pre-filter (using `dist(start) - length`)
    was both still too slow (347s) AND subtly unsafe: for a paramPoly3 whose
    declared `length` doesn't match its actual parametric arc length (the
    same class of authoring gotcha found in the round-5 recompute-guard fix),
    the bound's assumption that "no point on the curve is farther than
    `length` from the start" can be violated, silently dropping a real
    match (confirmed: match count dropped 128 -> 127 with that filter).

    This index instead buckets each road's ACTUAL sampled (x, y) positions
    (the same positions nearest_point_on_road computes from, via
    check_geometric_continuity's real pose evaluation -- not the `length`
    field) into a coarse grid, so a query only needs to inspect the small
    number of roads with a sample near the query point, then runs the full
    precise nearest_point_on_road only on those candidates. No length-based
    assumption, so no corresponding safety gap.
    """

    def __init__(self, root: ET.Element, cell_size_m: float = 10.0) -> None:
        self._cell_size = cell_size_m
        self._cells: Dict[Tuple[int, int], set] = {}
        for road in root.findall("road"):
            geoms, _warnings = _parse_geometries(road)
            for g in geoms:
                length = max(float(g.length), 0.0)
                n = max(2, int(length / _CURVE_SAMPLE_STEP_M) + 1) if length > 0 else 1
                for i in range(n):
                    s_local = length * i / (n - 1) if n > 1 else 0.0
                    pose = _pose_for_geometry(g, s_local)
                    cell = self._cell_of(pose.x, pose.y)
                    self._cells.setdefault(cell, set()).add(road)

    def _cell_of(self, x: float, y: float) -> Tuple[int, int]:
        return (int(x // self._cell_size), int(y // self._cell_size))

    def candidates_near(self, x: float, y: float, max_dist_m: float) -> List[ET.Element]:
        """Roads with at least one sampled point within `max_dist_m` of the
        cell neighborhood around (x, y) -- a superset of roads that could
        actually be within max_dist_m; nearest_point_on_road resolves the
        exact distance for each candidate returned here."""
        reach = int(max_dist_m // self._cell_size) + 1
        cx, cy = self._cell_of(x, y)
        found: set = set()
        for dx in range(-reach, reach + 1):
            for dy in range(-reach, reach + 1):
                found.update(self._cells.get((cx + dx, cy + dy), ()))
        return list(found)


def match_crossing_to_road(
    root: ET.Element,
    point_xy: Tuple[float, float],
    max_dist_m: float = DEFAULT_MAX_MATCH_DIST_M,
    *,
    spatial_index: Optional[RoadSpatialIndex] = None,
) -> Optional[Dict[str, Any]]:
    """Find the road whose planView polyline is nearest to `point_xy`, within max_dist_m.

    `spatial_index`: an optional prebuilt RoadSpatialIndex(root) -- pass one
    in when matching many crossings against the same root (apply_crosswalks
    does this) to avoid re-scanning every road per crossing. If omitted, a
    fresh index is built for this single call (fine for tests/one-off use
    with a handful of roads, wasteful for a real 32k-road map called in a
    loop).
    """
    x, y = point_xy
    index = spatial_index or RoadSpatialIndex(root)
    best: Optional[Dict[str, Any]] = None
    best_dist = max_dist_m
    for road in index.candidates_near(x, y, max_dist_m):
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
    # Built once and reused for every crossing -- see RoadSpatialIndex's
    # docstring for why a per-crossing full-road scan is unworkably slow
    # (882s for the real 32k-road candidate x 179 crossings).
    spatial_index = RoadSpatialIndex(root)

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
        match = match_crossing_to_road(
            root, midpoint, max_dist_m=max_match_dist_m, spatial_index=spatial_index
        )
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
