#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H1 — OSM way -> XODR road geometric matching (Phase H semantic enrichment).

Projects each OSM signal candidate start point onto the densified reference
line of every XODR road (structure_classifier.road_centerline_polyline) and
recovers:

- nearest road id (tie-break: smallest road id)
- s: arc length of the closest point along the road centreline
- distance: point-to-polyline distance (m)
- t_center: lateral offset of the OSM way centreline relative to the road
  reference line, i.e. -(sum of right-side lane widths)/2 evaluated at s
- z: elevation profile value at s (F4/F5 profiles)

Match policy (documented thresholds):
- match if distance <= 15.0 m
- ambiguous if the second-best road is within 1.5 m of the best
- otherwise unmapped (recorded, no signal emitted)
"""
from __future__ import annotations

import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.enrichment.structure_classifier import road_centerline_polyline
from ultimate_pipeline.enrichment.elevation_link_offset_solver import _eval_elevation_at

WRITER_VERSION = "phase_h1_osm_road_match.py/1"

MATCH_THRESHOLD_M = 15.0
AMBIGUOUS_GAP_M = 1.5
CENTERLINE_SPACING_M = 2.0
NODE_MATCH_EFF_M = 3.0
NODE_OWNER_VOTES = 2


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _point_segment_projection(
    px: float, py: float, ax: float, ay: float, bx: float, by: float,
) -> Tuple[float, float, float]:
    """(t, distance, projected segment fraction) of point onto segment."""
    dx = bx - ax
    dy = by - ay
    denom = dx * dx + dy * dy
    if denom < 1e-12:
        return math.hypot(px - ax, py - ay), math.hypot(px - ax, py - ay), 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return t, math.hypot(px - cx, py - cy), t


def _road_centerline(road: ET.Element) -> List[Tuple[float, float]]:
    pts = road_centerline_polyline(road, CENTERLINE_SPACING_M)
    return pts if len(pts) >= 2 else []


def _s_at_closest(poly: List[Tuple[float, float]], px: float, py: float) -> Tuple[float, float]:
    """Arc length s and distance of the closest polyline point to (px, py)."""
    best_s = 0.0
    best_d = math.inf
    run = 0.0
    for a, b in zip(poly, poly[1:]):
        t, d, _ = _point_segment_projection(px, py, a[0], a[1], b[0], b[1])
        if d < best_d:
            best_d = d
            best_s = run + t * math.hypot(b[0] - a[0], b[1] - a[1])
        run += math.hypot(b[0] - a[0], b[1] - a[1])
    return best_s, best_d


def _road_length(road: ET.Element) -> float:
    try:
        return float(road.get("length", "0"))
    except Exception:
        return 0.0


def _lane_width_at(road: ET.Element, s: float) -> float:
    """Total width of all lanes at arc length s (right-side lanes only map)."""
    secs = road.findall("lanes/laneSection")
    road_len = _road_length(road)
    for idx, sec in enumerate(secs):
        s1 = _safe_float(sec.get("s", "0"), 0.0)
        nxt = min(
            [_safe_float(o.get("s", "0"), road_len) for o in secs[idx + 1:]] or [road_len]
        )
        if s < s1 - 1e-9 or s > nxt + 1e-9:
            continue
        total = 0.0
        for side in ("left", "center", "right"):
            el = sec.find(side)
            if el is None:
                continue
            for lane in el.findall("lane"):
                wid = 0.0
                for w in lane.findall("width"):
                    try:
                        a = float(w.get("a", "0"))
                        b = float(w.get("b", "0"))
                        c = float(w.get("c", "0"))
                        d = float(w.get("d", "0"))
                    except Exception:
                        a = b = c = d = 0.0
                    ds = s - float(w.get("sOffset", "0"))
                    if ds < 0:
                        continue
                    wid = a + b * ds + c * ds * ds + d * ds * ds * ds
                total += max(0.0, wid)
        return total
    return 0.0


def _centerline_t(road: ET.Element, s: float) -> float:
    """OSM way centreline offset relative to the road reference line."""
    total = _lane_width_at(road, s)
    return -total / 2.0


def _z_at(road: ET.Element, s: float) -> Optional[float]:
    elevs = road.findall("elevationProfile/elevation")
    if not elevs:
        return None
    return _eval_elevation_at(elevs, s)


def match_candidate_to_roads(
    root: ET.Element, candidates: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Match OSM candidates onto roads (cKDTree, aligned-run-length).

    The OSM way lies at the carriageway centreline while the XODR reference
    line sits at the left pavement edge, so distances are corrected by the
    local half-width: effective_distance = max(0, d - width(s)/2).

    A way is matched to every road whose carriageway it runs along for a
    significant continuous length (aligned_run >= MIN_ALIGNED_RUN_M).  A
    single OSM way is frequently split into several XODR roads (junctions)
    or runs over/under co-located carriageways; way-wide tags (maxspeed,
    traffic_sign, turn:lanes) apply to every aligned road.  Ways embedded
    in junction plazas (no sustained alignment) are reported ambiguous;
    ways with no road within the threshold are reported unmapped.

    Returns:
        matched: [{candidate_idx, road_ids, roads_total, s, t_center, z,
                   distance, aligned_m: {rid: meters}}]
        ambiguous: [candidate_idx]
        unmapped: [candidate_idx]
    """
    import numpy as np
    from scipy.spatial import cKDTree

    roads = root.findall("road")
    road_by_id = {r.get("id"): r for r in roads}
    pts_list: List[Tuple[float, float]] = []
    owner: List[str] = []
    poly_by_road: Dict[str, List[Tuple[float, float]]] = {}
    for road in roads:
        poly = _road_centerline(road)
        if not poly:
            continue
        poly_by_road[road.get("id")] = poly
        pts_list.extend(poly)
        owner.extend([road.get("id")] * len(poly))

    tree = cKDTree(np.asarray(pts_list, dtype=np.float64))
    matched: List[Dict[str, Any]] = []
    ambiguous: List[int] = []
    unmapped: List[int] = []

    def _eff_for(rid: str, ax: float, ay: float) -> Tuple[float, float]:
        s_exact, d_exact = _s_at_closest(poly_by_road[rid], ax, ay)
        hw = _lane_width_at(road_by_id[rid], s_exact) / 2.0
        return max(0.0, d_exact - hw), s_exact

    def _node_owners(way_poly: List[Tuple[float, float]]) -> Dict[str, int]:
        """Per-road vote count: number of way nodes whose nearest road it is.

        OSM ways are coarsely noded (junction-to-junction); the XODR geometry
        was rebuilt, so node anchors — not polyline alignment — are the
        reliable ground-truth contact points.
        """
        votes: Dict[str, int] = {}
        for ax, ay in way_poly:
            dists, near = tree.query([ax, ay], k=min(4, len(pts_list)))
            if len(pts_list) == 1:
                dists, near = [dists], [near]
            seen: Dict[str, float] = {}
            for d, i in zip(list(dists), list(near)):
                rid = owner[int(i)]
                if rid not in seen or d < seen[rid]:
                    seen[rid] = d
            best: Optional[Tuple[float, str]] = None
            for rid, _d in seen.items():
                eff, _s = _eff_for(rid, ax, ay)
                if best is None or eff < best[0]:
                    best = (eff, rid)
            if best is not None and best[0] <= NODE_MATCH_EFF_M:
                votes[best[1]] = votes.get(best[1], 0) + 1
        return votes

    def _road_adjacency() -> Dict[str, set]:
        """Road-level adjacency: successor/predecessor links + junction connections."""
        adj: Dict[str, set] = {}
        for road in roads:
            rid = road.get("id")
            adj.setdefault(rid, set())
            for link in road.findall("link/predecessor") + road.findall("link/successor"):
                if link.get("elementType") == "road":
                    adj.setdefault(rid, set()).add(link.get("elementId"))
                    adj.setdefault(link.get("elementId"), set()).add(rid)
            for conn in road.findall(".//junction/connection"):
                pass
        for junc in root.findall("junction"):
            for conn in junc.findall("connection"):
                incoming = conn.get("incomingRoad")
                connecting = conn.get("connectingRoad")
                if incoming and connecting:
                    adj.setdefault(incoming, set()).add(connecting)
                    adj.setdefault(connecting, set()).add(incoming)
        return adj

    adjacency = _road_adjacency()

    for idx, cand in enumerate(candidates):
        way_poly = cand.get("polyline_m") or [
            cand["start_m"], cand.get("end_m") or cand["start_m"],
        ]
        votes = _node_owners(way_poly)
        members = {
            rid: v for rid, v in votes.items() if v >= NODE_OWNER_VOTES
        }
        if not members and len(way_poly) == 2 and len(votes) == 2:
            pair = sorted(votes.keys())
            if pair[1] in adjacency.get(pair[0], ()):
                members = {pair[0]: 1, pair[1]: 1}
        if not members:
            if votes:
                ambiguous.append(idx)
            else:
                unmapped.append(idx)
            continue
        members_sorted = sorted(members.items())
        rid0 = members_sorted[0][0]
        s0, d_exact = _s_at_closest(
            poly_by_road[rid0], way_poly[0][0], way_poly[0][1])
        road = road_by_id[rid0]
        matched.append({
            "candidate_idx": idx,
            "road_ids": [rid for rid, _ in members_sorted],
            "roads_total": len(members_sorted),
            "s": round(s0, 3),
            "t_center": round(_centerline_t(road, s0), 3),
            "z": _z_at(road, s0),
            "distance": round(d_exact, 3),
            "node_votes": {rid: v for rid, v in members_sorted},
        })
    return {"matched": matched, "ambiguous": ambiguous, "unmapped": unmapped}


def main() -> int:
    import json
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo))
    root = ET.parse(
        repo / "reports" / "post_audit_hardening" / "20260804T030000Z" / "candidate_g7_roadmarks.xodr"
    ).getroot()
    from ultimate_pipeline.tools.phase_h0_osm_signal_extract import OSMSignalExtractor
    rec = OSMSignalExtractor(
        str(repo / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"),
        str(repo / "reports" / "post_audit_hardening" / "20260804T030000Z" / "candidate_g7_roadmarks.xodr"),
    ).extract()
    result = match_candidate_to_roads(root, rec["candidates"])
    print(json.dumps({
        "matched": len(result["matched"]),
        "ambiguous": len(result["ambiguous"]),
        "unmapped": len(result["unmapped"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
