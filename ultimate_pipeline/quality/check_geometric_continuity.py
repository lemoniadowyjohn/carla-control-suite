# ultimate_pipeline/quality/check_geometric_continuity.py
# -*- coding: utf-8 -*-

"""
Geometric continuity check for OpenDRIVE road-to-road links.

Why:
- Many XODR files are topologically valid (successors exist, IDs exist) but still
  look broken in CARLA because the geometry at road boundaries does not match.
- CARLA does not weld meshes across roads. Even small pose mismatches can produce
  gaps/shards/overlaps.

What it checks:
- For each road that has a successor/predecessor link of elementType="road",
  compare end pose of A to start pose of B.
- Flag if:
  - Euclidean XY distance > eps_xy (meters)
  - Absolute heading difference > eps_hdg (radians)

Supports:
- planView geometries: line, arc, spiral (spiral numerically integrated)

Outputs:
- A dict report suitable for JSON writing.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Tuple


# ----------------------------
# Helpers
# ----------------------------


def _norm_angle(a: float) -> float:
    """Normalize angle to (-pi, pi]."""
    a = (a + math.pi) % (2.0 * math.pi) - math.pi
    if a <= -math.pi:
        a += 2.0 * math.pi
    return a


def _angle_diff(a: float, b: float) -> float:
    """Smallest signed difference a-b in (-pi, pi]."""
    return _norm_angle(a - b)


def _safe_float(x: Optional[str], default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except Exception:
        return default


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    hdg: float


@dataclass(frozen=True)
class Geometry:
    s0: float
    x0: float
    y0: float
    hdg0: float
    length: float
    kind: str
    curvature: float = 0.0
    curv_start: float = 0.0
    curv_end: float = 0.0
    poly_a: float = 0.0
    poly_b: float = 0.0
    poly_c: float = 0.0
    poly_d: float = 0.0
    param_a_u: float = 0.0
    param_b_u: float = 0.0
    param_c_u: float = 0.0
    param_d_u: float = 0.0
    param_a_v: float = 0.0
    param_b_v: float = 0.0
    param_c_v: float = 0.0
    param_d_v: float = 0.0
    param_p_range: str = "normalized"


# ----------------------------
# Geometry evaluation
# ----------------------------


def _pose_line(g: Geometry, s_local: float) -> Pose:
    x = g.x0 + math.cos(g.hdg0) * s_local
    y = g.y0 + math.sin(g.hdg0) * s_local
    return Pose(x=x, y=y, hdg=g.hdg0)


def _pose_arc(g: Geometry, s_local: float) -> Pose:
    k = g.curvature
    if abs(k) < 1e-12:
        return _pose_line(g, s_local)

    hdg = g.hdg0 + k * s_local
    dx_local = math.sin(k * s_local) / k
    dy_local = (1.0 - math.cos(k * s_local)) / k

    cos0 = math.cos(g.hdg0)
    sin0 = math.sin(g.hdg0)
    x = g.x0 + cos0 * dx_local - sin0 * dy_local
    y = g.y0 + sin0 * dx_local + cos0 * dy_local
    return Pose(x=x, y=y, hdg=hdg)


def _pose_spiral_numeric(g: Geometry, s_local: float, ds: float = 0.2) -> Pose:
    """
    Numerically integrate a spiral where curvature varies linearly
    from curv_start to curv_end over geometry length.
    """
    L = max(g.length, 1e-9)
    s_local = max(0.0, min(s_local, L))

    x = g.x0
    y = g.y0
    hdg = g.hdg0

    k0 = g.curv_start
    k1 = g.curv_end

    s = 0.0
    while s < s_local - 1e-12:
        step = min(ds, s_local - s)
        smid = s + 0.5 * step
        k_mid = k0 + (k1 - k0) * (smid / L)

        hdg_mid = hdg + k_mid * step

        x += math.cos(hdg) * step
        y += math.sin(hdg) * step

        hdg = hdg_mid
        s += step

    return Pose(x=x, y=y, hdg=hdg)


def _pose_poly3(g: Geometry, s_local: float) -> Pose:
    u = max(0.0, float(s_local))
    v = (
        float(g.poly_a)
        + float(g.poly_b) * u
        + float(g.poly_c) * u * u
        + float(g.poly_d) * u * u * u
    )
    dv_du = float(g.poly_b) + 2.0 * float(g.poly_c) * u + 3.0 * float(g.poly_d) * u * u

    cos0 = math.cos(g.hdg0)
    sin0 = math.sin(g.hdg0)
    x = g.x0 + cos0 * u - sin0 * v
    y = g.y0 + sin0 * u + cos0 * v
    hdg = _norm_angle(g.hdg0 + math.atan2(dv_du, 1.0))
    return Pose(x=x, y=y, hdg=hdg)


def _param_poly_eval(g: Geometry, s_local: float) -> Tuple[float, float, float, float]:
    """
    Return (u, v, du_dp, dv_dp) for paramPoly3 at local coordinate s_local.

    Assumption: pRange=="arcLength" means p in [0,length], otherwise normalized p in [0,1].
    This matches common OpenDRIVE usage and keeps evaluation deterministic.
    """
    L = max(float(g.length), 1e-9)
    s_local = max(0.0, min(float(s_local), L))
    p_range = str(g.param_p_range or "normalized").strip()
    if p_range == "arcLength":
        p = s_local
    else:
        p = s_local / L

    u = float(g.param_a_u) + float(g.param_b_u) * p + float(g.param_c_u) * p * p + float(g.param_d_u) * p * p * p
    v = float(g.param_a_v) + float(g.param_b_v) * p + float(g.param_c_v) * p * p + float(g.param_d_v) * p * p * p

    du_dp = float(g.param_b_u) + 2.0 * float(g.param_c_u) * p + 3.0 * float(g.param_d_u) * p * p
    dv_dp = float(g.param_b_v) + 2.0 * float(g.param_c_v) * p + 3.0 * float(g.param_d_v) * p * p
    return u, v, du_dp, dv_dp


def _pose_param_poly3(g: Geometry, s_local: float) -> Pose:
    u, v, du_dp, dv_dp = _param_poly_eval(g, s_local)
    cos0 = math.cos(g.hdg0)
    sin0 = math.sin(g.hdg0)
    x = g.x0 + cos0 * u - sin0 * v
    y = g.y0 + sin0 * u + cos0 * v
    if abs(du_dp) < 1e-12 and abs(dv_dp) < 1e-12:
        hdg = g.hdg0
    else:
        hdg = _norm_angle(g.hdg0 + math.atan2(dv_dp, du_dp))
    return Pose(x=x, y=y, hdg=hdg)


def _pose_for_geometry(g: Geometry, s_local: float) -> Pose:
    if g.kind == "line":
        return _pose_line(g, s_local)
    if g.kind == "arc":
        return _pose_arc(g, s_local)
    if g.kind == "spiral":
        return _pose_spiral_numeric(g, s_local)
    if g.kind == "poly3":
        return _pose_poly3(g, s_local)
    if g.kind == "paramPoly3":
        return _pose_param_poly3(g, s_local)
    return _pose_line(g, s_local)


# ----------------------------
# Parsing
# ----------------------------


def _parse_geometries(road_el: ET.Element) -> Tuple[List[Geometry], List[str]]:
    warnings: List[str] = []
    plan = road_el.find("planView")
    if plan is None:
        return [], ["missing planView"]

    geoms: List[Geometry] = []
    for geom_el in plan.findall("geometry"):
        s0 = _safe_float(geom_el.get("s"))
        x0 = _safe_float(geom_el.get("x"))
        y0 = _safe_float(geom_el.get("y"))
        hdg0 = _safe_float(geom_el.get("hdg"))
        length = _safe_float(geom_el.get("length"))

        kind = "unknown"
        curvature = 0.0
        curv_start = 0.0
        curv_end = 0.0
        poly_a = 0.0
        poly_b = 0.0
        poly_c = 0.0
        poly_d = 0.0
        param_a_u = 0.0
        param_b_u = 0.0
        param_c_u = 0.0
        param_d_u = 0.0
        param_a_v = 0.0
        param_b_v = 0.0
        param_c_v = 0.0
        param_d_v = 0.0
        param_p_range = "normalized"

        if geom_el.find("line") is not None:
            kind = "line"
        elif (arc := geom_el.find("arc")) is not None:
            kind = "arc"
            curvature = _safe_float(arc.get("curvature"))
        elif (spiral := geom_el.find("spiral")) is not None:
            kind = "spiral"
            curv_start = _safe_float(spiral.get("curvStart"))
            curv_end = _safe_float(spiral.get("curvEnd"))
        elif (poly := geom_el.find("poly3")) is not None:
            kind = "poly3"
            poly_a = _safe_float(poly.get("a"))
            poly_b = _safe_float(poly.get("b"))
            poly_c = _safe_float(poly.get("c"))
            poly_d = _safe_float(poly.get("d"))
        elif (param := geom_el.find("paramPoly3")) is not None:
            kind = "paramPoly3"
            param_a_u = _safe_float(param.get("aU"))
            param_b_u = _safe_float(param.get("bU"))
            param_c_u = _safe_float(param.get("cU"))
            param_d_u = _safe_float(param.get("dU"))
            param_a_v = _safe_float(param.get("aV"))
            param_b_v = _safe_float(param.get("bV"))
            param_c_v = _safe_float(param.get("cV"))
            param_d_v = _safe_float(param.get("dV"))
            param_p_range = (param.get("pRange") or "normalized").strip() or "normalized"
        else:
            warnings.append("unknown planView geometry type; using linear fallback")

        geoms.append(
            Geometry(
                s0=s0,
                x0=x0,
                y0=y0,
                hdg0=hdg0,
                length=length,
                kind=kind,
                curvature=curvature,
                curv_start=curv_start,
                curv_end=curv_end,
                poly_a=poly_a,
                poly_b=poly_b,
                poly_c=poly_c,
                poly_d=poly_d,
                param_a_u=param_a_u,
                param_b_u=param_b_u,
                param_c_u=param_c_u,
                param_d_u=param_d_u,
                param_a_v=param_a_v,
                param_b_v=param_b_v,
                param_c_v=param_c_v,
                param_d_v=param_d_v,
                param_p_range=param_p_range,
            )
        )

    geoms.sort(key=lambda g: g.s0)
    return geoms, warnings


def _road_length(road_el: ET.Element) -> float:
    return _safe_float(road_el.get("length"))


def _normalize_contact_point(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if raw in {"start", "end"}:
        return raw
    return None


def _endpoint_s(endpoint: str, road_length: float) -> float:
    return 0.0 if str(endpoint).strip().lower() == "start" else float(max(0.0, road_length))


def _source_endpoint_for_link(link_kind: str) -> str:
    # OpenDRIVE road links are anchored at the source road start for
    # predecessor links and at the source road end for successor links.
    return "start" if str(link_kind).strip().lower() == "predecessor" else "end"


def _expected_heading_delta_rad(source_endpoint: str, target_endpoint: str) -> float:
    # A start<->end join is same-direction along the reference line. A
    # start<->start or end<->end join is geometrically valid only when the
    # reference-line tangents face opposite directions at the shared point.
    return math.pi if str(source_endpoint) == str(target_endpoint) else 0.0


def _road_links(road_el: ET.Element) -> List[Tuple[str, str, str, Optional[str]]]:
    """
    Return list of (link_kind, elementType, elementId, contactPoint) for predecessor/successor.
    link_kind in {"predecessor","successor"}.
    """
    out: List[Tuple[str, str, str, Optional[str]]] = []
    link_el = road_el.find("link")
    if link_el is None:
        return out

    for kind in ("predecessor", "successor"):
        el = link_el.find(kind)
        if el is None:
            continue
        etype = (el.get("elementType") or "").strip()
        eid = (el.get("elementId") or "").strip()
        cp = _normalize_contact_point(el.get("contactPoint"))
        if etype and eid:
            out.append((kind, etype, eid, cp))
    return out


def _pose_at_s(geoms: List[Geometry], s_abs: float) -> Tuple[Pose, List[str]]:
    warnings: List[str] = []
    if not geoms:
        return Pose(0.0, 0.0, 0.0), ["no planView geometries"]

    s_abs = max(0.0, s_abs)

    g_sel = geoms[0]
    for g in geoms:
        if g.s0 <= s_abs + 1e-12:
            g_sel = g
        else:
            break

    s_local = s_abs - g_sel.s0
    s_local = max(0.0, min(s_local, max(g_sel.length, 0.0)))

    if g_sel.kind in ("unknown",):
        warnings.append(f"used fallback for geometry kind={g_sel.kind}")

    return _pose_for_geometry(g_sel, s_local), warnings


def _geometry_summary(g: Geometry, index: int) -> Dict[str, Any]:
    return {
        "index": int(index),
        "s0": float(g.s0),
        "x0": float(g.x0),
        "y0": float(g.y0),
        "hdg0": float(g.hdg0),
        "length": float(g.length),
        "kind": str(g.kind),
    }


def _classify_seam(*, seam_distance_m: float, hdg_delta_rad: float, eps_xy: float) -> str:
    ad = abs(float(hdg_delta_rad))
    d = float(seam_distance_m)
    if d < 0.5 and d > float(eps_xy):
        return "likely_rounding_drift"
    if d >= 0.5 and ad > 2.6:
        return "likely_reversed_segment"
    if d >= 0.5 and ad < 0.35:
        return "likely_bad_length_or_s"
    return "uncertain"


def _road_sort_key(road_id: str) -> Tuple[int, Any]:
    try:
        return (0, int(str(road_id)))
    except Exception:
        return (1, str(road_id))


def _geometry_from_element(geom_el: ET.Element) -> Geometry:
    s0 = _safe_float(geom_el.get("s"))
    x0 = _safe_float(geom_el.get("x"))
    y0 = _safe_float(geom_el.get("y"))
    hdg0 = _safe_float(geom_el.get("hdg"))
    length = _safe_float(geom_el.get("length"))

    kind = "unknown"
    curvature = 0.0
    curv_start = 0.0
    curv_end = 0.0
    poly_a = poly_b = poly_c = poly_d = 0.0
    param_a_u = param_b_u = param_c_u = param_d_u = 0.0
    param_a_v = param_b_v = param_c_v = param_d_v = 0.0
    param_p_range = "normalized"

    if geom_el.find("line") is not None:
        kind = "line"
    elif (arc := geom_el.find("arc")) is not None:
        kind = "arc"
        curvature = _safe_float(arc.get("curvature"))
    elif (spiral := geom_el.find("spiral")) is not None:
        kind = "spiral"
        curv_start = _safe_float(spiral.get("curvStart"))
        curv_end = _safe_float(spiral.get("curvEnd"))
    elif (poly := geom_el.find("poly3")) is not None:
        kind = "poly3"
        poly_a = _safe_float(poly.get("a"))
        poly_b = _safe_float(poly.get("b"))
        poly_c = _safe_float(poly.get("c"))
        poly_d = _safe_float(poly.get("d"))
    elif (param := geom_el.find("paramPoly3")) is not None:
        kind = "paramPoly3"
        param_a_u = _safe_float(param.get("aU"))
        param_b_u = _safe_float(param.get("bU"))
        param_c_u = _safe_float(param.get("cU"))
        param_d_u = _safe_float(param.get("dU"))
        param_a_v = _safe_float(param.get("aV"))
        param_b_v = _safe_float(param.get("bV"))
        param_c_v = _safe_float(param.get("cV"))
        param_d_v = _safe_float(param.get("dV"))
        param_p_range = (param.get("pRange") or "normalized").strip() or "normalized"

    return Geometry(
        s0=s0,
        x0=x0,
        y0=y0,
        hdg0=hdg0,
        length=length,
        kind=kind,
        curvature=curvature,
        curv_start=curv_start,
        curv_end=curv_end,
        poly_a=poly_a,
        poly_b=poly_b,
        poly_c=poly_c,
        poly_d=poly_d,
        param_a_u=param_a_u,
        param_b_u=param_b_u,
        param_c_u=param_c_u,
        param_d_u=param_d_u,
        param_a_v=param_a_v,
        param_b_v=param_b_v,
        param_c_v=param_c_v,
        param_d_v=param_d_v,
        param_p_range=param_p_range,
    )


def recompute_geometry_starts_chained_inplace(root: ET.Element, *, eps_change: float = 1e-12) -> int:
    """
    Deterministically chain geometry starts to previous geometry end poses.
    Only updates x/y/hdg of geometry[i>0]; does not change kind/length.
    """
    updated = 0
    for road in root.findall("road"):
        plan = road.find("planView")
        if plan is None:
            continue
        geoms_el = list(plan.findall("geometry"))
        if len(geoms_el) < 2:
            continue
        geoms_el.sort(key=lambda g: _safe_float(g.get("s")))
        models = [_geometry_from_element(g) for g in geoms_el]
        # Spatial gap threshold: if the current geometry's declared start is
        # farther than this from the previous geometry's endpoint, it is an
        # intentional planView discontinuity (anchor point) used to pin the
        # road's endpoint for link connectivity. Never overwrite it.
        _ANCHOR_PRESERVE_GAP_M = 0.5

        for i in range(1, len(geoms_el)):
            prev_model = models[i - 1]
            prev_end = _pose_for_geometry(prev_model, max(float(prev_model.length), 0.0))
            cur_model = models[i]

            # Guard: preserve spatial anchors — do not reposition geometry
            # that is intentionally placed far from the previous endpoint.
            spatial_gap = math.hypot(
                float(cur_model.x0) - float(prev_end.x),
                float(cur_model.y0) - float(prev_end.y),
            )
            if spatial_gap > _ANCHOR_PRESERVE_GAP_M:
                # Keep original x/y/hdg; still update the chain model so
                # subsequent geometries compute correctly from this anchor.
                models[i] = cur_model
                continue

            dx = abs(float(cur_model.x0) - float(prev_end.x))
            dy = abs(float(cur_model.y0) - float(prev_end.y))
            dh = abs(_angle_diff(float(cur_model.hdg0), float(prev_end.hdg)))
            if dx > eps_change or dy > eps_change or dh > eps_change:
                geoms_el[i].set("x", f"{float(prev_end.x):.12f}")
                geoms_el[i].set("y", f"{float(prev_end.y):.12f}")
                geoms_el[i].set("hdg", f"{float(_norm_angle(prev_end.hdg)):.12f}")
                updated += 1
            models[i] = replace(cur_model, x0=float(prev_end.x), y0=float(prev_end.y), hdg0=float(_norm_angle(prev_end.hdg)))
    return updated


def auto_repair_tiny_planview_seams_in_file(
    xodr_path: str,
    *,
    eps_xy: float = 0.2,
    max_repair_seam_m: float = 0.05,
) -> Dict[str, Any]:
    before = check_planview_internal_seams(xodr_path, eps_xy=eps_xy)
    if bool(before.get("ok", False)):
        return {
            "applied": False,
            "fixed": True,
            "reason": "no_seams",
            "before": before,
            "after": before,
            "updated_geometry_count": 0,
            "max_repair_seam_m": float(max_repair_seam_m),
        }
    max_seam = float(before.get("max_seam_m", 0.0) or 0.0)
    if max_seam > float(max_repair_seam_m):
        return {
            "applied": False,
            "fixed": False,
            "reason": "max_seam_exceeds_threshold",
            "before": before,
            "after": before,
            "updated_geometry_count": 0,
            "max_repair_seam_m": float(max_repair_seam_m),
        }

    tree = ET.parse(xodr_path)
    root = tree.getroot()
    updated = recompute_geometry_starts_chained_inplace(root)
    tree.write(xodr_path, encoding="utf-8", xml_declaration=True)
    after = check_planview_internal_seams(xodr_path, eps_xy=eps_xy)
    return {
        "applied": True,
        "fixed": bool(after.get("ok", False)),
        "reason": "attempted",
        "before": before,
        "after": after,
        "updated_geometry_count": int(updated),
        "max_repair_seam_m": float(max_repair_seam_m),
    }


# ----------------------------
# Public API
# ----------------------------


def check_geometric_continuity(
    xodr_path: str,
    eps_xy: float = 0.05,
    eps_hdg: float = 0.01,
) -> Dict[str, Any]:
    """
    Check geometric continuity at road boundaries for ordinary road-to-road links.

    Links involving junction connector roads are reported separately because
    OpenDRIVE junction routing is governed by <junction><connection><laneLink>
    semantics. Their reference lines may join at lane centers rather than at
    the non-junction road reference line, so they are diagnostic evidence for
    G4/G6-style junction-lane audits, not hard failures of this generic road
    reference-line gate.

    Returns a report dict:
      {
        "ok": bool,
        "eps_xy": float,
        "eps_hdg": float,
        "num_roads": int,
        "num_links_checked": int,
        "num_junction_connector_links_checked": int,
        "num_issues": int,
        "num_junction_connector_issues": int,
        "issues": [
           {
             "from_road": "12",
             "to_road": "13",
             "link_kind": "successor",
             "dx": ...,
             "dy": ...,
             "dxy": ...,
             "dhdg": ...,
             "from_pose_end": {"x":..,"y":..,"hdg":..},
             "to_pose_start": {"x":..,"y":..,"hdg":..},
             "warnings": [...]
           }, ...
        ],
        "warnings": [...]
      }
    """
    report: Dict[str, Any] = {
        "ok": True,
        "eps_xy": eps_xy,
        "eps_hdg": eps_hdg,
        "num_roads": 0,
        "num_links_checked": 0,
        "num_junction_connector_links_checked": 0,
        "num_issues": 0,
        "num_junction_connector_issues": 0,
        "issues": [],
        "junction_connector_issues": [],
        "warnings": [],
    }

    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as e:
        report["ok"] = False
        report["warnings"].append(f"failed to parse xodr: {e}")
        return report

    roads = root.findall("road")
    report["num_roads"] = len(roads)

    road_by_id: Dict[str, ET.Element] = {}
    geom_cache: Dict[str, Tuple[List[Geometry], List[str]]] = {}

    for r in roads:
        rid = (r.get("id") or "").strip()
        if rid:
            road_by_id[rid] = r

    def get_geoms(rid: str) -> Tuple[List[Geometry], List[str]]:
        if rid in geom_cache:
            return geom_cache[rid]
        r = road_by_id.get(rid)
        if r is None:
            geom_cache[rid] = ([], [f"missing road id={rid}"])
        else:
            geom_cache[rid] = _parse_geometries(r)
        return geom_cache[rid]

    issues: List[Dict[str, Any]] = []
    junction_connector_issues: List[Dict[str, Any]] = []
    warnings_global: List[str] = []

    for r in roads:
        rid = (r.get("id") or "").strip()
        if not rid:
            continue

        links = _road_links(r)
        for link_kind, etype, eid, contact_point in links:
            if etype != "road":
                continue
            if eid not in road_by_id:
                issues.append(
                    {
                        "from_road": rid,
                        "to_road": eid,
                        "link_kind": link_kind,
                        "error": f"linked road id not found: {eid}",
                        "warnings": [],
                    }
                )
                continue

            target_road = road_by_id[eid]
            source_is_junction_connector = str(r.get("junction") or "-1").strip() != "-1"
            target_is_junction_connector = str(target_road.get("junction") or "-1").strip() != "-1"
            is_junction_connector_link = source_is_junction_connector or target_is_junction_connector

            geoms_a, warn_a = get_geoms(rid)
            geoms_b, warn_b = get_geoms(eid)

            len_a = _road_length(r)
            len_b = _road_length(target_road)

            from_endpoint = _source_endpoint_for_link(link_kind)
            to_endpoint = contact_point or "start"
            pose_from, warn_eval_a = _pose_at_s(geoms_a, _endpoint_s(from_endpoint, len_a))
            pose_to, warn_eval_b = _pose_at_s(geoms_b, _endpoint_s(to_endpoint, len_b))
            expected_heading_delta = _expected_heading_delta_rad(from_endpoint, to_endpoint)

            dx = pose_to.x - pose_from.x
            dy = pose_to.y - pose_from.y
            dxy = math.hypot(dx, dy)
            dhdg = abs(_angle_diff(pose_to.hdg, pose_from.hdg + expected_heading_delta))

            if is_junction_connector_link:
                report["num_junction_connector_links_checked"] += 1
            else:
                report["num_links_checked"] += 1

            warn = []
            warn.extend(warn_a)
            warn.extend(warn_b)
            warn.extend(warn_eval_a)
            warn.extend(warn_eval_b)

            # NaN/Inf propagated from a corrupt planView attribute makes `dxy`/`dhdg`
            # non-finite; a magnitude comparison against NaN is always False in
            # IEEE-754 (`nan > eps_xy` is False), so the check below would silently
            # never fire. Guard explicitly instead of relying on the magnitude
            # comparison to catch it.
            if not math.isfinite(dxy) or not math.isfinite(dhdg) or dxy > eps_xy or dhdg > eps_hdg:
                record = {
                    "from_road": rid,
                    "to_road": eid,
                    "link_kind": link_kind,
                    "contact_point": contact_point,
                    "from_endpoint": from_endpoint,
                    "to_endpoint": to_endpoint,
                    "source_is_junction_connector": source_is_junction_connector,
                    "target_is_junction_connector": target_is_junction_connector,
                    "dx": dx,
                    "dy": dy,
                    "dxy": dxy,
                    "dhdg": dhdg,
                    "expected_heading_delta_rad": expected_heading_delta,
                    "from_pose": {"x": pose_from.x, "y": pose_from.y, "hdg": pose_from.hdg},
                    "to_pose": {"x": pose_to.x, "y": pose_to.y, "hdg": pose_to.hdg},
                    "warnings": warn,
                }
                if is_junction_connector_link:
                    junction_connector_issues.append(record)
                else:
                    issues.append(record)

    report["issues"] = issues
    report["junction_connector_issues"] = junction_connector_issues
    report["num_issues"] = len(issues)
    report["num_junction_connector_issues"] = len(junction_connector_issues)
    report["ok"] = len(issues) == 0

    for rid, (_, warns) in geom_cache.items():
        for w in warns:
            warnings_global.append(f"road {rid}: {w}")
    report["warnings"] = sorted(set(report["warnings"] + warnings_global))

    return report


def check_planview_internal_seams(
    xodr_path: str,
    eps_xy: float = 0.2,
    eps_hdg_only_deg: float = 5.0,
) -> Dict[str, Any]:
    """
    Check continuity between consecutive geometries within each road planView.

    A seam is reported when the previous geometry endpoint and next geometry
    start point are farther than eps_xy meters.

    Additionally (purely additive, does not affect `ok`/`seams`/`num_seams`/`max_seam_m`):
    when position IS continuous (dxy <= eps_xy) but the heading jumps by more than
    `eps_hdg_only_deg` degrees, that pair is recorded in `heading_only_discontinuities`.
    This case was previously silently skipped entirely -- `hdg_delta_rad` was computed but
    only ever used to classify an already-detected position seam, never checked on its own.
    A position-continuous heading jump is a real visible kink in the road centerline (the
    road doesn't jump in space, but its tangent direction snaps to a new angle instantly).
    Kept separate from `seams`/`ok` deliberately: this function participates in a live
    pipeline gate (stage_06_links.py, stage_09_tiling.py) with auto-repair triggering and
    UP_STRICT_QUALITY_GATES blocking semantics -- changing existing pass/fail behavior here
    needs an explicit decision, not a side effect of adding new diagnostic visibility.
    """
    report: Dict[str, Any] = {
        "ok": True,
        "eps_xy_m": float(eps_xy),
        "eps_hdg_only_deg": float(eps_hdg_only_deg),
        "num_roads": 0,
        "num_pairs_checked": 0,
        "num_seams": 0,
        "roads_checked": 0,
        "seams_found": 0,
        "max_seam_m": 0.0,
        "worst_road_id": "",
        "seams": [],
        "heading_only_discontinuities": [],
        "num_heading_only_discontinuities": 0,
        "warnings": [],
    }

    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as e:
        report["ok"] = False
        report["warnings"].append(f"failed to parse xodr: {e}")
        return report

    seams: List[Dict[str, Any]] = []
    roads = root.findall("road")
    report["num_roads"] = len(roads)
    roads_checked = 0

    for road in roads:
        rid = (road.get("id") or "").strip()
        geoms, warns = _parse_geometries(road)
        for w in warns:
            report["warnings"].append(f"road {rid}: {w}")
        if len(geoms) < 2:
            continue
        roads_checked += 1

        for i in range(len(geoms) - 1):
            g_prev = geoms[i]
            g_next = geoms[i + 1]
            pose_end = _pose_for_geometry(g_prev, max(float(g_prev.length), 0.0))
            next_start_pose = Pose(x=float(g_next.x0), y=float(g_next.y0), hdg=float(g_next.hdg0))
            dxy = math.hypot(float(next_start_pose.x) - float(pose_end.x), float(next_start_pose.y) - float(pose_end.y))
            hdg_delta_rad = _angle_diff(float(next_start_pose.hdg), float(pose_end.hdg))
            report["num_pairs_checked"] += 1
            if dxy <= float(eps_xy):
                if math.degrees(abs(float(hdg_delta_rad))) > float(eps_hdg_only_deg):
                    report["heading_only_discontinuities"].append(
                        {
                            "road_id": rid,
                            "from_geom_index": int(i),
                            "to_geom_index": int(i + 1),
                            "xy_gap_m": float(dxy),
                            "hdg_delta_rad": float(hdg_delta_rad),
                            "hdg_delta_deg": float(math.degrees(hdg_delta_rad)),
                        }
                    )
                continue
            classification = _classify_seam(
                seam_distance_m=float(dxy),
                hdg_delta_rad=float(hdg_delta_rad),
                eps_xy=float(eps_xy),
            )
            from_s_end = float(g_prev.s0 + max(float(g_prev.length), 0.0))
            to_s = float(g_next.s0)
            s_gap = to_s - from_s_end  # Should be 0 for properly chained geometries
            seams.append(
                {
                    "road_id": rid,
                    "from_geom_index": int(i),
                    "to_geom_index": int(i + 1),
                    "seam_distance_m": float(dxy),
                    "from_s": float(g_prev.s0),
                    "from_s_end": from_s_end,
                    "to_s": to_s,
                    "s_gap": float(s_gap),
                    "prev_geometry": _geometry_summary(g_prev, i),
                    "next_geometry": _geometry_summary(g_next, i + 1),
                    "prev_end_pose": {
                        "x": float(pose_end.x),
                        "y": float(pose_end.y),
                        "hdg": float(_norm_angle(pose_end.hdg)),
                    },
                    "next_start_pose": {
                        "x": float(next_start_pose.x),
                        "y": float(next_start_pose.y),
                        "hdg": float(_norm_angle(next_start_pose.hdg)),
                    },
                    "hdg_delta_rad": float(hdg_delta_rad),
                    "s_gap_indicates_discontinuity": abs(s_gap) > 1e-6,
                    "classification": str(classification),
                }
            )

    seams.sort(
        key=lambda s: (
            _road_sort_key(str(s.get("road_id", ""))),
            int(s.get("from_geom_index", 0)),
            int(s.get("to_geom_index", 0)),
        )
    )
    report["seams"] = seams
    report["num_seams"] = len(seams)
    report["roads_checked"] = int(roads_checked)
    report["seams_found"] = int(len(seams))
    report["num_heading_only_discontinuities"] = len(report["heading_only_discontinuities"])
    if seams:
        worst = max(seams, key=lambda s: float(s.get("seam_distance_m", 0.0)))
        report["max_seam_m"] = float(worst.get("seam_distance_m", 0.0))
        report["worst_road_id"] = str(worst.get("road_id", ""))
    else:
        report["max_seam_m"] = 0.0
        report["worst_road_id"] = ""
    report["ok"] = len(seams) == 0
    report["warnings"] = sorted(set(report["warnings"]))
    return report


if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("xodr_path")
    ap.add_argument("--eps-xy", type=float, default=0.05)
    ap.add_argument("--eps-hdg", type=float, default=0.01)
    args = ap.parse_args()

    rep = check_geometric_continuity(args.xodr_path, eps_xy=args.eps_xy, eps_hdg=args.eps_hdg)
    print(json.dumps(rep, indent=2))
    sys.exit(0 if rep.get("ok", False) else 2)
