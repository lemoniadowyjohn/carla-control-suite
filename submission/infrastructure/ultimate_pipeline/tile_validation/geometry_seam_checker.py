# ultimate_pipeline/tile_validation/geometry_seam_checker.py
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Dict, Optional, Tuple


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
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


def _geometry_endpoint(geom: ET.Element) -> Tuple[float, float, float]:
    """Return (x_end, y_end, hdg_end) for a <geometry> element (line/arc).
    Falls back to treating unknown geometry types as straight line."""
    x0 = _safe_float(geom.get("x"))
    y0 = _safe_float(geom.get("y"))
    hdg0 = _safe_float(geom.get("hdg"))
    length = _safe_float(geom.get("length"))

    arc = geom.find("arc")
    if arc is None:
        # Straight line
        x1 = x0 + length * math.cos(hdg0)
        y1 = y0 + length * math.sin(hdg0)
        return x1, y1, hdg0

    curvature = _safe_float(arc.get("curvature"))
    if abs(curvature) < 1e-12:
        x1 = x0 + length * math.cos(hdg0)
        y1 = y0 + length * math.sin(hdg0)
        return x1, y1, hdg0

    # Arc endpoint
    R = 1.0 / curvature
    theta = length * curvature
    x1 = x0 + R * (math.sin(hdg0 + theta) - math.sin(hdg0))
    y1 = y0 - R * (math.cos(hdg0 + theta) - math.cos(hdg0))
    hdg1 = hdg0 + theta
    return x1, y1, hdg1


class GeometrySeamChecker:
    """Fast seam continuity checker for tiled OpenDRIVE maps.

    Checks:
      • planView endpoint position continuity (end of last geometry vs start of first geometry)
      • heading continuity (wrapped angle difference)
      • elevationProfile continuity (first elevation 'a' or legacy 'z')
    """

    @staticmethod
    def _last_geometry(root: ET.Element) -> Optional[ET.Element]:
        roads = root.findall("./road")
        if not roads:
            return None
        plan = roads[-1].find("./planView")
        if plan is None:
            return None
        geoms = plan.findall("geometry")
        return geoms[-1] if geoms else None

    @staticmethod
    def _first_geometry(root: ET.Element) -> Optional[ET.Element]:
        road = root.find("./road")
        if road is None:
            return None
        plan = road.find("./planView")
        if plan is None:
            return None
        return plan.find("geometry")

    @staticmethod
    def _first_elevation_a(root: ET.Element) -> float:
        elev = root.find(".//elevationProfile/elevation")
        if elev is None:
            return 0.0
        # OpenDRIVE elevation uses a/b/c/d; some legacy tools write z.
        if elev.get("a") is not None:
            return _safe_float(elev.get("a", "0.0"))
        return _safe_float(elev.get("z", "0.0"))

    @staticmethod
    def check(tile_a_path: str, tile_b_path: str) -> Dict:
        try:
            root_a = ET.parse(tile_a_path).getroot()
            root_b = ET.parse(tile_b_path).getroot()
        except Exception as e:
            return {"status": "fail", "error": f"XML parse error: {e}"}

        ga = GeometrySeamChecker._last_geometry(root_a)
        gb = GeometrySeamChecker._first_geometry(root_b)

        if ga is None or gb is None:
            return {"status": "fail", "error": "Missing geometry at seam"}

        # Compare END of last geometry of A vs START of first geometry of B
        ax, ay, ah = _geometry_endpoint(ga)

        bx = _safe_float(gb.get("x"))
        by = _safe_float(gb.get("y"))
        bh = _safe_float(gb.get("hdg"))

        planar_jump = math.hypot(ax - bx, ay - by)
        heading_jump = abs(_angle_diff(ah, bh))

        za = GeometrySeamChecker._first_elevation_a(root_a)
        zb = GeometrySeamChecker._first_elevation_a(root_b)
        elev_jump = abs(za - zb)

        # CARLA-safe thresholds (heuristic)
        if planar_jump < 0.15 and heading_jump < 0.05 and elev_jump < 0.10:
            status = "ok"
        elif planar_jump < 0.50 and heading_jump < 0.15 and elev_jump < 0.30:
            status = "warn"
        else:
            status = "fail"

        return {
            "status": status,
            "planar_jump_m": planar_jump,
            "heading_jump_rad": heading_jump,
            "elevation_jump_m": elev_jump,
        }
