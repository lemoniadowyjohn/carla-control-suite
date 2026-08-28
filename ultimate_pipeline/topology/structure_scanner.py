# ultimate_pipeline/topology/structure_scanner.py

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
StructureScanner v2 — NON-DESTRUCTIVE, DIAGNOSTIC-ONLY

This module analyzes an OpenDRIVE map and reports:
    1) Curvature anomalies (roads with absurd curvature spikes).
    2) Lane-section discontinuities (s-ordering and width jumps).
    3) Junction density statistics (per-road junction counts).
    4) Elevation jumps (suspicious z-discontinuities).
    5) Roads with zero geometry elements.
    6) Graph reachability islands (disconnected components).

It DOES NOT:
    - Remove roads.
    - Modify junctions.
    - Rewrite geometry.
    - Change any XML in-place.

Safe to run on large city-scale OSM → XODR maps.
"""

import math
from collections import defaultdict, deque
from typing import Dict, Any, List, Tuple, Optional

import xml.etree.ElementTree as ET


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    """Robust float parsing that never throws and never returns NaN/inf."""
    if value is None:
        return default
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


class StructureScanner:
    # Tunable thresholds (kept conservative)
    CURVATURE_ABS_MIN_THRESHOLD = 0.5        # 1/m, anything above this is suspicious for city roads
    CURVATURE_PERCENTILE = 0.99              # use 99th percentile + abs min
    LANE_WIDTH_JUMP_THRESH = 3.0             # meters, sudden total-width change between laneSections
    ELEVATION_JUMP_DZ_MIN = 5.0              # meters, big vertical step
    ELEVATION_SLOPE_MIN = 1.0                # dz/ds, very steep
    ISLAND_MIN_SIZE = 20                     # roads; smaller components are “islands”

    @staticmethod
    def analyze(root: ET.Element) -> Dict[str, Any]:
        """
        Analyze the given OpenDRIVE XML root and return a JSON-serializable report.
        """
        # ----------------- basic road graph -----------------
        roads: Dict[str, ET.Element] = {
            r.get("id"): r for r in root.findall("road") if r.get("id") is not None
        }
        preds: Dict[str, List[str]] = defaultdict(list)
        succs: Dict[str, List[str]] = defaultdict(list)

        for rid, road in roads.items():
            link = road.find("link")
            if link is None:
                continue

            for p in link.findall("predecessor"):
                if p.get("elementType") == "road":
                    eid = p.get("elementId")
                    if eid:
                        preds[rid].append(eid)

            for s in link.findall("successor"):
                if s.get("elementType") == "road":
                    eid = s.get("elementId")
                    if eid:
                        succs[rid].append(eid)

        # ------------------------------------------------------------------
        # 1) Curvature anomalies
        # ------------------------------------------------------------------
        curvature_report = StructureScanner._analyze_curvature(roads)

        # ------------------------------------------------------------------
        # 2) Lane-section discontinuities
        # ------------------------------------------------------------------
        lane_section_report = StructureScanner._analyze_lane_sections(roads)

        # ------------------------------------------------------------------
        # 3) Junction density statistics
        # ------------------------------------------------------------------
        junction_report, broken_junc_refs = StructureScanner._analyze_junctions(root, roads)

        # ------------------------------------------------------------------
        # 4) Elevation jumps
        # ------------------------------------------------------------------
        elevation_report = StructureScanner._analyze_elevation(roads)

        # ------------------------------------------------------------------
        # 5) Zero-geometry roads
        # ------------------------------------------------------------------
        zero_geom_roads = StructureScanner._find_zero_geometry_roads(roads)

        # ------------------------------------------------------------------
        # 6) Graph reachability / islands
        # ------------------------------------------------------------------
        graph_islands = StructureScanner._analyze_graph_islands(roads, preds, succs)

        # ------------------------------------------------------------------
        # Legacy-style quick checks (for compatibility with old report keys)
        # ------------------------------------------------------------------
        multi_successor = [rid for rid in roads if len(succs[rid]) > 1]
        multi_predecessor = [rid for rid in roads if len(preds[rid]) > 1]
        self_links = [rid for rid in roads if rid in preds[rid] or rid in succs[rid]]

        report: Dict[str, Any] = {
            # Legacy keys (non-destructive; just counts)
            "multi_successor": multi_successor,
            "multi_predecessor": multi_predecessor,
            "self_links": self_links,
            "broken_junction_refs": broken_junc_refs,
            "zero_geometry_roads": zero_geom_roads,

            # New rich diagnostics
            "curvature_anomalies": curvature_report,
            "lane_section_issues": lane_section_report,
            "junction_stats": junction_report,
            "elevation_anomalies": elevation_report,
            "graph_islands": graph_islands,
        }

        return report

    # ======================================================================
    # 1) Curvature analysis
    # ======================================================================
    @staticmethod
    def _analyze_curvature(roads: Dict[str, ET.Element]) -> Dict[str, Any]:
        """
        For each road, estimate a "max absolute curvature" from planView geometries.
        Prefer arc curvature if available, otherwise approximate from heading deltas.
        Returns:
            {
                "per_road": [{"road_id": ..., "max_abs_curvature": ...}, ...],
                "threshold": float,
                "global_stats": {...},
                "anomalous_roads": [ ...subset of per_road... ]
            }
        """
        per_road_max: Dict[str, float] = {}
        all_curvatures: List[float] = []

        for rid, road in roads.items():
            pv = road.find("planView")
            if pv is None:
                continue

            geos = pv.findall("geometry")
            if not geos:
                continue

            max_abs_k = 0.0

            # pass 1: use arc curvature where present
            for g in geos:
                length = max(_safe_float(g.get("length"), 0.01), 1e-3)
                arc = g.find("arc")
                if arc is not None:
                    k = _safe_float(arc.get("curvature"), 0.0)
                else:
                    # no explicit curvature; we'll approximate later if needed
                    k = 0.0
                max_abs_k = max(max_abs_k, abs(k))

            # pass 2: estimate curvature from heading deltas if everything was 0
            if max_abs_k == 0.0 and len(geos) > 1:
                for i in range(len(geos) - 1):
                    g0 = geos[i]
                    g1 = geos[i + 1]
                    hdg0 = _safe_float(g0.get("hdg"), 0.0)
                    hdg1 = _safe_float(g1.get("hdg"), 0.0)
                    dpsi = StructureScanner._wrap_angle(hdg1 - hdg0)
                    length = max(_safe_float(g0.get("length"), 0.01), 1e-3)
                    k_est = abs(dpsi) / length  # very rough estimate
                    max_abs_k = max(max_abs_k, k_est)

            if max_abs_k > 0.0:
                per_road_max[rid] = max_abs_k
                all_curvatures.append(max_abs_k)

        if not all_curvatures:
            return {
                "per_road": [],
                "threshold": None,
                "global_stats": {},
                "anomalous_roads": []
            }

        # basic stats
        all_curvatures_sorted = sorted(all_curvatures)
        n = len(all_curvatures_sorted)

        def percentile(p: float) -> float:
            if n == 1:
                return all_curvatures_sorted[0]
            idx = int(p * (n - 1))
            return all_curvatures_sorted[idx]

        mean_k = sum(all_curvatures_sorted) / n
        max_k = all_curvatures_sorted[-1]
        p99 = percentile(StructureScanner.CURVATURE_PERCENTILE)

        threshold = max(
            StructureScanner.CURVATURE_ABS_MIN_THRESHOLD,
            p99
        )

        per_road_entries = [
            {"road_id": rid, "max_abs_curvature": k}
            for rid, k in per_road_max.items()
        ]

        anomalous = [
            entry for entry in per_road_entries
            if entry["max_abs_curvature"] >= threshold
        ]

        return {
            "per_road": per_road_entries,
            "threshold": threshold,
            "global_stats": {
                "count": n,
                "mean": mean_k,
                "max": max_k,
                "p99": p99,
            },
            "anomalous_roads": anomalous,
        }

    @staticmethod
    def _wrap_angle(rad: float) -> float:
        """Wrap angle to [-pi, pi]."""
        while rad > math.pi:
            rad -= 2.0 * math.pi
        while rad < -math.pi:
            rad += 2.0 * math.pi
        return rad

    # ======================================================================
    # 2) Lane-section discontinuities
    # ======================================================================
    @staticmethod
    def _analyze_lane_sections(roads: Dict[str, ET.Element]) -> Dict[str, Any]:
        """
        Detect:
            - non-monotonic laneSection s values per road
            - large total-width jumps across laneSections

        Returns:
            {
              "non_monotonic": [ {"road_id":..., "s_values":[...]}, ... ],
              "width_jumps": [ {"road_id":..., "from_idx":.., "to_idx":.., "width0":.., "width1":.., "delta":..}, ... ],
              "summary": {...}
            }
        """
        non_monotonic = []
        width_jumps = []

        for rid, road in roads.items():
            lanes = road.find("lanes")
            if lanes is None:
                continue

            sections = lanes.findall("laneSection")
            if len(sections) <= 1:
                continue

            # as-declared s values (XML document order) -- OpenDRIVE requires
            # laneSections to appear in strictly increasing s order, so this
            # check must run BEFORE any sorting, against the order the file
            # actually declares. (Sorting first and then checking the sorted
            # list for "non-monotonicity" can, by construction, only ever
            # detect exact ties -- it can never see the file listed sections
            # out of order, since sorting silently fixes the very defect
            # being checked for.)
            declared_s_values = [_safe_float(ls.get("s"), 0.0) for ls in sections]

            # 1) monotonic check (strictly increasing, as declared in the file)
            for i in range(len(declared_s_values) - 1):
                if declared_s_values[i + 1] <= declared_s_values[i]:
                    non_monotonic.append({
                        "road_id": rid,
                        "s_values": declared_s_values,
                    })
                    break

            # sort sections by s for the width-jump analysis below, which
            # cares about width deltas along increasing s regardless of
            # whether the file declared them in order.
            sec_info = []
            for ls in sections:
                s = _safe_float(ls.get("s"), 0.0)
                sec_info.append((s, ls))
            sec_info.sort(key=lambda x: x[0])

            s_values = [s for s, _ in sec_info]

            # 2) total width per section
            widths = []
            for s, ls in sec_info:
                total_width = 0.0

                # Left side lanes
                left = ls.find("left")
                if left is not None:
                    for lane in left.findall("lane"):
                        w = StructureScanner._lane_width_at_zero(lane)
                        total_width += abs(w)

                # Right side lanes
                right = ls.find("right")
                if right is not None:
                    for lane in right.findall("lane"):
                        w = StructureScanner._lane_width_at_zero(lane)
                        total_width += abs(w)

                widths.append(total_width)

            # successive differences
            for i in range(len(widths) - 1):
                w0 = widths[i]
                w1 = widths[i + 1]
                d = abs(w1 - w0)
                if d >= StructureScanner.LANE_WIDTH_JUMP_THRESH:
                    width_jumps.append({
                        "road_id": rid,
                        "from_index": i,
                        "to_index": i + 1,
                        "s0": s_values[i],
                        "s1": s_values[i + 1],
                        "width0": w0,
                        "width1": w1,
                        "delta": d,
                    })

        summary = {
            "non_monotonic_count": len(non_monotonic),
            "width_jump_count": len(width_jumps),
            "width_jump_threshold": StructureScanner.LANE_WIDTH_JUMP_THRESH,
        }

        return {
            "non_monotonic": non_monotonic,
            "width_jumps": width_jumps,
            "summary": summary,
        }

    @staticmethod
    def _lane_width_at_zero(lane_elem: ET.Element) -> float:
        """
        Approximate lane width at sOffset=0 from first <width> element.
        """
        w = lane_elem.find("width")
        if w is None:
            return 0.0
        a = _safe_float(w.get("a"), 0.0)
        return a

    # ======================================================================
    # 3) Junction density & broken refs
    # ======================================================================
    @staticmethod
    def _analyze_junctions(root: ET.Element, roads: Dict[str, ET.Element]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        road_ids = set(roads.keys())
        road_junc_count = defaultdict(int)
        broken_refs: List[Dict[str, Any]] = []

        total_junctions = 0

        for j in root.findall("junction"):
            total_junctions += 1
            jid = j.get("id", "?")

            for conn in j.findall("connection"):
                inc = conn.get("incomingRoad")
                con = conn.get("connectingRoad")

                if inc in road_ids:
                    road_junc_count[inc] += 1
                else:
                    broken_refs.append({
                        "junction_id": jid,
                        "incoming": inc,
                        "connecting": con,
                        "type": "missing_incomingRoad",
                    })

                if con in road_ids:
                    road_junc_count[con] += 1
                else:
                    broken_refs.append({
                        "junction_id": jid,
                        "incoming": inc,
                        "connecting": con,
                        "type": "missing_connectingRoad",
                    })

        per_road = [
            {"road_id": rid, "junction_count": c}
            for rid, c in road_junc_count.items()
        ]

        if per_road:
            counts = [r["junction_count"] for r in per_road]
            avg = sum(counts) / len(counts)
            max_c = max(counts)
        else:
            avg = 0.0
            max_c = 0

        # simple histogram
        hist = defaultdict(int)
        for c in road_junc_count.values():
            hist[c] += 1
        histogram = [{"junction_count": k, "num_roads": v} for k, v in sorted(hist.items())]

        stats = {
            "total_junctions": total_junctions,
            "num_roads_with_junctions": len(road_junc_count),
            "avg_junctions_per_road": avg,
            "max_junctions_for_any_road": max_c,
            "histogram": histogram,
        }

        return {
            "per_road": per_road,
            "stats": stats,
        }, broken_refs

    # ======================================================================
    # 4) Elevation jumps
    # ======================================================================
    @staticmethod
    def _analyze_elevation(roads: Dict[str, ET.Element]) -> Dict[str, Any]:
        """
        Looks for suspicious z-jumps in elevationProfile.

        Approximation: use 'a' coefficient as height at 's0'.
        """
        per_road = []
        all_slopes = []

        for rid, road in roads.items():
            ep = road.find("elevationProfile")
            if ep is None:
                continue

            elevs = []
            for e in ep.findall("elevation"):
                s0 = _safe_float(e.get("s"), 0.0)
                a = _safe_float(e.get("a"), 0.0)
                elevs.append((s0, a))

            if len(elevs) < 2:
                continue

            elevs.sort(key=lambda x: x[0])

            max_dz = 0.0
            max_slope = 0.0
            anomalies_local = []

            for i in range(len(elevs) - 1):
                s0, z0 = elevs[i]
                s1, z1 = elevs[i + 1]
                ds = max(abs(s1 - s0), 0.1)
                dz = z1 - z0
                slope = dz / ds

                max_dz = max(max_dz, abs(dz))
                max_slope = max(max_slope, abs(slope))
                all_slopes.append(abs(slope))

                if abs(dz) >= StructureScanner.ELEVATION_JUMP_DZ_MIN and abs(slope) >= StructureScanner.ELEVATION_SLOPE_MIN:
                    anomalies_local.append({
                        "from_s": s0,
                        "to_s": s1,
                        "z0": z0,
                        "z1": z1,
                        "dz": dz,
                        "slope": slope,
                    })

            if max_dz > 0.0 or max_slope > 0.0:
                per_road.append({
                    "road_id": rid,
                    "max_abs_dz": max_dz,
                    "max_abs_slope": max_slope,
                    "local_anomalies": anomalies_local,
                })

        # global stats
        if all_slopes:
            all_slopes_sorted = sorted(all_slopes)
            n = len(all_slopes_sorted)
            mean_slope = sum(all_slopes_sorted) / n
            max_slope = all_slopes_sorted[-1]
        else:
            mean_slope = 0.0
            max_slope = 0.0

        return {
            "per_road": per_road,
            "thresholds": {
                "dz_min": StructureScanner.ELEVATION_JUMP_DZ_MIN,
                "slope_min": StructureScanner.ELEVATION_SLOPE_MIN,
            },
            "global_stats": {
                "num_slope_segments": len(all_slopes),
                "mean_abs_slope": mean_slope,
                "max_abs_slope": max_slope,
            },
        }

    # ======================================================================
    # 5) Zero-geometry roads
    # ======================================================================
    @staticmethod
    def _find_zero_geometry_roads(roads: Dict[str, ET.Element]) -> List[str]:
        zero = []
        for rid, road in roads.items():
            pv = road.find("planView")
            if pv is None:
                zero.append(rid)
                continue
            geos = pv.findall("geometry")
            if not geos:
                zero.append(rid)
        return zero

    # ======================================================================
    # 6) Graph reachability / islands
    # ======================================================================
    @staticmethod
    def _analyze_graph_islands(
        roads: Dict[str, ET.Element],
        preds: Dict[str, List[str]],
        succs: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """
        Build an undirected graph from predecessor/successor relations and
        find connected components.

        Small components are reported as "islands".
        """
        neighbors: Dict[str, set] = {rid: set() for rid in roads.keys()}

        # undirected edges from preds/succs
        for rid in roads:
            for s in succs.get(rid, []):
                if s in neighbors:
                    neighbors[rid].add(s)
                    neighbors[s].add(rid)
            for p in preds.get(rid, []):
                if p in neighbors:
                    neighbors[rid].add(p)
                    neighbors[p].add(rid)

        visited = set()
        components: List[List[str]] = []

        for rid in neighbors.keys():
            if rid in visited:
                continue
            comp = []
            q = deque([rid])
            visited.add(rid)
            while q:
                cur = q.popleft()
                comp.append(cur)
                for nb in neighbors[cur]:
                    if nb not in visited:
                        visited.add(nb)
                        q.append(nb)
            components.append(comp)

        total_roads = len(roads)
        components.sort(key=len, reverse=True)

        largest_size = components[0] and len(components[0]) if components else 0

        islands = []
        min_island_size = StructureScanner.ISLAND_MIN_SIZE
        for comp in components:
            if len(comp) < min_island_size:
                islands.append({
                    "size": len(comp),
                    # don't dump 1000 IDs; cap for report
                    "roads": comp[:50],
                })

        return {
            "num_components": len(components),
            "largest_component_size": largest_size,
            "total_roads": total_roads,
            "islands_min_size": min_island_size,
            "num_islands": len(islands),
            "islands": islands,
        }

    # ======================================================================
    # Pretty summary
    # ======================================================================
    @staticmethod
    def summarize(report: Dict[str, Any]) -> None:
        """
        Console summary. Non-fatal; just prints counts and some key stats.
        """
        print("\n🧠 Structure Scanner v2 Report:")

        # Legacy quick checks
        ms = len(report.get("multi_successor", []) or [])
        mp = len(report.get("multi_predecessor", []) or [])
        sl = len(report.get("self_links", []) or [])
        bjr = len(report.get("broken_junction_refs", []) or [])
        zg = len(report.get("zero_geometry_roads", []) or [])

        print(f"  ✓ multi_successor:          {ms} roads flagged")
        print(f"  ✓ multi_predecessor:        {mp} roads flagged")
        print(f"  ✓ self_links:               {sl} roads flagged")
        print(f"  ✓ broken_junction_refs:     {bjr} issues")
        print(f"  ✓ zero_geometry_roads:      {zg} roads")

        # Curvature
        curv = report.get("curvature_anomalies", {}) or {}
        curv_stats = curv.get("global_stats", {}) or {}
        curv_anom = curv.get("anomalous_roads", []) or []
        print("  🌀 Curvature:")
        print(f"     roads analyzed:          {curv_stats.get('count', 0)}")
        print(f"     max curvature:           {curv_stats.get('max', 0.0):.4f}")
        print(f"     p99 curvature:           {curv_stats.get('p99', 0.0):.4f}")
        print(f"     anomaly threshold:       {curv.get('threshold', 0.0)}")
        print(f"     anomalous roads:         {len(curv_anom)}")

        # Lane sections
        lanes = report.get("lane_section_issues", {}) or {}
        ls_sum = lanes.get("summary", {}) or {}
        print("  🚧 Lane sections:")
        print(f"     non-monotonic roads:     {ls_sum.get('non_monotonic_count', 0)}")
        print(f"     width jumps:             {ls_sum.get('width_jump_count', 0)} "
              f"(threshold={ls_sum.get('width_jump_threshold', 0.0)} m)")

        # Junctions
        junc = report.get("junction_stats", {}) or {}
        jstats = junc.get("stats", {}) or {}
        print("  ⚓ Junctions:")
        print(f"     total junctions:         {jstats.get('total_junctions', 0)}")
        print(f"     roads with junctions:    {jstats.get('num_roads_with_junctions', 0)}")
        print(f"     avg junctions/road:      {jstats.get('avg_junctions_per_road', 0.0):.3f}")
        print(f"     max junctions for a road:{jstats.get('max_junctions_for_any_road', 0)}")

        # Elevation
        elev = report.get("elevation_anomalies", {}) or {}
        estats = elev.get("global_stats", {}) or {}
        print("  🏔 Elevation:")
        print(f"     slope segments:          {estats.get('num_slope_segments', 0)}")
        print(f"     mean |dz/ds|:            {estats.get('mean_abs_slope', 0.0):.3f}")
        print(f"     max  |dz/ds|:            {estats.get('max_abs_slope', 0.0):.3f}")

        # Graph islands
        gi = report.get("graph_islands", {}) or {}
        print("  🕸 Graph connectivity:")
        print(f"     components:              {gi.get('num_components', 0)}")
        print(f"     largest component size:  {gi.get('largest_component_size', 0)}")
        print(f"     islands (<{gi.get('islands_min_size', 0)} roads): {gi.get('num_islands', 0)}")

        print("  (All checks are diagnostic-only; no roads were harmed.)")
