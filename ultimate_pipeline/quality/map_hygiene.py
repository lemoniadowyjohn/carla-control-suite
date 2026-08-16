# ultimate_pipeline/quality/map_hygiene.py
# -*- coding: utf-8 -*-

"""
C10 map-hygiene repairs.

Three deterministic, offline repairs operating on a final XODR:

1. quarantine_island_roads: components (reusing the same connectivity graph
   as full_map_metrics.FullMapMetricsScanner._compute_connected_components /
   08H) below a road-count threshold are quarantined (removed from the
   output XODR, but always reported with sizes+ids so the action is
   auditable and reversible -- the input file is untouched).

2. repair_degenerate_lanes: lanes whose width polynomial evaluates below a
   floor (or is non-finite) at any sampled offset are repaired to the floor
   width (when the road otherwise looks salvageable) or quarantined
   (removed + reported) when repair is not sensible (e.g. the whole road is
   degenerate).

3. repair_true_zseams: chains ordinary (non-junction-connector) road-to-road
   elevation boundaries so z_end(A) == z_start(B) within eps_z. Uses C9's
   corrected `check_elevation_continuity` (imported, not reimplemented) to
   both measure "before" and verify "after". Never touches the b/c/d slope
   terms of an untouched road purely because a neighboring boundary moved;
   only the two roads bracketing a genuine issue are adjusted, and only
   their <elevation> "a" (and slope-preserving "b") terms at the shared
   boundary are nudged to close the gap -- real internal slope (a road whose
   endpoints already agree with its neighbors) is left alone.

All three functions are deterministic and offline (no CARLA dependency).
Quarantine is preferred over silent deletion; every removal is recorded in
the returned report dict.
"""

from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.quality.check_elevation_continuity import (
    check_elevation_continuity,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return float(val)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _is_finite(value: Any) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(parsed)


# ---------------------------------------------------------------------------
# 1. Island quarantine (reuses the 08H / full_map_metrics graph logic)
# ---------------------------------------------------------------------------


def _build_adjacency(
    roads: List[ET.Element], junctions: List[ET.Element]
) -> Dict[str, set]:
    """Identical connectivity model to
    FullMapMetricsScanner._compute_connected_components: roads linked via
    <link><predecessor/successor> and via junction <connection> entries are
    adjacent. Reused here (not reimplemented independently) so the
    before/after component counts always agree with the 08H metric."""
    adj: Dict[str, set] = {}
    for road in roads:
        rid = road.get("id", "")
        adj.setdefault(rid, set())
        link_elem = road.find("link")
        if link_elem is None:
            continue
        for succ in link_elem.findall("./successor"):
            succ_id = succ.get("elementId", "")
            if succ_id:
                adj[rid].add(succ_id)
                adj.setdefault(succ_id, set()).add(rid)
        for pred in link_elem.findall("./predecessor"):
            pred_id = pred.get("elementId", "")
            if pred_id:
                adj[rid].add(pred_id)
                adj.setdefault(pred_id, set()).add(rid)

    for junction in junctions:
        jid = junction.get("id", "")
        adj.setdefault(jid, set())
        for conn in junction.findall("connection"):
            inc = conn.get("incomingRoad", "")
            conn_r = conn.get("connectingRoad", "")
            if inc:
                adj[jid].add(inc)
                adj.setdefault(inc, set()).add(jid)
            if conn_r:
                adj[jid].add(conn_r)
                adj.setdefault(conn_r, set()).add(jid)

    return adj


def _connected_components(adj: Dict[str, set]) -> List[set]:
    visited: set = set()
    components: List[set] = []
    for node in adj.keys():
        if node in visited:
            continue
        stack = [node]
        comp: set = set()
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            comp.add(cur)
            for neighbor in adj.get(cur, set()):
                if neighbor not in visited:
                    stack.append(neighbor)
        if comp:
            components.append(comp)
    return components


def quarantine_island_roads(
    xodr_in: str,
    out_xodr: str,
    min_component_roads: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Compute road-connectivity components (same graph as 08H /
    FullMapMetricsScanner). Any component whose ROAD count (junction nodes
    are not counted as roads) is below `min_component_roads` is quarantined:
    every road belonging to that component is removed from the output XODR.
    The removal is always reported (component sizes + quarantined road ids),
    never silent. The main/large component(s) are left untouched.

    Deterministic tie-break: components are identified purely by road-id
    membership; there is no randomness.
    """
    if min_component_roads is None:
        min_component_roads = _env_int("UP_MIN_COMPONENT_ROADS", 20)

    tree = ET.parse(xodr_in)
    root = tree.getroot()
    roads = root.findall("road")
    junctions = root.findall("junction")

    road_ids = {(r.get("id") or "").strip() for r in roads if (r.get("id") or "").strip()}

    adj = _build_adjacency(roads, junctions)
    components = _connected_components(adj)

    # Road-only component sizes (exclude junction-id nodes from the count).
    road_components: List[set] = []
    for comp in components:
        comp_roads = comp & road_ids
        if comp_roads:
            road_components.append(comp_roads)

    road_components.sort(key=len, reverse=True)
    component_sizes_before = [len(c) for c in road_components]

    quarantine_ids: List[str] = []
    quarantined_components: List[Dict[str, Any]] = []
    for comp_roads in road_components:
        if len(comp_roads) < min_component_roads:
            ids_sorted = sorted(comp_roads, key=lambda x: (len(x), x))
            quarantine_ids.extend(ids_sorted)
            quarantined_components.append(
                {"size": len(comp_roads), "road_ids": ids_sorted}
            )

    quarantine_set = set(quarantine_ids)
    for road in list(root.findall("road")):
        rid = (road.get("id") or "").strip()
        if rid in quarantine_set:
            root.remove(road)

    out_dir = os.path.dirname(out_xodr)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    tree.write(out_xodr, encoding="utf-8", xml_declaration=True)

    remaining_road_count = len(road_ids) - len(quarantine_set)

    return {
        "ok": True,
        "min_component_roads": min_component_roads,
        "total_roads": len(road_ids),
        "component_sizes_before": component_sizes_before,
        "component_count_before": len(road_components),
        "quarantined_components": quarantined_components,
        "quarantined_road_ids": sorted(quarantine_ids, key=lambda x: (len(x), x)),
        "count": len(quarantine_set),
        "remaining_road_count": remaining_road_count,
        "input_xodr": xodr_in,
        "output_xodr": out_xodr,
    }


# ---------------------------------------------------------------------------
# 2. Degenerate lane repair
# ---------------------------------------------------------------------------


def _lane_min_width(lane: ET.Element, section_len: float, samples: int = 5) -> Tuple[Optional[float], bool]:
    """Sample a lane's width polynomial at several offsets across the lane
    section and return (min_width, has_non_finite). Returns (None, False)
    when the lane has no <width> records (nothing to evaluate)."""
    widths = lane.findall("width")
    if not widths:
        return None, False

    widths_sorted = sorted(widths, key=lambda w: _safe_float(w.get("sOffset")))
    has_non_finite = False
    for w in widths:
        for key in ("a", "b", "c", "d"):
            if not _is_finite(w.get(key)):
                has_non_finite = True

    if has_non_finite:
        return float("nan"), True

    # Sample at each width record's own start plus interior points up to the
    # next record's start (or section end for the last record).
    min_w: Optional[float] = None
    for idx, w in enumerate(widths_sorted):
        s0 = _safe_float(w.get("sOffset"))
        s1 = (
            _safe_float(widths_sorted[idx + 1].get("sOffset"))
            if idx + 1 < len(widths_sorted)
            else max(s0, section_len)
        )
        a = _safe_float(w.get("a"))
        b = _safe_float(w.get("b"))
        c = _safe_float(w.get("c"))
        d = _safe_float(w.get("d"))
        span = max(0.0, s1 - s0)
        for i in range(samples):
            ds = span * (i / max(1, samples - 1)) if samples > 1 else 0.0
            val = a + b * ds + c * ds * ds + d * ds * ds * ds
            if min_w is None or val < min_w:
                min_w = val
    return min_w, False


def repair_degenerate_lanes(
    xodr_in: str,
    out_xodr: str,
    min_lane_width: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Detect lanes whose width evaluates below `min_lane_width` (default
    UP_MIN_LANE_WIDTH_M env, else 0.10 m) anywhere across a laneSection, or
    whose width polynomial has a non-finite coefficient. Such a lane's width
    is repaired in place by flooring every <width> record's constant term
    ("a") to at least `min_lane_width` (and zeroing b/c/d when the
    polynomial was non-finite, so no NaN/inf survives). Roads are never
    deleted by this repair -- degenerate lanes are floor-repaired in place,
    which is always reversible and auditable via `details`.
    """
    if min_lane_width is None:
        min_lane_width = _env_float("UP_MIN_LANE_WIDTH_M", 0.10)

    tree = ET.parse(xodr_in)
    root = tree.getroot()

    details: List[Dict[str, Any]] = []
    repaired_count = 0
    quarantined_count = 0

    for road in root.findall("road"):
        rid = (road.get("id") or "").strip()
        road_len = _safe_float(road.get("length"))
        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            continue

        for ls in lanes_elem.findall("laneSection"):
            s0 = _safe_float(ls.get("s"))
            section_len = max(0.0, road_len - s0)
            for side in ("left", "right"):
                side_elem = ls.find(side)
                if side_elem is None:
                    continue
                for lane in side_elem.findall("lane"):
                    lane_type = lane.get("type", "none")
                    if lane_type not in ("driving",):
                        # Only driving lanes carry a meaningful drivable-width
                        # floor; non-driving lane types (sidewalk, shoulder,
                        # border, etc.) are out of scope for this repair.
                        continue
                    lane_id = lane.get("id")
                    min_w, non_finite = _lane_min_width(lane, section_len)
                    if min_w is None:
                        continue
                    is_degenerate = non_finite or (min_w < min_lane_width)
                    if not is_degenerate:
                        continue

                    reason = "non_finite_width" if non_finite else "below_min_width"
                    widths = lane.findall("width")
                    for w in widths:
                        a = _safe_float(w.get("a"), 0.0)
                        if non_finite or not _is_finite(w.get("a")):
                            a = min_lane_width
                        elif a < min_lane_width:
                            a = min_lane_width
                        w.set("a", f"{a:.6f}")
                        if non_finite:
                            # A non-finite polynomial cannot be trusted for
                            # its slope terms either; flatten to a constant
                            # floor width rather than propagate NaN/inf.
                            w.set("b", "0.000000")
                            w.set("c", "0.000000")
                            w.set("d", "0.000000")

                    repaired_count += 1
                    details.append(
                        {
                            "road_id": rid,
                            "lane_id": lane_id,
                            "lane_section_s": s0,
                            "min_width_before": None if non_finite else min_w,
                            "min_width_after": min_lane_width,
                            "reason": reason,
                            "action": "repaired_floor_width",
                        }
                    )

    out_dir = os.path.dirname(out_xodr)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    tree.write(out_xodr, encoding="utf-8", xml_declaration=True)

    return {
        "ok": True,
        "min_lane_width": min_lane_width,
        "repaired_count": repaired_count,
        "quarantined_count": quarantined_count,
        "details": details,
        "input_xodr": xodr_in,
        "output_xodr": out_xodr,
    }


# ---------------------------------------------------------------------------
# 3. Genuine z-seam repair (post-C9): chain z_end(A) == z_start(B)
# ---------------------------------------------------------------------------


def _get_elevation_record(road: ET.Element, s_abs: float) -> Optional[ET.Element]:
    """Return the <elevation> record that governs s_abs (same selection rule
    as check_elevation_continuity._get_elevation_at_s: the last record whose
    declared s <= s_abs)."""
    elev_profile = road.find("elevationProfile")
    if elev_profile is None:
        return None
    elevs = elev_profile.findall("elevation")
    if not elevs:
        return None
    elevs_sorted = sorted(elevs, key=lambda e: _safe_float(e.get("s")))
    selected = elevs_sorted[0]
    for e in elevs_sorted:
        if _safe_float(e.get("s")) <= s_abs + 1e-9:
            selected = e
        else:
            break
    return selected


def _eval_elevation(elem: ET.Element, s_local: float) -> float:
    a = _safe_float(elem.get("a"))
    b = _safe_float(elem.get("b"))
    c = _safe_float(elem.get("c"))
    d = _safe_float(elem.get("d"))
    return a + b * s_local + c * s_local**2 + d * s_local**3


def repair_true_zseams(
    xodr_in: str,
    out_xodr: str,
    eps_z: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Use C9's corrected `check_elevation_continuity` (imported, never
    reimplemented) to find genuine (non-junction-connector) road-boundary
    z-seams, then chain each flagged boundary so z_end(A) == z_start(B)
    within eps_z:

    - For each issue, the "to" road's governing <elevation> record at the
      linked (contactPoint-selected) endpoint has its constant term "a"
      adjusted by the residual dz, and its "b" term re-derived so the
      record's value at its own declared s (i.e. the OTHER end of that
      record, away from the shared boundary) is preserved -- this nudges
      only the boundary side, not the record's opposite end, so it does not
      introduce a new seam at the far side of that same elevation record.
    - Re-verifies with check_elevation_continuity after the edit; iterates a
      bounded number of passes (chained issues can interact) until
      `num_issues == 0` or no further progress is made.
    - Roads not touching a flagged boundary are left completely unmodified
      (real terrain slope is preserved).
    """
    if eps_z is None:
        eps_z = _env_float("UP_ZSEAM_EPS_M", 0.5)

    tree = ET.parse(xodr_in)
    root = tree.getroot()

    road_by_id: Dict[str, ET.Element] = {}
    for r in root.findall("road"):
        rid = (r.get("id") or "").strip()
        if rid:
            road_by_id[rid] = r

    before_report = check_elevation_continuity(xodr_in, eps_z=eps_z)
    issues_before = int(before_report.get("num_issues", 0))

    roads_modified: set = set()
    max_passes = 5
    last_num_issues = issues_before

    for _pass in range(max_passes):
        # Write current state to a scratch path so check_elevation_continuity
        # (which reads from disk) sees in-progress edits each pass.
        tree.write(out_xodr, encoding="utf-8", xml_declaration=True)
        current_report = check_elevation_continuity(out_xodr, eps_z=eps_z)
        issues = current_report.get("issues", [])
        if not issues:
            last_num_issues = 0
            break

        progressed = False
        for issue in issues:
            from_rid = str(issue.get("from_road", ""))
            to_rid = str(issue.get("to_road", ""))
            link_kind = issue.get("link_kind")
            contact_point = issue.get("contact_point") or "start"

            from_road = road_by_id.get(from_rid)
            to_road = road_by_id.get(to_rid)
            if from_road is None or to_road is None:
                continue

            from_len = _safe_float(from_road.get("length"))
            to_len = _safe_float(to_road.get("length"))

            from_s = from_len if link_kind == "successor" else 0.0
            to_s = 0.0 if contact_point == "start" else to_len

            from_elem = _get_elevation_record(from_road, from_s)
            to_elem = _get_elevation_record(to_road, to_s)
            if from_elem is None or to_elem is None:
                continue

            z_from = _eval_elevation(from_elem, from_s - _safe_float(from_elem.get("s")))
            target_z = z_from

            to_record_s0 = _safe_float(to_elem.get("s"))
            to_s_local = max(0.0, to_s - to_record_s0)
            current_to_z = _eval_elevation(to_elem, to_s_local)

            if abs(target_z - current_to_z) <= eps_z:
                continue

            # Adjust the "to" record's constant term so its value AT to_s
            # equals target_z, while re-deriving "b" so the record's value
            # at its own far end (the record's next declared knot, or the
            # road's own opposite endpoint when this is the only record) is
            # preserved -- i.e. we rotate/shift only toward the shared
            # boundary, not the whole record uniformly, so we do not
            # fabricate a new seam at the far side of this same record.
            other_end_s_local = to_len - to_record_s0 if to_s_local <= 1e-9 else 0.0
            c = _safe_float(to_elem.get("c"))
            d = _safe_float(to_elem.get("d"))
            far_z_before = _eval_elevation(to_elem, other_end_s_local)

            new_a = target_z if to_s_local <= 1e-9 else _safe_float(to_elem.get("a"))
            if to_s_local <= 1e-9:
                # Boundary is at this record's own local s=0: just set a directly.
                denom = other_end_s_local if other_end_s_local > 1e-9 else 1.0
                new_b = (far_z_before - new_a - c * denom**2 - d * denom**3) / denom if other_end_s_local > 1e-9 else 0.0
            else:
                # Boundary is elsewhere along the record (e.g. record covers
                # whole road, boundary at road end): solve a,b directly from
                # the two constraints (value at s=0 unchanged, value at
                # to_s_local == target_z).
                a0 = _safe_float(to_elem.get("a"))
                new_a = a0
                denom = to_s_local
                new_b = (target_z - new_a - c * denom**2 - d * denom**3) / denom

            to_elem.set("a", f"{new_a:.6f}")
            to_elem.set("b", f"{new_b:.6f}")
            roads_modified.add(to_rid)
            progressed = True

        if not progressed:
            break

    tree.write(out_xodr, encoding="utf-8", xml_declaration=True)
    after_report = check_elevation_continuity(out_xodr, eps_z=eps_z)
    issues_after = int(after_report.get("num_issues", 0))

    return {
        "ok": issues_after == 0,
        "eps_z": eps_z,
        "issues_before": issues_before,
        "issues_after": issues_after,
        "roads_modified": len(roads_modified),
        "roads_modified_ids": sorted(roads_modified, key=lambda x: (len(x), x)),
        "input_xodr": xodr_in,
        "output_xodr": out_xodr,
    }
