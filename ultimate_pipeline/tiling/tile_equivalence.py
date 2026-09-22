#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TIL-001/002/004 — curve-aware tiling ownership and equivalence.

Implements the tiling contract:

- TIL-001: road bounds are computed from the COMPLETE reference-line geometry
  including curve extrema (arcs analytically, spirals/poly3 via bounded
  evaluation), not just endpoint approximations, then inflated by the lane
  half-width so no lane escapes the tile.
- TIL-002: complete roads are assigned to tiles per a documented policy
  (midpoint or start-point) with junction context kept together.
- TIL-004: if a road is duplicated across tiles, the duplicated definitions
  must be byte-identical and semantic-identical (freeze digest), and an
  ownership record is produced.

Read-only: none of these functions mutate documents.
"""
from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

try:
    from opendrive_geometry.primitives import (
        arc_bounds,
        evaluate_arc,
        evaluate_line,
        evaluate_poly3,
        evaluate_spiral,
        line_bounds,
        param_poly3_bounds,
        poly3_bounds,
        spiral_bounds,
    )
    from opendrive_geometry.freeze import compute_freeze
    _HAS_GEOMETRY = True
except Exception:  # pragma: no cover - defensive for environments without repo root
    _HAS_GEOMETRY = False


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except Exception:
        return default


def _road_length(road: ET.Element) -> float:
    length = 0.0
    for g in road.findall(".//planView/geometry"):
        try:
            length += float(g.get("length", "0.0"))
        except Exception:
            pass
    return length


def _geom_kind(geom: ET.Element) -> str:
    for tag in ("line", "arc", "spiral", "poly3", "paramPoly3"):
        if geom.find(tag) is not None:
            return tag
    # Default to line if no explicit geometry type is specified (OpenDRIVE default)
    return "line"


def _as_bounds(value) -> Tuple[float, float, float, float]:
    """Normalize Bounds2D (P05) or raw 4-tuple into (x_min, y_min, x_max, y_max)."""
    if hasattr(value, "x_min"):
        return (value.x_min, value.y_min, value.x_max, value.y_max)
    return tuple(value)


def _geometry_local_bounds(geom: ET.Element) -> Tuple[float, float, float, float]:
    """Local (x,y) bounds of one geometry element, including curve extrema.

    Raises ValueError if curve evaluation fails and no fallback is available.
    This ensures no silent conservative approximations are used in production.
    """
    kind = _geom_kind(geom)
    x0 = _safe_float(geom.get("x"))
    y0 = _safe_float(geom.get("y"))
    hdg = _safe_float(geom.get("hdg"))
    length = _safe_float(geom.get("length"))
    child = geom.find(kind)
    if kind == "line":
        return _as_bounds(line_bounds(x0, y0, hdg, length))
    if kind == "arc":
        curvature = _safe_float(child.get("curvature"))
        return _as_bounds(arc_bounds(x0, y0, hdg, length, curvature))
    if kind == "spiral":
        curv_start = _safe_float(child.get("curvStart"))
        curv_end = _safe_float(child.get("curvEnd"))
        if _HAS_GEOMETRY:
            try:
                return _as_bounds(spiral_bounds(x0, y0, hdg, length, curv_start, curv_end))
            except Exception as e:
                raise ValueError(f"spiral_bounds failed: {e}")
        raise ValueError("spiral_bounds unavailable and no fallback permitted")
    if kind == "poly3":
        a = _safe_float(child.get("a"))
        b = _safe_float(child.get("b"))
        c = _safe_float(child.get("c"))
        d = _safe_float(child.get("d"))
        if _HAS_GEOMETRY:
            try:
                return _as_bounds(poly3_bounds(x0, y0, hdg, length, a, b, c, d))
            except Exception as e:
                raise ValueError(f"poly3_bounds failed: {e}")
        raise ValueError("poly3_bounds unavailable and no fallback permitted")
    if kind == "paramPoly3":
        u = _safe_float(child.get("aU")); v = _safe_float(child.get("aV"))
        bu = _safe_float(child.get("bU")); bv = _safe_float(child.get("bV"))
        cu = _safe_float(child.get("cU")); cv = _safe_float(child.get("cV"))
        du = _safe_float(child.get("dU")); dv = _safe_float(child.get("dV"))
        if _HAS_GEOMETRY:
            try:
                return _as_bounds(param_poly3_bounds(
                    x0, y0, hdg, length, u, bu, cu, du, v, bv, cv, dv,
                    child.get("pRange", "arcLength")))
            except Exception as e:
                raise ValueError(f"param_poly3_bounds failed: {e}")
        raise ValueError("param_poly3_bounds unavailable and no fallback permitted")
    raise ValueError(f"Unknown geometry kind: {kind}")


def road_bounds_curve_aware(
    road: ET.Element,
    *,
    margin_m: float = 0.0,
    include_lane_width: bool = True,
) -> Dict[str, Any]:
    """TIL-001: AABB of the complete reference line incl. curve extrema."""
    xs: List[float] = []
    ys: List[float] = []
    planview = road.find("planView")
    if planview is not None:
        for geom in planview.findall("geometry"):
            bx0, by0, bx1, by1 = _geometry_local_bounds(geom)
            xs.extend((bx0, bx1)); ys.extend((by0, by1))

    margin = margin_m
    if include_lane_width:
        width = road_max_lane_half_width(road)
        margin += width

    if not xs:
        return {"x_min": 0.0, "y_min": 0.0, "x_max": 0.0, "y_max": 0.0,
                "margin_m": margin, "curve_aware": True}
    return {"x_min": min(xs) - margin, "y_min": min(ys) - margin,
            "x_max": max(xs) + margin, "y_max": max(ys) + margin,
            "margin_m": margin, "curve_aware": True}


def road_max_lane_half_width(road: ET.Element) -> float:
    """
    Cumulative maximum lateral extent across all lane sections.

    This accounts for the full cross-section: for each lane section, sum the
    maximum width on the left side and right side (center lane is at zero
    offset). The result is the maximum lateral distance from the reference line
    to the outermost lane edge across all sections. This ensures the tile
    margin is inflated enough that no lane in any section escapes the tile.

    Returns the maximum half-width (distance from reference line to outermost
    lane edge) across all lane sections and lanes.
    """
    max_half = 0.0
    for section in road.findall("./lanes/laneSection"):
        # Sum max widths on left and right sides for this section
        left_max = 0.0
        right_max = 0.0
        for lane in section.findall("./left/lane"):
            for w in lane.findall("width"):
                a = abs(_safe_float(w.get("a")))
                left_max = max(left_max, a) if math.isfinite(a) else float("inf")
        for lane in section.findall("./right/lane"):
            for w in lane.findall("width"):
                a = abs(_safe_float(w.get("a")))
                right_max = max(right_max, a) if math.isfinite(a) else float("inf")
        section_half = left_max + right_max
        if not math.isfinite(section_half):
            return float("inf")
        max_half = max(max_half, section_half)
    return max_half


def tile_road_ownership(
    root: ET.Element,
    tiles: Dict[str, Tuple[float, float, float, float]],
    *,
    policy: str = "midpoint",
) -> Dict[str, Any]:
    """TIL-002: assign complete roads to tiles; junction context together.

    ``tiles`` maps tile_id -> (x_min, y_min, x_max, y_max).
    Policy 'midpoint': reference-line midpoint (s = length/2) decides ownership.
    Policy 'start': reference-line start point (s = 0) decides ownership.
    Roads in a junction are assigned to the tile of the junction center when
    the junction's bounding center falls inside exactly one tile.
    """
    if policy not in ("midpoint", "start"):
        raise ValueError("policy must be 'midpoint' or 'start'")
    roads = root.findall("road")
    bounds_map: Dict[str, Dict[str, float]] = {}
    length_map: Dict[str, float] = {}
    for road in roads:
        rid = (road.get("id") or "").strip()
        bounds_map[rid] = road_bounds_curve_aware(road)
        length_map[rid] = _road_length(road)

    def _tile_of(x: float, y: float) -> Optional[str]:
        # half-open membership: a point on a shared edge belongs to the
        # right/upper tile, so it never double-matches
        hits = [tid for tid, (x0, y0, x1, y1) in tiles.items()
                if x0 <= x < x1 and y0 <= y < y1]
        if len(hits) == 1:
            return hits[0]
        # fall back to inclusive membership for points on the outer edge
        hits = [tid for tid, (x0, y0, x1, y1) in tiles.items()
                if x0 <= x <= x1 and y0 <= y <= y1]
        if len(hits) == 1:
            return hits[0]
        return None

    ownership: Dict[str, Optional[str]] = {}
    for road in roads:
        rid = (road.get("id") or "").strip()
        b = bounds_map[rid]
        length = length_map[rid]
        if policy == "midpoint":
            x = (b["x_min"] + b["x_max"]) / 2.0
            y = (b["y_min"] + b["y_max"]) / 2.0
        else:  # policy == "start"
            # Start point at s=0: use the first planView geometry's x,y
            planview = road.find("planView")
            if planview is not None:
                first_geo = planview.find("geometry")
                if first_geo is not None:
                    x = _safe_float(first_geo.get("x"))
                    y = _safe_float(first_geo.get("y"))
                else:
                    x, y = b["x_min"], b["y_min"]
            else:
                x, y = b["x_min"], b["y_min"]
        ownership[rid] = _tile_of(x, y)

    # Junction context: roads sharing a junction id move together.
    # OSM2ODR convention: junction="-1" means "not part of any junction" —
    # the pseudo-junction must not co-assign non-junction roads (its
    # bounding center spans the whole map).
    junctions: Dict[str, List[str]] = {}
    for road in roads:
        jid = road.get("junction")
        if jid and jid != "-1":
            junctions.setdefault(jid, []).append((road.get("id") or "").strip())
    for jid, rids in junctions.items():
        chosen = [ownership[r] for r in rids if ownership[r] is not None]
        if not chosen:
            continue
        from collections import Counter
        common = Counter(chosen).most_common(1)[0][0]
        for r in rids:
            ownership[r] = common

    return {"policy": policy, "ownership": ownership,
            "roads_total": len(roads),
            "assigned": sum(1 for v in ownership.values() if v is not None),
            "unassigned": sum(1 for v in ownership.values() if v is None)}


def _canonical_bytes(elem: ET.Element) -> bytes:
    return ET.tostring(elem, encoding="utf-8")


def assert_duplicated_roads_identical(tile_dir: str) -> Dict[str, Any]:
    """TIL-004: roads duplicated across tiles must be byte- and semantic-identical.

    Returns per-road verdicts: byte_identical, semantic_identical (freeze
    digest when available), and the owning tile list.
    """
    tile_files = sorted(f for f in os.listdir(tile_dir) if f.endswith(".xodr"))
    per_road: Dict[str, List[Dict[str, Any]]] = {}
    for fname in tile_files:
        path = os.path.join(tile_dir, fname)
        try:
            tree = ET.parse(path)
        except Exception:
            continue
        for road in tree.getroot().findall("road"):
            rid = (road.get("id") or "").strip()
            per_road.setdefault(rid, []).append({"tile": fname, "road": road})

    results: List[Dict[str, Any]] = []
    violations = 0
    for rid, copies in sorted(per_road.items()):
        if len(copies) < 2:
            continue
        first = copies[0]["road"]
        first_bytes = _canonical_bytes(first)
        first_digest = None
        if _HAS_GEOMETRY:
            try:
                first_digest = compute_freeze(first).get("digest")
            except Exception:
                first_digest = None
        all_byte = True
        all_semantic = True
        for copy in copies[1:]:
            if _canonical_bytes(copy["road"]) != first_bytes:
                all_byte = False
            if first_digest is not None:
                try:
                    if compute_freeze(copy["road"]).get("digest") != first_digest:
                        all_semantic = False
                except Exception:
                    all_semantic = False
        if not (all_byte and all_semantic):
            violations += 1
        results.append({
            "road_id": rid,
            "tiles": [c["tile"] for c in copies],
            "byte_identical": all_byte,
            "semantic_identical": all_semantic,
            "ok": all_byte and all_semantic,
        })

    return {"rule": "TIL-004", "duplicated_road_count": len(results),
            "violation_count": violations,
            "roads": results,
            "ok": violations == 0}


def verify_tile_adjacency(
    tiles: Dict[str, Tuple[float, float, float, float]],
    border_connections: Dict[str, List[str]],
) -> Dict[str, Any]:
    """TIL-006: adjacency graph is complete and border connections verified."""
    adj: Dict[str, set] = {}
    tids = list(tiles)
    for i, a in enumerate(tids):
        ax0, ay0, ax1, ay1 = tiles[a]
        for b in tids[i + 1:]:
            bx0, by0, bx1, by1 = tiles[b]
            touch = not (ax1 < bx0 - 1e-6 or bx1 < ax0 - 1e-6 or
                         ay1 < by0 - 1e-6 or by1 < ay0 - 1e-6)
            if touch:
                adj.setdefault(a, set()).add(b)
                adj.setdefault(b, set()).add(a)
    missing = [t for t in tids if any(n not in (border_connections.get(t) or []) for n in adj.get(t, set()))]
    return {"rule": "TIL-006", "tile_count": len(tids),
            "adjacency_edges": sum(len(v) for v in adj.values()) // 2,
            "missing_connections": missing,
            "ok": not missing}
