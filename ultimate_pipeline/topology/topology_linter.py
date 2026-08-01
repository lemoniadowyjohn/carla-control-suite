# ultimate_pipeline/topology/topology_linter.py

import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Dict, Set, List

from ultimate_pipeline.core.validation_report import ValidationReport
from ultimate_pipeline.core.xodr_sanitizer import XODRSanitizer
_safe_float = XODRSanitizer._safe_float



class TopologyLinter:
    """
    TopologyLinter Pro:
    Performs static checks on the OpenDRIVE network:

    TL-001: Connectivity of road graph (disconnected components)
    TL-002: Lane parity at junction connections
    TL-003: Invalid predecessor/successor references
    TL-004: laneSection s > road.length
    TL-005: Zero-length or extremely short roads
    TL-006: Geometry s-order / overflow vs road.length
    TL-007: Junction connections referencing missing/self roads
    TL-008: Suspicious elevation coefficients
    TL-009: Suspicious lane widths (<=0 or absurdly large)
    """

    # ==========================
    # Helper: road graph
    # ==========================
    @staticmethod
    def _road_graph(root: ET.Element) -> Dict[str, Set[str]]:
        graph: Dict[str, Set[str]] = defaultdict(set)
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}
        for rid, road in roads.items():
            link = road.find("link")
            if link is None:
                continue
            for tag in ("predecessor", "successor"):
                for e in link.findall(tag):
                    if e.get("elementType") != "road":
                        continue
                    eid = e.get("elementId")
                    if not eid or eid not in roads or eid == rid:
                        continue
                    graph[rid].add(eid)
                    graph[eid].add(rid)
        return graph

    # ==========================
    # TL-001: Connectivity
    # ==========================
    @staticmethod
    def _check_connectivity(root: ET.Element, report: ValidationReport):
        graph = TopologyLinter._road_graph(root)
        road_ids = [r.get("id") for r in root.findall("road") if r.get("id")]
        if not road_ids:
            report.add("fatal", "topology_linter", "TL-001: No roads present in map.")
            return

        visited: Set[str] = set()
        stack = [road_ids[0]]

        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            for nb in graph.get(cur, []):
                if nb not in visited:
                    stack.append(nb)

        disconnected = [r for r in road_ids if r not in visited]
        if disconnected:
            msg = (
                f"TL-001: {len(disconnected)} roads are disconnected from main component "
                f"(e.g. {', '.join(disconnected[:10])})."
            )
            report.add("warning", "topology_linter", msg)
        else:
            report.add("info", "topology_linter", "TL-001: Road graph is fully connected or single-component.")

    # ==========================
    # Helper: lane counts
    # ==========================
    @staticmethod
    def _lane_counts_for_edge_section(road: ET.Element, at_start: bool):
        secs = list(road.findall("./lanes/laneSection"))
        if not secs:
            return 0, 0
        secs.sort(key=lambda s: _safe_float(s.get("s", "0"), 0.0))
        sec = secs[0] if at_start else secs[-1]
        left = sec.find("left")
        right = sec.find("right")
        left_count = len(left.findall("lane")) if left is not None else 0
        right_count = len(right.findall("lane")) if right is not None else 0
        return left_count, right_count

    # ==========================
    # TL-002: Lane parity at junctions
    # ==========================
    @staticmethod
    def _check_lane_parity(root: ET.Element, report: ValidationReport):
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}
        mismatches = 0
        for junc in root.findall("junction"):
            jid = junc.get("id", "?")
            for conn in junc.findall("connection"):
                inc_id = conn.get("incomingRoad")
                con_id = conn.get("connectingRoad")
                cpt = conn.get("contactPoint", "start")

                if inc_id not in roads or con_id not in roads:
                    continue

                inc_l, inc_r = TopologyLinter._lane_counts_for_edge_section(roads[inc_id], at_start=False)
                con_l, con_r = TopologyLinter._lane_counts_for_edge_section(
                    roads[con_id], at_start=(cpt != "end")
                )

                if inc_l != con_l or inc_r != con_r:
                    mismatches += 1

        if mismatches:
            report.add(
                "warning",
                "topology_linter",
                f"TL-002: {mismatches} junction connections have lane parity mismatch.",
            )
        else:
            report.add("info", "topology_linter", "TL-002: Lane parity at junctions looks consistent.")

    # ==========================
    # TL-003: Invalid predecessor/successor refs
    # ==========================
    @staticmethod
    def _check_invalid_links(root: ET.Element, report: ValidationReport):
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}
        errors = 0

        for rid, road in roads.items():
            link = road.find("link")
            if link is None:
                continue
            for tag in ("predecessor", "successor"):
                for e in link.findall(tag):
                    etype = e.get("elementType")
                    eid = e.get("elementId")
                    if etype != "road":
                        errors += 1
                        report.add(
                            "error",
                            "topology_linter",
                            f"TL-003: Road {rid} {tag} refers to non-road elementType={etype}.",
                        )
                        continue
                    if not eid or eid not in roads:
                        errors += 1
                        report.add(
                            "error",
                            "topology_linter",
                            f"TL-003: Road {rid} {tag} refers to missing road id={eid}.",
                        )
                        continue
                    if eid == rid:
                        errors += 1
                        report.add(
                            "error",
                            "topology_linter",
                            f"TL-003: Road {rid} {tag} refers to itself (id={eid}).",
                        )

        if errors == 0:
            report.add("info", "topology_linter", "TL-003: All predecessor/successor road references look valid.")

    # ==========================
    # TL-004: laneSection bounds
    # ==========================
    @staticmethod
    def _check_laneSection_bounds(root: ET.Element, report: ValidationReport):
        """
        laneSection.s must not exceed road.length.
        CARLA and SUMO both choke on these.
        """
        errors = 0

        for road in root.findall("road"):
            rid = road.get("id", "?")
            road_length = _safe_float(road.get("length", "0"), 0.0)

            for ls in road.findall(".//laneSection"):
                s = _safe_float(ls.get("s", "0"), 0.0)
                if s > road_length + 1e-6:
                    errors += 1
                    report.add(
                        "error",
                        "topology_linter",
                        f"TL-004: laneSection s={s:.3f} exceeds road {rid} length={road_length:.3f}.",
                    )

        if errors == 0:
            report.add("info", "topology_linter", "TL-004: laneSection bounds OK (no section starts beyond road length).")

    # ==========================
    # TL-005: Zero-length roads
    # ==========================
    @staticmethod
    def _check_zero_length_roads(root: ET.Element, report: ValidationReport):
        tiny = []
        for road in root.findall("road"):
            rid = road.get("id", "?")
            length = _safe_float(road.get("length", "0"), 0.0)
            if length < 0.5:
                tiny.append((rid, length))

        if tiny:
            sample = ", ".join(f"{rid}({length:.2f}m)" for rid, length in tiny[:10])
            report.add(
                "warning",
                "topology_linter",
                f"TL-005: {len(tiny)} roads are very short (<0.5m), e.g. {sample}. May cause unstable meshing.",
            )
        else:
            report.add("info", "topology_linter", "TL-005: No zero-length or tiny roads detected.")

    # ==========================
    # TL-006: Geometry s-order / overflow
    # ==========================
    @staticmethod
    def _check_geometry_s_and_overflow(root: ET.Element, report: ValidationReport):
        """
        Check that:
        - geometry s-values are non-decreasing within each road
        - geometry segments do not extend far beyond road.length
        """
        s_violations = 0
        overflow = 0

        for road in root.findall("road"):
            rid = road.get("id", "?")
            rlen = _safe_float(road.get("length", "0"), 0.0)
            last_s = -1e9

            for geo in road.findall("./planView/geometry"):
                s = _safe_float(geo.get("s", "0"), 0.0)
                glen = _safe_float(geo.get("length", "0"), 0.0)

                if s + glen > rlen + 1e-3:
                    overflow += 1
                    report.add(
                        "warning",
                        "topology_linter",
                        f"TL-006: Road {rid} geometry at s={s:.3f} length={glen:.3f} exceeds road length={rlen:.3f}.",
                    )

                if s < last_s - 1e-6:
                    s_violations += 1
                    report.add(
                        "warning",
                        "topology_linter",
                        f"TL-006: Road {rid} geometry s-values are not sorted (s={s:.3f} after {last_s:.3f}).",
                    )
                last_s = max(last_s, s)

        if s_violations == 0 and overflow == 0:
            report.add("info", "topology_linter", "TL-006: Geometry s-order and extents look consistent.")

    # ==========================
    # TL-007: Junction references
    # ==========================
    @staticmethod
    def _check_junction_refs(root: ET.Element, report: ValidationReport):
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}
        errors = 0

        for junc in root.findall("junction"):
            jid = junc.get("id", "?")
            conns = junc.findall("connection")
            if not conns:
                report.add("warning", "topology_linter", f"TL-007: Junction {jid} has no connections.")
                continue

            for conn in conns:
                inc = conn.get("incomingRoad")
                con = conn.get("connectingRoad")

                if not inc or not con:
                    errors += 1
                    report.add(
                        "error",
                        "topology_linter",
                        f"TL-007: Junction {jid} has connection with missing road ids (incoming={inc}, connecting={con}).",
                    )
                    continue

                if inc == con:
                    errors += 1
                    report.add(
                        "error",
                        "topology_linter",
                        f"TL-007: Junction {jid} has self-connection (road {inc}).",
                    )

                if inc not in roads or con not in roads:
                    errors += 1
                    report.add(
                        "error",
                        "topology_linter",
                        f"TL-007: Junction {jid} connects missing road(s): incoming={inc}, connecting={con}.",
                    )

        if errors == 0:
            report.add("info", "topology_linter", "TL-007: Junction road references look valid.")

    # ==========================
    # TL-008: Elevation anomalies
    # ==========================
    @staticmethod
    def _check_elevation_anomalies(root: ET.Element, report: ValidationReport):
        """
        Check elevationProfile/elevation 'a' coefficients for absurd values.
        Typically |a| > 50 indicates bad unit scaling or NaN poisoning.
        """
        bad = 0
        for road in root.findall("road"):
            rid = road.get("id", "?")
            for ev in road.findall("elevationProfile/elevation"):
                a = _safe_float(ev.get("a", "0"), 0.0)
                if abs(a) > 50.0:
                    bad += 1
                    report.add(
                        "warning",
                        "topology_linter",
                        f"TL-008: Road {rid} has suspicious elevation a={a:.3f} (|a|>50).",
                    )

        if bad == 0:
            report.add("info", "topology_linter", "TL-008: Elevation coefficients look reasonable.")

    # ==========================
    # TL-009: Lane width anomalies
    # ==========================
    @staticmethod
    def _check_lane_widths(root: ET.Element, report: ValidationReport):
        """
        Detect lanes with:
        - non-positive widths
        - absurd widths (e.g. > 15m)
        """
        non_pos = 0
        huge = 0

        for w in root.findall(".//lane/width"):
            a = _safe_float(w.get("a", "0"), 0.0)
            if a <= 0.0:
                non_pos += 1
            elif a > 15.0:
                huge += 1

        if non_pos:
            report.add(
                "error",
                "topology_linter",
                f"TL-009: {non_pos} lanes have non-positive width coefficients (a<=0).",
            )
        if huge:
            report.add(
                "warning",
                "topology_linter",
                f"TL-009: {huge} lanes have huge width coefficients (a>15m).",
            )
        if non_pos == 0 and huge == 0:
            report.add("info", "topology_linter", "TL-009: Lane widths are within normal range.")

    # ==========================
    # Public entry point
    # ==========================
    @staticmethod
    def run(root: ET.Element, report: ValidationReport) -> None:
        """
        Execute all topology lint rules on the given OpenDRIVE root.
        Results are appended into the provided ValidationReport instance.
        """
        TopologyLinter._check_connectivity(root, report)          # TL-001
        TopologyLinter._check_lane_parity(root, report)           # TL-002
        TopologyLinter._check_invalid_links(root, report)         # TL-003
        TopologyLinter._check_laneSection_bounds(root, report)    # TL-004
        TopologyLinter._check_zero_length_roads(root, report)     # TL-005
        TopologyLinter._check_geometry_s_and_overflow(root, report)  # TL-006
        TopologyLinter._check_junction_refs(root, report)         # TL-007
        TopologyLinter._check_elevation_anomalies(root, report)   # TL-008
        TopologyLinter._check_lane_widths(root, report)           # TL-009
