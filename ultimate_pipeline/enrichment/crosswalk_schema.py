# ultimate_pipeline/enrichment/crosswalk_schema.py
"""CARLA 0.9.16 crosswalk <object> schema codec (R05 lemma).

Mirrors exactly what libCarla 0.9.16 (tag 294096eb) does in
Map::GetAllCrosswalkZones for `<outline><cornerLocal u v z>` corners:

  g     = theta - hdg                       # radians
  pivot = (bx + t*sin(theta), by - t*cos(theta))
  world.x = pivot.x + u*cos(g) + v*sin(g)   # CARLA TransformPoint + the
  world.y = pivot.y + u*sin(g) - v*cos(g)   # "Unreal Y axis hack" (v -> -v)
  world.z = pivot.z + z

encode() is the exact inverse of decode() (the rotation matrix is its own
inverse), so the round trip is lossless for any (s, t, hdg).

The base pose (b, theta) is the reference-line pose at `s` evaluated from the
XODR planView with opendrive_geometry (same math as libCarla geometry
primitives).
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

from opendrive_geometry.primitives import (
    evaluate_arc,
    evaluate_line,
    evaluate_param_poly3,
    evaluate_poly3,
    evaluate_spiral,
)
from opendrive_geometry.model import Pose2D

LocalCorner = Tuple[float, float, float]  # (u, v, z)
WorldCorner = Tuple[float, float, float]  # (x, y, z)


# ---------------------------------------------------------------------------
# Reference line pose at s (mirrors libcarla planView geometry evaluation)
# ---------------------------------------------------------------------------

def _road_length(road: ET.Element) -> float:
    try:
        return float(road.get("length", "0") or "0")
    except (TypeError, ValueError):
        return 0.0


def _clamp_s(road: ET.Element, s: float) -> float:
    return max(0.0, min(s, _road_length(road)))


def reference_pose_at_s(road: ET.Element, s: float) -> Optional[Pose2D]:
    """Pose (x, y, heading) of the road reference line at arc length `s`.

    Returns None when the road has no planView or `s` falls inside no
    geometry (gap). `s` is clamped to the road length; per-geometry the
    evaluation range is enforced by the primitives.
    """
    plan = road.find("planView")
    if plan is None:
        return None
    geoms = plan.findall("geometry")
    if not geoms:
        return None
    s = _clamp_s(road, s)
    best: Optional[Tuple[float, ET.Element]] = None
    for geom in geoms:
        try:
            gs = float(geom.get("s", "0") or "0")
        except (TypeError, ValueError):
            continue
        glen = float(geom.get("length", "0") or "0")
        if gs <= s <= gs + glen + 1e-9:
            if best is None or gs > best[0]:
                best = (gs, geom)
    if best is None:
        return None
    gs, geom = best
    x0 = float(geom.get("x", "0") or "0")
    y0 = float(geom.get("y", "0") or "0")
    hdg0 = float(geom.get("hdg", "0") or "0")
    glen = float(geom.get("length", "0") or "0")
    ds = s - gs

    for prim in ("line", "arc", "spiral", "poly3", "paramPoly3"):
        el = geom.find(prim)
        if el is None:
            continue
        if prim == "line":
            return evaluate_line(x0, y0, hdg0, glen, ds)
        if prim == "arc":
            curv = float(el.get("curvature", "0") or "0")
            return evaluate_arc(x0, y0, hdg0, glen, curv, ds)
        if prim == "spiral":
            cs = float(el.get("curvStart", "0") or "0")
            ce = float(el.get("curvEnd", "0") or "0")
            return evaluate_spiral(x0, y0, hdg0, glen, cs, ce, ds)
        if prim == "poly3":
            co = [float(el.get(a, "0") or "0") for a in ("a", "b", "c", "d")]
            return evaluate_poly3(x0, y0, hdg0, glen, *co, ds)
        if prim == "paramPoly3":
            co = [float(el.get(a, "0") or "0")
                  for a in ("aU", "bU", "cU", "dU", "aV", "bV", "cV", "dV")]
            raw = (el.get("pRange") or "arcLength").strip().lower()
            p_range = "normalized" if raw == "normalized" else "arcLength"
            return evaluate_param_poly3(x0, y0, hdg0, glen, *co, p_range, ds)
    # Geometry element with no recognized primitive child.
    return None


# ---------------------------------------------------------------------------
# CARLA 0.9.16 GetAllCrosswalkZones codec
# ---------------------------------------------------------------------------

def _pivot(pose: Pose2D, t: float) -> Tuple[float, float]:
    """Pivot = base + lateral t along direction (sin theta, -cos theta)."""
    theta = pose.hdg
    return pose.x + t * math.sin(theta), pose.y - t * math.cos(theta)


def carla_local_corners(
    world_outline: List[WorldCorner],
    pose: Pose2D,
    t: float,
    hdg: float,
) -> List[LocalCorner]:
    """Encode world corners into the CARLA 0.9.16 local (u, v, z) frame.

    `pose` is the reference-line pose at the object s; `t` the object's
    lateral offset (S07 t_center); `hdg` the object heading attribute (rad).
    """
    theta = pose.hdg
    g = theta - hdg
    cg, sg = math.cos(g), math.sin(g)
    px, py = _pivot(pose, t)
    out: List[LocalCorner] = []
    for (x, y, z) in world_outline:
        dx = x - px
        dy = y - py
        u = dx * cg + dy * sg
        v = dx * sg - dy * cg
        out.append((u, v, z))
    return out


def carla_world_corners(
    local_outline: List[LocalCorner],
    pose: Pose2D,
    t: float,
    hdg: float,
) -> List[WorldCorner]:
    """Decode local corners back to world (mirror of GetAllCrosswalkZones)."""
    theta = pose.hdg
    g = theta - hdg
    cg, sg = math.cos(g), math.sin(g)
    px, py = _pivot(pose, t)
    out: List[WorldCorner] = []
    for (u, v, z) in local_outline:
        out.append((px + u * cg + v * sg, py + u * sg - v * cg, z))
    return out