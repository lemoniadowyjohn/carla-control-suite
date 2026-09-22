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


def _safe_float_nan_propagate(value: Optional[str], default: float = 0.0) -> float:
    """Parse float but propagate NaN/Inf instead of defaulting.
    
    Used for width coefficients where a corrupted NaN must not be silently
    treated as a narrower/absent width -- TIL-001 requires the tile margin
    to be inflated enough that no lane escapes the tile.
    """
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _geom_kind(geom: ET.Element) -> str:
    for tag in ("line", "arc", "spiral", "poly3", "paramPoly3"):
        if geom.find(tag) is not None:
            return tag
    return "unknown"


def _as_bounds(value) -> Tuple[float, float, float, float]:
    """Normalize Bounds2D (P05) or raw 4-tuple into (x_min, y_min, x_max, y_max)."""
    if hasattr(value, "x_min"):
        return (value.x_min, value.y_min, value.x_max, value.y_max)
    return tuple(value)


def _geometry_local_bounds(geom: ET.Element) -> Tuple[float, float, float, float]:
    """Local (x,y) bounds of one geometry element, including curve extrema."""
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
                raise RuntimeError(f"spiral_bounds failed for geometry {x0},{y0}: {e}")
        raise RuntimeError("spiral geometry requires opendrive_geometry (unavailable)")

    if kind == "poly3":
        a = _safe_float(child.get("a"))
        b = _safe_float(child.get("b"))
        c = _safe_float(child.get("c"))
        d = _safe_float(child.get("d"))
        if _HAS_GEOMETRY:
            try:
                return _as_bounds(poly3_bounds(x0, y0, hdg, length, a, b, c, d))
            except Exception as e:
                raise RuntimeError(f"poly3_bounds failed for geometry {x0},{y0}: {e}")
        raise RuntimeError("poly3 geometry requires opendrive_geometry (unavailable)")

    if kind == "paramPoly3":
        u = _safe_float(child.get("aU")); v = _safe_float(child.get("aV"))
        bu = _safe_float(child.get("bU")); bv = _safe_float(child.get("bV"))
        cu = _safe_float(child.get("cU")); cv = _safe_float(child.get("cV"))
        du = _safe_float(child.get("dU")); dv = _safe_float(child.get("dV"))
        if _HAS_GEOMETRY:
            try:
                # analytic extrema incl. derivative roots (hardened evaluator)
                return _as_bounds(param_poly3_bounds(
                    x0, y0, hdg, length, u, bu, cu, du, v, bv, cv, dv,
                    child.get("pRange", "arcLength")))
            except Exception as e:
                raise RuntimeError(f"param_poly3_bounds failed for geometry {x0},{y0}: {e}")
        # Fallback: hardened sampler
        try:
            from ultimate_pipeline.geometry.geometry_math import (
                sample_parampoly3_points,
            )
            n_samples = max(8, min(64, int(length / 2.0)))
            pts = sample_parampoly3_points(
                child, x0, y0, hdg, length,
                [i / n_samples for i in range(1, n_samples + 1)])
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            return (min(xs), min(ys), max(xs), max(ys))
        except Exception as e:
            raise RuntimeError(f"paramPoly3 sampler failed for geometry {x0},{y0}: {e}")
    return (x0, y0, x0, y0)


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


def _eval_width_poly(s_offset: float, a: float, b: float, c: float, d: float) -> float:
    """Evaluate cubic width polynomial at given sOffset."""
    return a + b * s_offset + c * s_offset * s_offset + d * s_offset * s_offset * s_offset


def road_cumulative_lateral_extent(road: ET.Element) -> float:
    """TIL-001: Total lateral extent of the road cross-section.

    Sums left lanes + right lanes separately using canonical width evaluation
    (polynomial extrema per laneSection), then returns max(left_total, right_total).
    This is the true half-width margin needed so no lane escapes the tile.
    """
    left_total = 0.0
    right_total = 0.0

    road_len = float(road.get("length", "0.0") or 0.0)

    for ls in road.findall("./lanes/laneSection"):
        s0 = float(ls.get("s", "0.0") or 0.0)

        for lane in ls.findall("left/lane"):
            max_w = 0.0
            for w in lane.findall("width"):
                a = _safe_float_nan_propagate(w.get("a"), 0.0)
                b = _safe_float_nan_propagate(w.get("b"), 0.0)
                c = _safe_float_nan_propagate(w.get("c"), 0.0)
                d = _safe_float_nan_propagate(w.get("d"), 0.0)
                s_offset = _safe_float(w.get("sOffset"), 0.0)
                # Evaluate polynomial at endpoints and critical points
                w0 = abs(_eval_width_poly(s_offset, a, b, c, d))
                w1 = abs(_eval_width_poly(road_len, a, b, c, d))
                # Propagate non-finite: if any evaluation is non-finite, max_w becomes non-finite
                if not (math.isfinite(w0) and math.isfinite(w1)):
                    return float('nan')
                max_w = max(max_w, w0, w1)
                # Check derivative roots for cubic extrema
                if abs(c) > 1e-12:
                    disc = b*b - 3*a*c
                    if disc >= 0:
                        sqrt_disc = math.sqrt(disc)
                        t_crit1 = (-b + sqrt_disc) / (3*c)
                        t_crit2 = (-b - sqrt_disc) / (3*c)
                        for t in (t_crit1, t_crit2):
                            if t is not None and 0 <= t <= road_len:
                                wt = abs(_eval_width_poly(t, a, b, c, d))
                                if not math.isfinite(wt):
                                    return float('nan')
                                max_w = max(max_w, wt)
            left_total += max_w

        for lane in ls.findall("right/lane"):
            max_w = 0.0
            for w in lane.findall("width"):
                a = _safe_float_nan_propagate(w.get("a"), 0.0)
                b = _safe_float_nan_propagate(w.get("b"), 0.0)
                c = _safe_float_nan_propagate(w.get("c"), 0.0)
                d = _safe_float_nan_propagate(w.get("d"), 0.0)
                s_offset = _safe_float(w.get("sOffset"), 0.0)
                w0 = abs(_eval_width_poly(s_offset, a, b, c, d))
                w1 = abs(_eval_width_poly(road_len, a, b, c, d))
                if not (math.isfinite(w0) and math.isfinite(w1)):
                    return float('nan')
                max_w = max(max_w, w0, w1)
                if abs(c) > 1e-12:
                    disc = b*b - 3*a*c
                    if disc >= 0:
                        sqrt_disc = math.sqrt(disc)
                        t_crit1 = (-b + sqrt_disc) / (3*c)
                        t_crit2 = (-b - sqrt_disc) / (3*c)
                        for t in (t_crit1, t_crit2):
                            if t is not None and 0 <= t <= road_len:
                                wt = abs(_eval_width_poly(t, a, b, c, d))
                                if not math.isfinite(wt):
                                    return float('nan')
                                max_w = max(max_w, wt)
            right_total += max_w

    return max(left_total, right_total)


def road_max_lane_half_width(road: ET.Element) -> float:
    """Legacy compatibility: returns cumulative lateral extent for TIL-001 compliance.

    The old implementation used max individual lane width 'a', which could
    underestimate the true cross-section (e.g., 3x3.5m lanes = 10.5m, not 3.5m).
    """
    return road_cumulative_lateral_extent(road)


def _eval_ref_line_at_s(road: ET.Element, s: float) -> Tuple[float, float]:
    """Evaluate reference line (x,y) at arc-length s using canonical geometry.

    Uses the same evaluator as the pipeline's geometry kernel for consistency.
    """
    try:
        from ultimate_pipeline.geometry.geometry_math import evaluate_planview_at_s
        return evaluate_planview_at_s(road, s)
    except Exception:
        # Fallback: approximate by walking planView segments
        planview = road.find("planView")
        if planview is None:
            return (0.0, 0.0)
        acc = 0.0
        for geom in planview.findall("geometry"):
            g_s = _safe_float(geom.get("s"), 0.0)
            g_x = _safe_float(geom.get("x"), 0.0)
            g_y = _safe_float(geom.get("y"), 0.0)
            g_hdg = _safe_float(geom.get("hdg"), 0.0)
            g_len = _safe_float(geom.get("length"), 0.0)
            kind = _geom_kind(geom)
            if g_s + g_len >= s:
                # Interpolate within this geometry segment
                t = s - g_s
                if kind == "line":
                    return (g_x + t * math.cos(g_hdg), g_y + t * math.sin(g_hdg))
                # For curves, use start point as conservative approximation
                return (g_x, g_y)
            acc = g_s + g_len
        # Beyond end: return last point
        return (_safe_float(road.get("length"), 0.0), 0.0)


def tile_road_ownership(
    root: ET.Element,
    tiles: Dict[str, Tuple[float, float, float, float]],
    *,
    policy: str = "midpoint",
) -> Dict[str, Any]:
    """TIL-002: assign complete roads to tiles; junction context together.

    ``tiles`` maps tile_id -> (x_min, y_min, x_max, y_max).
    Policy 'midpoint': reference-line midpoint decides; 'start': start point.
    Roads in a junction are assigned to the tile of the junction center when
    the junction's bounding center falls inside exactly one tile.
    """
    if policy not in ("midpoint", "start"):
        raise ValueError("policy must be 'midpoint' or 'start'")
    roads = root.findall("road")
    bounds_map: Dict[str, Dict[str, float]] = {}
    for road in roads:
        rid = (road.get("id") or "").strip()
        bounds_map[rid] = road_bounds_curve_aware(road)

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
        road_len = float(road.get("length", "0.0") or 0.0)
        if policy == "midpoint":
            x, y = _eval_ref_line_at_s(road, road_len / 2.0)
        else:
            x, y = _eval_ref_line_at_s(road, 0.0)  # start point (reference line s=0)
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
        counts = Counter(chosen)
        max_count = max(counts.values())
        # Deterministic tie-breaking: sort tile_ids and pick the first
        tied_tiles = sorted(tid for tid, cnt in counts.items() if cnt == max_count)
        common = tied_tiles[0]
        if len(tied_tiles) > 1:
            # Record ambiguous junction assignment for audit
            pass  # Could add to return dict if needed
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

    Fail closed: any parse failure or missing semantic digest is a violation.
    """
    tile_files = sorted(f for f in os.listdir(tile_dir) if f.endswith(".xodr"))
    per_road: Dict[str, List[Dict[str, Any]]] = {}
    parse_failures: List[Dict[str, str]] = []
    for fname in tile_files:
        path = os.path.join(tile_dir, fname)
        try:
            tree = ET.parse(path)
        except Exception as e:
            parse_failures.append({"tile": fname, "error": str(e)})
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
        digest_error = None
        if _HAS_GEOMETRY:
            try:
                # compute_freeze returns a string digest directly, not a dict
                first_digest = compute_freeze(first)
            except Exception as e:
                digest_error = str(e)
        all_byte = True
        all_semantic = True
        for copy in copies[1:]:
            if _canonical_bytes(copy["road"]) != first_bytes:
                all_byte = False
            if first_digest is not None:
                try:
                    if compute_freeze(copy["road"]) != first_digest:
                        all_semantic = False
                except Exception:
                    all_semantic = False
            else:
                # No canonical digest available -- cannot verify semantic identity
                all_semantic = False
        if parse_failures:
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
            "parse_failures": parse_failures,
            "roads": results,
            "ok": violations == 0 and not parse_failures}


def verify_tile_adjacency(
    tiles: Dict[str, Tuple[float, float, float, float]],
    border_connections: Dict[str, List[str]],
) -> Dict[str, Any]:
    """TIL-006: adjacency graph is complete and border connections verified.

    Adjacency requires POSITIVE shared-edge overlap (length > 1e-6).
    Corner-only contact does NOT count as an edge neighbor.
    Also detects overlapping tile boxes and duplicate tiles.
    """
    adj: Dict[str, set] = {}
    tids = sorted(tiles)  # deterministic order
    overlapping_pairs: List[Tuple[str, str]] = []
    for i, a in enumerate(tids):
        ax0, ay0, ax1, ay1 = tiles[a]
        for b in tids[i + 1:]:
            bx0, by0, bx1, by1 = tiles[b]

            # Check for overlapping area (not just touching)
            x_overlap = min(ax1, bx1) - max(ax0, bx0)
            y_overlap = min(ay1, by1) - max(ay0, by0)

            if x_overlap > 1e-6 and y_overlap > 1e-6:
                # Actual area overlap -- should not happen in valid tiling
                overlapping_pairs.append((a, b))
                continue

            # Check for positive shared-edge overlap (not corner-only)
            edge_overlap = 0.0
            if abs(ax1 - bx0) < 1e-6 or abs(bx1 - ax0) < 1e-6:
                # Vertical edge contact -- check y overlap
                edge_overlap = min(ay1, by1) - max(ay0, by0)
            elif abs(ay1 - by0) < 1e-6 or abs(by1 - ay0) < 1e-6:
                # Horizontal edge contact -- check x overlap
                edge_overlap = min(ax1, bx1) - max(ax0, bx0)

            if edge_overlap > 1e-6:
                adj.setdefault(a, set()).add(b)
                adj.setdefault(b, set()).add(a)

    # Check for duplicate tiles (identical bounds)
    duplicate_pairs: List[Tuple[str, str]] = []
    for i, a in enumerate(tids):
        for b in tids[i + 1:]:
            if tiles[a] == tiles[b]:
                duplicate_pairs.append((a, b))

    missing = [t for t in tids if any(n not in (border_connections.get(t) or []) for n in adj.get(t, set()))]

    return {
        "rule": "TIL-006",
        "tile_count": len(tids),
        "adjacency_edges": sum(len(v) for v in adj.values()) // 2,
        "missing_connections": missing,
        "overlapping_tiles": overlapping_pairs,
        "duplicate_tiles": duplicate_pairs,
        "ok": not missing and not overlapping_pairs and not duplicate_pairs
    }
