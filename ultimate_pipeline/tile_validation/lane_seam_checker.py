from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Dict, Tuple
import math

XY = Tuple[float, float]


@dataclass
class LanePoint:
    x: float
    y: float
    z: float
    hdg: float   # heading
    s: float     # param s along lane centerline


@dataclass
class LanePolyline:
    points: List[LanePoint]
    road_id: str
    lane_id: int


@dataclass
class SeamReport:
    lane_pairs: List[Dict]
    max_lateral_offset: float
    max_heading_error: float
    max_elevation_jump: float
    marking_mismatch_pairs: int
    warnings: List[str]


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except Exception:
        return default


def _angle_wrap(a: float) -> float:
    while a <= -math.pi:
        a += 2.0 * math.pi
    while a > math.pi:
        a -= 2.0 * math.pi
    return a


def _angle_diff(a: float, b: float) -> float:
    return _angle_wrap(a - b)


def _lane_type(lane: ET.Element) -> str:
    # OpenDRIVE: <lane id=".." type="driving" ...>
    t = (lane.get("type") or "").strip().lower()
    if t:
        return t

    # Some generators add a child <type> (non-standard for lane element) – be defensive.
    t_elem = lane.find("type")
    if t_elem is not None:
        return (t_elem.get("type") or t_elem.text or "").strip().lower()

    return ""


def _sample_geometry(geom: ET.Element, step: float = 2.0) -> List[XY]:
    """Sample a geometry (line or arc) into XY points."""
    x0 = _safe_float(geom.get("x", "0"))
    y0 = _safe_float(geom.get("y", "0"))
    hdg = _safe_float(geom.get("hdg", "0"))
    length = _safe_float(geom.get("length", "0"))

    arc = geom.find("arc")
    pts: List[XY] = []

    if arc is None:
        n = max(2, int(max(length, 0.0) / step))
        for i in range(n + 1):
            ds = length * (i / n)
            x = x0 + ds * math.cos(hdg)
            y = y0 + ds * math.sin(hdg)
            pts.append((x, y))
        return pts

    curvature = _safe_float(arc.get("curvature", "0"))
    if abs(curvature) < 1e-12:
        n = max(2, int(max(length, 0.0) / step))
        for i in range(n + 1):
            ds = length * (i / n)
            x = x0 + ds * math.cos(hdg)
            y = y0 + ds * math.sin(hdg)
            pts.append((x, y))
        return pts

    R = 1.0 / curvature
    n = max(12, int(max(length, 0.0) / step))
    for i in range(n + 1):
        ds = length * (i / n)
        theta = ds * curvature
        x = x0 + R * (math.sin(hdg + theta) - math.sin(hdg))
        y = y0 - R * (math.cos(hdg + theta) - math.cos(hdg))
        pts.append((x, y))
    return pts


def _planview_polyline(road: ET.Element, step: float = 2.0) -> List[LanePoint]:
    plan = road.find("planView")
    if plan is None:
        return []
    geoms = plan.findall("geometry")
    if not geoms:
        return []

    # XY sampling
    xy: List[XY] = []
    for g in geoms:
        pts = _sample_geometry(g, step=step)
        if not xy:
            xy.extend(pts)
        else:
            xy.extend(pts[1:])

    if not xy:
        return []

    # Elevation: use first elevation a/z as a flat approximation
    z = 0.0
    elev = road.find("./elevationProfile/elevation")
    if elev is not None:
        z = _safe_float(elev.get("a", elev.get("z", "0")))

    # cumulative s + heading from forward diff
    out: List[LanePoint] = []
    s = 0.0
    for i, (x, y) in enumerate(xy):
        if i > 0:
            px, py = xy[i - 1]
            s += math.hypot(x - px, y - py)
        if i < len(xy) - 1:
            nx, ny = xy[i + 1]
            hdg = math.atan2(ny - y, nx - x)
        else:
            # last point: reuse previous heading if available
            hdg = out[-1].hdg if out else 0.0
        out.append(LanePoint(x=x, y=y, z=z, hdg=hdg, s=s))
    return out


def _extract_lane_polylines(root: ET.Element) -> List[LanePolyline]:
    """Returns centerlines of all driving lanes (planView proxy)."""
    out: List[LanePolyline] = []

    for road in root.findall("road"):
        rid = road.get("id", "?")
        plan_pts = _planview_polyline(road, step=2.0)
        if not plan_pts:
            continue

        lanesec_elems = road.findall("./lanes/laneSection")
        if not lanesec_elems:
            continue

        for ls in lanesec_elems:
            for side in ("left", "right"):
                side_elem = ls.find(side)
                if side_elem is None:
                    continue
                for lane in side_elem.findall("lane"):
                    if _lane_type(lane) != "driving":
                        continue
                    try:
                        lane_id = int(lane.get("id"))
                    except Exception:
                        continue

                    # We use planView as proxy centerline (good enough for seam QA)
                    out.append(LanePolyline(points=plan_pts, road_id=rid, lane_id=lane_id))

    return out


def _extract_border_points(
    polys: List[LanePolyline],
    xmin: float, ymin: float, xmax: float, ymax: float,
    border_tol: float = 5.0
) -> List[LanePolyline]:
    """Keep only polylines whose end points lie close to bbox border."""
    out: List[LanePolyline] = []

    def near(px: float, py: float) -> bool:
        return (
            abs(px - xmin) <= border_tol
            or abs(px - xmax) <= border_tol
            or abs(py - ymin) <= border_tol
            or abs(py - ymax) <= border_tol
        )

    for poly in polys:
        if not poly.points:
            continue
        p0 = poly.points[0]
        p1 = poly.points[-1]
        if near(p0.x, p0.y) or near(p1.x, p1.y):
            out.append(poly)

    return out


def _match_lanes(
    border_a: List[LanePolyline],
    border_b: List[LanePolyline],
    max_dist: float = 2.0,
    max_hdg_diff: float = 0.3
) -> List[Tuple[LanePolyline, LanePolyline]]:
    """Match A endpoint -> B startpoint by distance + wrapped heading similarity."""
    matches: List[Tuple[LanePolyline, LanePolyline]] = []
    for la in border_a:
        pa = la.points[-1]
        best = None
        best_dist = 1e9

        for lb in border_b:
            pb = lb.points[0]
            dist = math.hypot(pa.x - pb.x, pa.y - pb.y)
            if dist > max_dist:
                continue
            hdg_diff = abs(_angle_diff(pa.hdg, pb.hdg))
            if hdg_diff > max_hdg_diff:
                continue
            if dist < best_dist:
                best_dist = dist
                best = lb

        if best is not None:
            matches.append((la, best))
    return matches


def _compute_seam_stats(pA: LanePoint, pB: LanePoint) -> Dict:
    # signed deltas (A - B): what you’d add to B to align to A (before rotation)
    dx = pA.x - pB.x
    dy = pA.y - pB.y
    dz = pA.z - pB.z
    dtheta = _angle_diff(pA.hdg, pB.hdg)

    lateral_offset = math.hypot(dx, dy)
    heading_error = abs(dtheta)
    elevation_jump = abs(dz)

    return {
        "dx": dx,
        "dy": dy,
        "dz": dz,
        "dtheta": dtheta,
        "lateral_offset": lateral_offset,
        "heading_error": heading_error,
        "elevation_jump": elevation_jump,
    }


def _lane_has_markings(root: ET.Element, road_id: str, lane_id: int) -> bool:
    """True if lane has any <roadMark>."""
    for road in root.findall("road"):
        if road.get("id") != str(road_id):
            continue
        for lane in road.findall(".//lane"):
            if lane.get("id") == str(lane_id):
                if lane.findall("roadMark"):
                    return True
    return False


class LaneSeamChecker:
    """Checks lane continuity across tile boundaries (planView proxy).

    Also validates:
      - marking presence continuity across seam
    """

    @staticmethod
    def analyze(
        tile_a: str,
        tile_b: str,
        border_tol: float = 5.0,
        dist_thresh: float = 2.0,
        hdg_thresh: float = 0.3
    ) -> SeamReport:

        rootA = ET.parse(tile_a).getroot()
        rootB = ET.parse(tile_b).getroot()

        polysA = _extract_lane_polylines(rootA)
        polysB = _extract_lane_polylines(rootB)

        def bb(root):
            xs, ys = [], []
            for g in root.findall(".//geometry"):
                xs.append(_safe_float(g.get("x", "0")))
                ys.append(_safe_float(g.get("y", "0")))
            if not xs or not ys:
                # Safe degenerate bbox
                return 0.0, 0.0, 0.0, 0.0
            return min(xs), min(ys), max(xs), max(ys)

        xminA, yminA, xmaxA, ymaxA = bb(rootA)
        xminB, yminB, xmaxB, ymaxB = bb(rootB)

        borderA = _extract_border_points(polysA, xminA, yminA, xmaxA, ymaxA, border_tol)
        borderB = _extract_border_points(polysB, xminB, yminB, xmaxB, ymaxB, border_tol)

        matches = _match_lanes(borderA, borderB, max_dist=dist_thresh, max_hdg_diff=hdg_thresh)

        lane_pairs: List[Dict] = []
        max_lat = 0.0
        max_hdg = 0.0
        max_ele = 0.0
        marking_mismatch_pairs = 0
        warnings: List[str] = []

        for la, lb in matches:
            pA = la.points[-1]
            pB = lb.points[0]

            stats = _compute_seam_stats(pA, pB)

            has_mark_A = _lane_has_markings(rootA, la.road_id, la.lane_id)
            has_mark_B = _lane_has_markings(rootB, lb.road_id, lb.lane_id)
            marking_match = (has_mark_A == has_mark_B)
            if not marking_match:
                marking_mismatch_pairs += 1

            lane_pairs.append({
                "roadA": la.road_id,
                "laneA": la.lane_id,
                "roadB": lb.road_id,
                "laneB": lb.lane_id,
                "has_mark_A": has_mark_A,
                "has_mark_B": has_mark_B,
                "marking_match": marking_match,
                **stats,
            })

            _lat = stats["lateral_offset"]
            _hdg = stats["heading_error"]
            _ele = stats["elevation_jump"]
            max_lat = _lat if not math.isfinite(_lat) else max(max_lat, _lat)
            max_hdg = _hdg if not math.isfinite(_hdg) else max(max_hdg, _hdg)
            max_ele = _ele if not math.isfinite(_ele) else max(max_ele, _ele)

        # Warnings (heuristics)
        if not math.isfinite(max_lat) or max_lat > 0.10:
            warnings.append(f"Lateral offset exceeds 10 cm: {max_lat:.3f} m")
        if not math.isfinite(max_hdg) or max_hdg > 0.10:
            warnings.append(f"Heading jump > 0.10 rad: {max_hdg:.3f}")
        if not math.isfinite(max_ele) or max_ele > 0.05:
            warnings.append(f"Elevation jump > 5 cm: {max_ele:.3f} m")
        if marking_mismatch_pairs > 0:
            warnings.append(f"{marking_mismatch_pairs} lane pairs have marking presence mismatch across seam.")

        return SeamReport(
            lane_pairs=lane_pairs,
            max_lateral_offset=max_lat,
            max_heading_error=max_hdg,
            max_elevation_jump=max_ele,
            marking_mismatch_pairs=marking_mismatch_pairs,
            warnings=warnings,
        )
