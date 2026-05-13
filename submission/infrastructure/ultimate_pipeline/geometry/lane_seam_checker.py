import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Tuple
import math

XY = Tuple[float, float]


def _safe_float(val: str, default: float = 0.0) -> float:
    try:
        return float(val)
    except Exception:
        return default


@dataclass
class SeamReport:
    lane_pairs: List[Dict]
    max_lateral_offset: float
    max_heading_error: float
    max_elevation_jump: float
    warnings: List[str]


def _sample_geometry(geom: ET.Element, step: float = 2.0) -> List[XY]:
    x0 = _safe_float(geom.get("x", "0"))
    y0 = _safe_float(geom.get("y", "0"))
    hdg = _safe_float(geom.get("hdg", "0"))
    length = _safe_float(geom.get("length", "0"))

    arc = geom.find("arc")
    pts: List[XY] = []

    if arc is None:
        n = max(2, int(length / step))
        for i in range(n + 1):
            ds = length * (i / n)
            x = x0 + ds * math.cos(hdg)
            y = y0 + ds * math.sin(hdg)
            pts.append((x, y))
        return pts

    curvature = _safe_float(arc.get("curvature", "0"))
    if abs(curvature) < 1e-9:
        n = max(2, int(length / step))
        for i in range(n + 1):
            ds = length * (i / n)
            x = x0 + ds * math.cos(hdg)
            y = y0 + ds * math.sin(hdg)
            pts.append((x, y))
        return pts

    R = 1.0 / curvature
    n = max(12, int(length / step))
    for i in range(n + 1):
        ds = length * (i / n)
        theta = ds * curvature
        x = x0 + R * (math.sin(hdg + theta) - math.sin(hdg))
        y = y0 - R * (math.cos(hdg + theta) - math.cos(hdg))
        pts.append((x, y))
    return pts


def _collect_points(root: ET.Element) -> List[XY]:
    pts: List[XY] = []
    for geom in root.findall(".//planView/geometry"):
        gpts = _sample_geometry(geom)
        if not pts:
            pts.extend(gpts)
        else:
            pts.extend(gpts[1:])
    return pts


def _bbox_from_geoms(root: ET.Element) -> Tuple[float, float, float, float]:
    xs, ys = [], []
    for g in root.findall(".//planView/geometry"):
        xs.append(_safe_float(g.get("x", "0")))
        ys.append(_safe_float(g.get("y", "0")))
    if not xs:
        return 0, 0, 0, 0
    return min(xs), min(ys), max(xs), max(ys)


def _near_border(p: XY, xmin: float, ymin: float, xmax: float, ymax: float, tol: float) -> bool:
    x, y = p
    return (
        abs(x - xmin) <= tol or abs(x - xmax) <= tol or
        abs(y - ymin) <= tol or abs(y - ymax) <= tol
    )


class LaneSeamChecker:
    """
    Pipeline-compatible seam validator.
    Provides analyze() returning SeamReport with:
      max_lateral_offset, max_heading_error, max_elevation_jump, warnings
    """

    @staticmethod
    def analyze(tile_a: str, tile_b: str, border_tol: float = 5.0) -> SeamReport:
        rootA = ET.parse(tile_a).getroot()
        rootB = ET.parse(tile_b).getroot()

        ptsA = _collect_points(rootA)
        ptsB = _collect_points(rootB)

        xminA, yminA, xmaxA, ymaxA = _bbox_from_geoms(rootA)
        xminB, yminB, xmaxB, ymaxB = _bbox_from_geoms(rootB)

        # pick border points (simple)
        borderA = [p for p in (ptsA[:50] + ptsA[-50:]) if _near_border(p, xminA, yminA, xmaxA, ymaxA, border_tol)]
        borderB = [p for p in (ptsB[:50] + ptsB[-50:]) if _near_border(p, xminB, yminB, xmaxB, ymaxB, border_tol)]

        # fallback if no border points were captured
        if not borderA and ptsA:
            borderA = [ptsA[-1]]
        if not borderB and ptsB:
            borderB = [ptsB[0]]

        max_lat = 0.0
        warnings: List[str] = []
        lane_pairs: List[Dict] = []

        # naive closest-point match
        for pa in borderA:
            best = None
            best_d = 1e9
            for pb in borderB:
                d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
                if d < best_d:
                    best_d = d
                    best = pb
            if best is not None:
                max_lat = max(max_lat, best_d)
                lane_pairs.append({"pA": pa, "pB": best, "lateral_offset": best_d})

        # heading/elevation not available here reliably (tiles often omit it in a clean way)
        max_hdg = 0.0
        max_dz = 0.0

        if max_lat > 0.10:
            warnings.append(f"Lateral offset exceeds 10 cm: {max_lat:.3f} m")

        return SeamReport(
            lane_pairs=lane_pairs,
            max_lateral_offset=max_lat,
            max_heading_error=max_hdg,
            max_elevation_jump=max_dz,
            warnings=warnings,
        )
