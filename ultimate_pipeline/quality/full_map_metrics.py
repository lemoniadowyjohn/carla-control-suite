from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Optional


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _elevation_at_s(road: ET.Element, s_abs: float) -> Optional[float]:
    """Evaluate a road's elevation cubic (a + b*s + c*s^2 + d*s^3) at s_abs,
    selecting the applicable <elevation> record by its declared s.

    Returns None if the road has no elevationProfile records.
    """
    elev_profile = road.find("elevationProfile")
    if elev_profile is None:
        return None
    elevs = elev_profile.findall("elevation")
    if not elevs:
        return None

    sorted_elevs = sorted(elevs, key=lambda e: _safe_float(e.get("s")))
    selected = sorted_elevs[0]
    for e in sorted_elevs:
        if _safe_float(e.get("s")) <= s_abs + 1e-9:
            selected = e
        else:
            break

    s0 = _safe_float(selected.get("s"))
    a = _safe_float(selected.get("a"))
    b = _safe_float(selected.get("b"))
    c = _safe_float(selected.get("c"))
    d = _safe_float(selected.get("d"))
    s_local = max(0.0, s_abs - s0)
    return a + b * s_local + c * s_local * s_local + d * s_local * s_local * s_local


class FullMapMetricsScanner:
    """
    Compute full-map parent/child metrics for a final XODR.

    Metrics:
      - Road/junction counts
      - Lane validity (type distribution, LaneLink presence)
      - Connector endpoint errors (gap, tangent diff)
      - Elevation continuity (variance, max gradient)
      - Graph component analysis (connected components)
      - Seam distribution (heading jumps at road boundaries)
    """

    @staticmethod
    def scan(xodr_path: str) -> dict[str, Any]:
        tree = ET.parse(xodr_path)
        root = tree.getroot()

        roads = root.findall("road")
        junctions = root.findall("junction")

        road_count = len(roads)
        junction_count = len(junctions)

        total_lanes = 0
        total_driving_lanes = 0
        total_lanelinks = 0
        lane_types: dict[str, int] = {}

        connector_endpoint_errors: list[dict] = []
        elevation_variance: list[float] = []
        max_elevation_gradient = 0.0

        road_ids = {r.get("id", ""): r for r in roads}

        for road in roads:
            rid = road.get("id", "")
            lanes_elem = road.find("lanes")
            if lanes_elem is None:
                continue

            for lane_section in lanes_elem.findall("laneSection"):
                for side in ("left", "center", "right"):
                    side_elem = lane_section.find(side)
                    if side_elem is None:
                        continue
                    for lane in side_elem.findall("lane"):
                        total_lanes += 1
                        lt = lane.get("type", "none")
                        lane_types[lt] = lane_types.get(lt, 0) + 1
                        if lt == "driving":
                            total_driving_lanes += 1
                        link = lane.find("link")
                        if link is not None:
                            if link.find("predecessor") is not None:
                                total_lanelinks += 1
                            if link.find("successor") is not None:
                                total_lanelinks += 1

            planview = road.find("planView")
            elevation_profile = road.find("elevationProfile")

            if elevation_profile is not None:
                elevs = elevation_profile.findall("elevation")
                sect_count = len(elevs)
                if sect_count > 1:
                    sorted_elevs = sorted(
                        elevs, key=lambda e: float(e.get("s", "0"))
                    )
                    for i in range(1, len(sorted_elevs)):
                        prev = sorted_elevs[i - 1]
                        curr = sorted_elevs[i]
                        s0 = float(prev.get("s", "0"))
                        s1 = float(curr.get("s", "0"))
                        a0 = float(prev.get("a", "0"))
                        a1 = float(curr.get("a", "0"))
                        ds = max(1e-6, s1 - s0)
                        gradient = abs(a1 - a0) / ds
                        max_elevation_gradient = max(max_elevation_gradient, gradient)
                        elevation_variance.append(gradient)

            if planview is not None:
                geoms = planview.findall("geometry")
                if len(geoms) > 1:
                    for i in range(1, len(geoms)):
                        prev = geoms[i - 1]
                        curr = geoms[i]
                        prev_s = float(prev.get("s", "0"))
                        prev_len = float(prev.get("length", "0"))
                        prev_end_s = prev_s + prev_len
                        curr_s = float(curr.get("s", "0"))
                        gap = curr_s - prev_end_s
                        if gap > 0.05:
                            connector_endpoint_errors.append({
                                "road_id": rid,
                                "type": "planview_gap",
                                "prev_geometry_index": i - 1,
                                "gap_m": round(gap, 3),
                            })

        # Cross-road elevation gradient sampling.
        #
        # The within-road loop above only compares consecutive <elevation>
        # records inside the SAME road's elevationProfile. In this map's
        # common encoding, most roads carry exactly one elevation record
        # each, so that loop alone always yields num_segments==0 even on a
        # sloped map -- a dead sub-metric that silently "passes". Sample the
        # elevation gradient across road-to-road successor links as well, so
        # real elevation change between consecutive roads is measured.
        for road in roads:
            link_elem = road.find("link")
            if link_elem is None:
                continue
            succ = link_elem.find("successor")
            if succ is None:
                continue
            if (succ.get("elementType") or "").strip() != "road":
                continue
            succ_id = succ.get("elementId", "")
            succ_road = road_ids.get(succ_id)
            if succ_road is None:
                continue

            road_len = _safe_float(road.get("length"))
            contact_point = (succ.get("contactPoint") or "start").strip().lower()
            succ_len = _safe_float(succ_road.get("length"))
            succ_s = 0.0 if contact_point != "end" else succ_len

            z_from = _elevation_at_s(road, road_len)
            z_to = _elevation_at_s(succ_road, succ_s)
            if z_from is None or z_to is None:
                continue

            # Use the s-distance between the two sampled points (along each
            # road's own arc length) as a deterministic, always-positive
            # denominator for the gradient estimate.
            ds = max(1e-6, road_len - 0.0) if road_len > 0 else 1e-6
            gradient = abs(z_to - z_from) / ds
            max_elevation_gradient = max(max_elevation_gradient, gradient)
            elevation_variance.append(gradient)

        graph_components = FullMapMetricsScanner._compute_connected_components(
            roads, junctions
        )

        seam_heading_diffs: list[float] = []
        for road in roads:
            planview = road.find("planView")
            if planview is None:
                continue
            geoms = planview.findall("geometry")
            if len(geoms) < 2:
                continue
            for i in range(1, len(geoms)):
                prev_hdg = float(geoms[i - 1].get("hdg", "0"))
                curr_hdg = float(geoms[i].get("hdg", "0"))
                diff = abs(prev_hdg - curr_hdg) % (2 * math.pi)
                if diff > math.pi:
                    diff = 2 * math.pi - diff
                seam_heading_diffs.append(math.degrees(diff))

        junction_roads = 0
        junction_lane_count = 0
        for junction in junctions:
            for conn in junction.findall("connection"):
                conn_road_id = conn.get("connectingRoad", "")
                if conn_road_id in road_ids:
                    junction_roads += 1
                    conn_road = road_ids[conn_road_id]
                    conn_lanes = conn_road.find("lanes")
                    if conn_lanes is not None:
                        for ls in conn_lanes.findall("laneSection"):
                            for side in ("left", "center", "right"):
                                side_elem = ls.find(side)
                                if side_elem is not None:
                                    junction_lane_count += len(
                                        side_elem.findall("lane")
                                    )

        p50 = 0.0
        p95 = 0.0
        max_seam = 0.0
        if seam_heading_diffs:
            sorted_diffs = sorted(seam_heading_diffs)
            p50 = sorted_diffs[len(sorted_diffs) // 2]
            p95 = sorted_diffs[int(len(sorted_diffs) * 0.95)]
            max_seam = sorted_diffs[-1]

        elev_variance_val = 0.0
        if elevation_variance:
            mean_v = sum(elevation_variance) / len(elevation_variance)
            elev_variance_val = sum(
                (v - mean_v) ** 2 for v in elevation_variance
            ) / len(elevation_variance)

        lane_val = {
            "total": total_lanes,
            "driving": total_driving_lanes,
            "non_driving": total_lanes - total_driving_lanes,
            "by_type": lane_types,
        }

        return {
            "road_count": road_count,
            "junction_count": junction_count,
            "junction_connecting_roads": junction_roads,
            "junction_lanes": junction_lane_count,
            "lane_validity": lane_val,
            "total_lanelinks": total_lanelinks,
            "connector_endpoint_errors": {
                "total": len(connector_endpoint_errors),
                "details": connector_endpoint_errors,
            },
            "elevation_continuity": {
                "max_gradient": round(max_elevation_gradient, 6),
                "variance": round(elev_variance_val, 6),
                "num_segments": len(elevation_variance),
            },
            "graph_components": {
                "count": graph_components["count"],
                "sizes": graph_components["sizes"],
            },
            "seam_distribution": {
                "p50_deg": round(p50, 2),
                "p95_deg": round(p95, 2),
                "max_deg": round(max_seam, 2),
                "num_seams": len(seam_heading_diffs),
            },
            "ok": True,
        }

    @staticmethod
    def _compute_connected_components(
        roads: list[ET.Element],
        junctions: list[ET.Element],
    ) -> dict[str, Any]:
        adj: dict[str, set[str]] = {}
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

        visited: set[str] = set()
        components: list[set[str]] = []
        all_nodes = set(adj.keys())
        for node in all_nodes:
            if node in visited:
                continue
            stack = [node]
            comp: set[str] = set()
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

        return {
            "count": len(components),
            "sizes": sorted((len(c) for c in components), reverse=True),
        }
