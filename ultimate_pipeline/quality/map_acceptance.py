#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Map acceptance summary for gating perception runs.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from ultimate_pipeline.utils.file_hashing import safe_sha256_file
from ultimate_pipeline.tools.crash_safe_length_repair import (
    TOL_M as LENGTH_INVARIANT_TOL_M,
    length_invariant_summary,
)


def _run_id_from_out_dir(out_dir: Optional[str]) -> Optional[str]:
    if not out_dir:
        return None
    base = os.path.basename(os.path.normpath(out_dir))
    return base or None


def _artifact_path_from_report(report: Dict[str, Any]) -> Optional[str]:
    for key in ("artifact_path", "report_path", "path", "output"):
        value = report.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _reason_from_report(report: Dict[str, Any]) -> str:
    for key in ("reason", "error", "message"):
        value = report.get(key)
        if isinstance(value, str) and value:
            return value
    decision = report.get("decision")
    if isinstance(decision, dict):
        value = decision.get("reason")
        if isinstance(value, str) and value:
            return value
    if "issues" in report:
        return f"issues={len(report.get('issues') or [])}"
    if "failures" in report:
        return f"failures={len(report.get('failures') or [])}"
    if "still_broken_count" in report:
        return f"still_broken_count={report.get('still_broken_count')}"
    if "broken_count" in report:
        return f"broken_count={report.get('broken_count')}"
    return "gate_failed"


def _determine_report_ok(report: Dict[str, Any]) -> Optional[bool]:
    if "ok" in report:
        return bool(report.get("ok"))
    decision = report.get("decision")
    if isinstance(decision, dict) and "pass" in decision:
        return bool(decision.get("pass"))
    return None


def _determine_lane_ok(report: Dict[str, Any]) -> Optional[bool]:
    if "ok" in report:
        return bool(report.get("ok"))
    if "still_broken_count" in report:
        return int(report.get("still_broken_count") or 0) == 0
    if "broken_count" in report:
        return int(report.get("broken_count") or 0) == 0
    if "num_issues" in report:
        return int(report.get("num_issues") or 0) == 0
    if "failures" in report:
        return len(report.get("failures") or []) == 0
    return None


def _lane_missing_count(report: Dict[str, Any]) -> Optional[int]:
    if "still_broken_count" in report:
        return int(report.get("still_broken_count") or 0)
    if "broken_count" in report:
        return int(report.get("broken_count") or 0)
    if "num_issues" in report:
        return int(report.get("num_issues") or 0)
    if "failures" in report:
        return len(report.get("failures") or [])
    return None


def _write_acceptance(out_dir: Optional[str], run_id: Optional[str], payload: Dict[str, Any]) -> Optional[str]:
    if not out_dir or not run_id:
        return None
    try:
        art_dir = os.path.join(out_dir, "artifacts", run_id)
        os.makedirs(art_dir, exist_ok=True)
        path = os.path.join(art_dir, "map_acceptance.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=True)
        return path
    except Exception:
        return None


def _enrichment_completeness_counts(final_xodr_path: str) -> Optional[Dict[str, int]]:
    """CODEX C7: count buildings + functional signals directly from the XODR.

    Reconciles the "signals" metric so a genuinely enriched map (traffic
    lights represented as paired <object>+<signal>, see
    ultimate_pipeline/enrichment/traffic_light_infer.py) is never reported
    as signals=0 just because the legacy prop-only representation is also
    present.
    """
    try:
        root = ET.parse(final_xodr_path).getroot()
    except Exception:
        return None

    buildings_count = len(root.findall(".//object[@type='building']"))
    functional_signals_count = len(root.findall(".//signal"))
    traffic_light_object_count = len(root.findall(".//object[@type='traffic_light']"))

    return {
        "buildings_count": buildings_count,
        "functional_signals_count": functional_signals_count,
        "traffic_light_object_count": traffic_light_object_count,
    }


class _UnionFind:
    """Tiny union-find for lane-topology connected components."""

    def __init__(self) -> None:
        self._parent: Dict[str, str] = {}

    def _find(self, x: str) -> str:
        parent = self._parent
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        parent = self._parent
        if a not in parent:
            parent[a] = a
        if b not in parent:
            parent[b] = b
        ra, rb = self._find(a), self._find(b)
        if ra != rb:
            parent[ra] = rb


def component_reachability_summary(root: Any) -> Optional[Dict[str, Any]]:
    """Offline lane-topology reachability (the live-CARLA probe finding:
    spawn points on isolated road components never drive even with
    TrafficManager).

    Builds a lane graph from <laneSection>/<lane>/<link> successor+
    predecessor edges (both within-road lane-section transitions and
    cross-road junction links), then reports connected components. A map
    whose drivable network is fragmented has a low
    largest_component_fraction — autopilot routes can never cross such
    fragments, so capture spawn points on them produce dead runs.
    """
    try:
        uf = _UnionFind()
        roads: Dict[str, List[Any]] = {}
        node_sections: Dict[str, List[Any]] = {}
        road_elems: Dict[str, Any] = {}
        for road in root.findall(".//road"):
            rid = road.get("id", "")
            sections = road.findall("./lanes/laneSection")
            roads[rid] = sections
            node_sections[rid] = sections
            road_elems[rid] = road

        def _node(rid: str, section_idx: int, lane_id: str) -> str:
            return f"{rid}:{section_idx}:{lane_id}"

        def _is_driving(lane: Any) -> bool:
            return lane.get("type") == "driving"

        unmatched_cross_links = 0
        lane_count = 0
        for rid, sections in roads.items():
            for si, section in enumerate(sections):
                for lane in section.findall(".//lane"):
                    lid = lane.get("id")
                    if lid is None or lid == "0" or not _is_driving(lane):
                        continue
                    lane_count += 1
                    node = _node(rid, si, lid)
                    uf.union(node, node)
                    link = lane.find("./link")
                    if link is None:
                        continue
                    for tag in ("successor", "predecessor"):
                        el = link.find(f"./{tag}")
                        if el is None:
                            continue
                        target_lid = el.get("id")
                        if el.get("elementType") == "road":
                            # Cross-road junction link.
                            target_road = el.get("elementId")
                            contact = el.get("contactPoint")
                            target_sections = node_sections.get(target_road)
                            if not target_sections:
                                unmatched_cross_links += 1
                                continue
                            if contact == "start":
                                tsi = 0
                            elif contact == "end":
                                tsi = len(target_sections) - 1
                            else:
                                unmatched_cross_links += 1
                                continue
                            # Resolve the counterpart lane: explicit id, else
                            # same |lane| sign in the target section.
                            if target_lid is not None and target_lid != "0":
                                found = any(
                                    l.get("id") == target_lid
                                    for l in target_sections[tsi].findall("./lane")
                                )
                            else:
                                sign = "-" if lid.startswith("-") else ""
                                found = any(
                                    l.get("id") == f"{sign}{abs(int(lid))}"
                                    for l in target_sections[tsi].findall("./lane")
                                )
                            if found:
                                uf.union(node, _node(target_road, tsi, target_lid or str(abs(int(lid)))))
                            else:
                                unmatched_cross_links += 1
                        elif target_lid is not None:
                            # Within-road transition to adjacent lane section.
                            if tag == "successor":
                                tsi = si + 1
                            else:
                                tsi = si - 1
                            if 0 <= tsi < len(sections):
                                uf.union(node, _node(rid, tsi, target_lid))
                            # Out-of-range = the road-end marker this generator
                            # writes; boundary connectivity is provided by the
                            # junction / road-level link passes below.

        # Road-level links of type "road" (elementType=road): the boundary
        # lanes of this road connect to the same-id boundary lanes of the
        # target road. These are the authoritative outer-road <-> connecting
        # road connectors in this pipeline's output.
        for rid, sections in roads.items():
            if not sections:
                continue
            link = road_elems[rid].find("./link")
            if link is None or len(link) == 0:
                continue
            for tag in ("successor", "predecessor"):
                el = link.find(f"./{tag}")
                if el is None or el.get("elementType") != "road":
                    continue
                target_road = el.get("elementId")
                contact = el.get("contactPoint")
                target_sections = node_sections.get(target_road)
                if not target_sections:
                    unmatched_cross_links += 1
                    continue
                src_tsi = len(sections) - 1 if tag == "successor" else 0
                target_tsi = 0 if contact == "start" else len(target_sections) - 1
                src_lanes = sections[src_tsi].findall(".//lane")
                target_lanes = target_sections[target_tsi].findall(".//lane")
                target_ids = {l.get("id") for l in target_lanes}
                for lane in src_lanes:
                    lid = lane.get("id")
                    if lid is None or lid == "0":
                        continue
                    if lid in target_ids:
                        uf.union(_node(rid, src_tsi, lid), _node(target_road, target_tsi, lid))
                    else:
                        # Tolerate a flipped contactPoint (generator quirk):
                        # try the other boundary of the target road.
                        alt_tsi = 0 if target_tsi > 0 else len(target_sections) - 1
                        if lid in {l.get("id") for l in target_sections[alt_tsi].findall(".//lane")}:
                            uf.union(_node(rid, src_tsi, lid), _node(target_road, alt_tsi, lid))
                        else:
                            unmatched_cross_links += 1

        # Junction pass: roads connect through <junction><connection> elements.
        # Each connection's <laneLink from=.. to=..> maps a lane of the
        # incomingRoad (at its junction-side boundary section) to a lane of the
        # connectingRoad. The connection's contactPoint is unreliable in this
        # generator's output (always "start"), so the boundary section is
        # resolved by trying the contactPoint side first, then the other end.
        for junction in root.findall(".//junction"):
            for conn in junction.findall("./connection"):
                in_road = conn.get("incomingRoad")
                conn_road = conn.get("connectingRoad")
                contact = conn.get("contactPoint")
                if not in_road or not conn_road:
                    continue
                in_sections = node_sections.get(in_road)
                conn_sections = node_sections.get(conn_road)
                if not in_sections or not conn_sections:
                    unmatched_cross_links += len(conn.findall("./laneLink"))
                    continue
                in_tsi = 0 if contact == "start" else len(in_sections) - 1
                conn_tsi = 0  # connecting road attaches to the junction at s=0
                in_lanes = {l.get("id") for l in in_sections[in_tsi].findall(".//lane")}
                conn_lanes = {l.get("id") for l in conn_sections[conn_tsi].findall(".//lane")}
                for ll in conn.findall("./laneLink"):
                    frm = ll.get("from")
                    to = ll.get("to")
                    if frm is None or to is None:
                        continue
                    in_tsi_used = in_tsi
                    conn_tsi_used = conn_tsi
                    if frm not in in_lanes:
                        alt = 0 if in_tsi > 0 else len(in_sections) - 1
                        if frm in {l.get("id") for l in in_sections[alt].findall(".//lane")}:
                            in_tsi_used = alt
                    if to not in conn_lanes:
                        alt = 0 if conn_tsi > 0 else len(conn_sections) - 1
                        if to in {l.get("id") for l in conn_sections[alt].findall(".//lane")}:
                            conn_tsi_used = alt
                    if frm in {l.get("id") for l in in_sections[in_tsi_used].findall(".//lane")} and to in {
                        l.get("id") for l in conn_sections[conn_tsi_used].findall(".//lane")
                    }:
                        uf.union(_node(in_road, in_tsi_used, frm), _node(conn_road, conn_tsi_used, to))
                    else:
                        unmatched_cross_links += 1

        if lane_count == 0:
            return None

        comp_sizes: Dict[str, int] = {}
        for rid, sections in roads.items():
            for si in range(len(sections)):
                for lane in sections[si].findall(".//lane"):
                    lid = lane.get("id")
                    if lid is None or lid == "0" or not _is_driving(lane):
                        continue
                    node = _node(rid, si, lid)
                    comp = uf._find(node)
                    comp_sizes[comp] = comp_sizes.get(comp, 0) + 1

        component_count = len(comp_sizes)
        largest = max(comp_sizes.values(), default=0)
        isolated_count = sum(1 for size in comp_sizes.values() if size <= 1)
        return {
            "ok": None,  # set by the acceptance gate when opted in
            "lane_count": lane_count,
            "component_count": component_count,
            "largest_component_lane_count": largest,
            "largest_component_fraction": round(largest / lane_count, 6),
            "isolated_lane_component_count": isolated_count,
            "unmatched_cross_links": unmatched_cross_links,
        }
    except Exception:
        return None


def build_map_acceptance(
    reports: Dict[str, Any],
    *,
    run_id: str | None = None,
    final_xodr_path: str | None = None,
    out_dir: str | None = None,
    require_enrichment: bool = False,
    require_component_reachability: bool = False,
) -> Dict[str, Any]:
    hard_fail_reasons: List[Dict[str, str]] = []
    soft_warnings: List[Dict[str, str]] = []
    metrics: Dict[str, Any] = {}
    linked_artifacts: Dict[str, str] = {}

    if not run_id:
        run_id = _run_id_from_out_dir(out_dir)

    final_xodr_sha256 = None
    if final_xodr_path and os.path.exists(final_xodr_path):
        final_xodr_sha256 = safe_sha256_file(final_xodr_path)

    seam = reports.get("elevation_seams")
    if isinstance(seam, dict):
        metrics["seam_stats"] = seam.get("seam_stats")
        metrics["elevation_stats"] = seam.get("elevation_stats")
        art = _artifact_path_from_report(seam)
        if art:
            linked_artifacts["elevation_seams"] = art
        if seam.get("ok") is False:
            hard_fail_reasons.append({"gate": "elevation_seams", "reason": _reason_from_report(seam)})

    dem = reports.get("dem_coverage")
    if isinstance(dem, dict):
        ratio = dem.get("coverage_ratio")
        if ratio is None:
            ratio = dem.get("valid_ratio")
        metrics["dem_coverage_ratio"] = ratio
        art = _artifact_path_from_report(dem)
        if art:
            linked_artifacts["dem_coverage"] = art
        if dem.get("ok") is False:
            hard_fail_reasons.append({"gate": "dem_coverage", "reason": _reason_from_report(dem)})

    geom = reports.get("geometric_continuity")
    if isinstance(geom, dict):
        geom_ok = _determine_report_ok(geom)
        metrics["geometric_continuity_ok"] = geom_ok
        art = _artifact_path_from_report(geom)
        if art:
            linked_artifacts["geometric_continuity"] = art
        if geom_ok is False:
            hard_fail_reasons.append({"gate": "geometric_continuity", "reason": _reason_from_report(geom)})

    lane_section = reports.get("lane_section_successors")
    if isinstance(lane_section, dict):
        lane_ok = _determine_lane_ok(lane_section)
        metrics["lane_ok"] = lane_ok
        missing = _lane_missing_count(lane_section)
        if missing is not None:
            metrics["lane_successor_missing_count"] = missing
        art = _artifact_path_from_report(lane_section)
        if art:
            linked_artifacts["lane_section_successors"] = art
        if lane_ok is False:
            hard_fail_reasons.append({"gate": "lane_section_successors", "reason": _reason_from_report(lane_section)})

    lane_conn = reports.get("lane_connectivity")
    if isinstance(lane_conn, dict):
        lane_ok = _determine_lane_ok(lane_conn)
        metrics["lane_ok"] = lane_ok if metrics.get("lane_ok") is None else metrics.get("lane_ok")
        missing = _lane_missing_count(lane_conn)
        if missing is not None and "lane_successor_missing_count" not in metrics:
            metrics["lane_successor_missing_count"] = missing
        art = _artifact_path_from_report(lane_conn)
        if art:
            linked_artifacts["lane_connectivity"] = art
        if lane_ok is False:
            hard_fail_reasons.append({"gate": "lane_connectivity", "reason": _reason_from_report(lane_conn)})

    length_invariant = reports.get("length_invariant")
    if isinstance(length_invariant, dict) and "violations" in length_invariant:
        # A pre-computed evidence dict was supplied (e.g. from the
        # certifier's _length_invariant_evidence). Trust it as-is -- do NOT
        # recompute with a different tolerance.
        li_violations = int(length_invariant.get("violations") or 0)
        metrics["length_invariant_violations"] = li_violations
        metrics["length_invariant_tol_m"] = LENGTH_INVARIANT_TOL_M
        art = _artifact_path_from_report(length_invariant)
        if art:
            linked_artifacts["length_invariant"] = art
        if li_violations > 0:
            hard_fail_reasons.append(
                {
                    "gate": "length_invariant",
                    "reason": f"violations={li_violations} (tol={LENGTH_INVARIANT_TOL_M:g}m)",
                }
            )
    elif final_xodr_path and os.path.exists(final_xodr_path):
        # No pre-computed evidence was supplied: measure directly from the
        # final candidate using the EXACT same helper (and tolerance,
        # 1e-9) as run_n_certify._length_invariant_evidence, so the
        # acceptance gate and the certifier can never disagree due to a
        # tolerance mismatch. A sub-1e-6 excess must be caught by both.
        try:
            li_root = ET.parse(final_xodr_path).getroot()
            li_summary = length_invariant_summary(li_root)
        except Exception:
            li_summary = None
        if li_summary is not None:
            li_violations = int(li_summary.get("violations") or 0)
            metrics["length_invariant_violations"] = li_violations
            metrics["length_invariant_tol_m"] = LENGTH_INVARIANT_TOL_M
            if li_violations > 0:
                hard_fail_reasons.append(
                    {
                        "gate": "length_invariant",
                        "reason": f"violations={li_violations} (tol={LENGTH_INVARIANT_TOL_M:g}m)",
                    }
                )

    origin = reports.get("origin_sanity")
    if isinstance(origin, dict):
        dist = origin.get("centroid_distance_m")
        metrics["origin_centroid_distance_m"] = dist
        art = _artifact_path_from_report(origin)
        if art:
            linked_artifacts["origin_sanity"] = art
        if origin.get("ok") is False:
            if isinstance(dist, (int, float)) and dist > 500_000.0:
                hard_fail_reasons.append({"gate": "origin_sanity", "reason": _reason_from_report(origin)})
            else:
                soft_warnings.append({"gate": "origin_sanity", "reason": _reason_from_report(origin)})

    # Junction integrity (WS1.4 follow-up, 2026-09-02): dangling
    # <junction><connection> references (incoming/connecting road or lane
    # missing) build an unusable junction -- CARLA/SUMO can crash on load or
    # silently drop the connector. Discovered live: map_hygiene.py's island
    # quarantine left exactly this kind of dangling reference behind for
    # every road it removed, and nothing in the acceptance pipeline caught
    # it. Always a hard fail when present, matching geometric_continuity/
    # lane_connectivity -- not opt-in, since a dangling junction reference is
    # a genuine structural defect a "valid" map should never have.
    junction_integrity = reports.get("junction_integrity")
    if isinstance(junction_integrity, dict):
        ji_ok = junction_integrity.get("ok")
        metrics["junction_integrity_ok"] = ji_ok
        metrics["junction_integrity_issue_count"] = junction_integrity.get("issue_count")
        art = _artifact_path_from_report(junction_integrity)
        if art:
            linked_artifacts["junction_integrity"] = art
        if ji_ok is False:
            hard_fail_reasons.append(
                {"gate": "junction_integrity", "reason": _reason_from_report(junction_integrity)}
            )

    # CODEX C7: enrichment completeness (buildings + functional signals).
    # Always measured (visible in metrics) so the map is never silently
    # reported as signals=0 when it actually carries <signal> elements or
    # traffic_light <object> props. Only hard-fails when the caller opts in
    # via require_enrichment=True (the "enriched map of record" build path);
    # manual/geometry-only reference maps legitimately have 0 of either and
    # must not be broken by this gate.
    if final_xodr_path and os.path.exists(final_xodr_path):
        enrich_counts = _enrichment_completeness_counts(final_xodr_path)
        if enrich_counts is not None:
            metrics["buildings_count"] = enrich_counts["buildings_count"]
            metrics["functional_signals_count"] = enrich_counts["functional_signals_count"]
            metrics["traffic_light_object_count"] = enrich_counts["traffic_light_object_count"]
            if require_enrichment:
                reasons = []
                if enrich_counts["buildings_count"] <= 0:
                    reasons.append("buildings_count=0")
                if (
                    enrich_counts["functional_signals_count"] <= 0
                    and enrich_counts["traffic_light_object_count"] <= 0
                ):
                    reasons.append("functional_signals_count=0 and traffic_light_object_count=0")
                if reasons:
                    hard_fail_reasons.append(
                        {
                            "gate": "enrichment_completeness",
                            "reason": "; ".join(reasons),
                        }
                    )

    # Component reachability (live-probe finding): lanes unreachable from the
    # main drivable component can never be autopilot-routed, so capture spawn
    # points on them produce dead runs. Always measured (metric + soft
    # warning); hard-fails only when the caller opts in via
    # require_component_reachability=True, with the threshold
    # largest_component_fraction >= 0.95 (<=5% of lanes on islands).
    comp_rep = reports.get("component_reachability")
    if isinstance(comp_rep, dict) and isinstance(comp_rep.get("largest_component_fraction"), (int, float)):
        pass  # precomputed evidence supplied by the caller
    elif final_xodr_path and os.path.exists(final_xodr_path):
        try:
            comp_root = ET.parse(final_xodr_path).getroot()
        except Exception:
            comp_root = None
        if comp_root is not None:
            comp_rep = component_reachability_summary(comp_root)
    if isinstance(comp_rep, dict) and isinstance(comp_rep.get("largest_component_fraction"), (int, float)):
        metrics["lane_component_count"] = comp_rep.get("component_count")
        metrics["lane_count_total"] = comp_rep.get("lane_count")
        metrics["largest_component_fraction"] = comp_rep.get("largest_component_fraction")
        metrics["largest_component_lane_count"] = comp_rep.get("largest_component_lane_count")
        metrics["isolated_lane_component_count"] = comp_rep.get("isolated_lane_component_count")
        metrics["unmatched_cross_links"] = comp_rep.get("unmatched_cross_links")
        if int(comp_rep.get("isolated_lane_component_count") or 0) > 0:
            soft_warnings.append(
                {
                    "gate": "component_reachability",
                    "reason": (
                        f"{comp_rep.get('isolated_lane_component_count')} isolated lane "
                        f"components (largest={comp_rep.get('largest_component_fraction')})"
                    ),
                }
            )
        if require_component_reachability:
            fraction = float(comp_rep.get("largest_component_fraction"))
            if fraction < 0.95:
                hard_fail_reasons.append(
                    {
                        "gate": "component_reachability",
                        "reason": (
                            f"largest_component_fraction={fraction} < 0.95 "
                            f"(component_count={comp_rep.get('component_count')})"
                        ),
                    }
                )

    valid_for_experiments = len(hard_fail_reasons) == 0
    payload = {
        "run_id": run_id,
        "final_xodr_path": final_xodr_path,
        "final_xodr_sha256": final_xodr_sha256,
        "valid_for_experiments": valid_for_experiments,
        "hard_fail_reasons": hard_fail_reasons,
        "soft_warnings": soft_warnings,
        "metrics": metrics,
        "linked_artifacts": linked_artifacts,
    }
    payload["valid"] = valid_for_experiments
    payload["failed_gates"] = [item["gate"] for item in hard_fail_reasons]

    artifact_path = _write_acceptance(out_dir, run_id, payload)
    if artifact_path:
        payload["acceptance_artifact"] = artifact_path

    return payload
