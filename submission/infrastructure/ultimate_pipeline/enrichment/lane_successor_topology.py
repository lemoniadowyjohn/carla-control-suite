#!/usr/bin/env python3
"""
Lane successor inference from REAL road topology only.

Generator-stage fix for missing road-to-road and road-to-junction lane
successors. Operates on pre-final intermediate data (Stage 7 output), derives
successors from explicit road-level <link> topology and junction laneLinks.

NO synthetic fallback, NO geometric interpolation, NO ID proximity guessing.
If topology doesn't determine a unique successor, the lane remains without one
and is reported as unresolved.

Strategies
----------
1. ROAD_SUCCESSOR_IS_ROAD: a road whose road-level successor is
   ``elementType="road"``; a lane is linked to the same lane id on the target
   road's boundary laneSection, when that lane exists there.
2. (removed) The former junction laneLink branch was unreachable dead code: it
   was guarded by an ``elif`` that already excluded ``elementType="road"`` and
   then re-checked exactly that condition. It has been deleted; regression
   coverage lives in ``tests/unit/test_lane_successor_topology.py``.
3. ROAD_SUCCESSOR_IS_JUNCTION: a road whose road-level successor is
   ``elementType="junction"``. Junction connections attach at the incoming
   road's END (last laneSection). Each connection's ``<laneLink>`` maps an
   incoming lane (``from``) to a lane on the connecting road (``to``). When the
   laneLink topology yields exactly ONE validated target lane id for a lane
   (unique proof), that id is written as the lane successor. Multiple distinct
   targets (a real lane fork) or no laneLink are left unresolved -- never
   guessed.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple


def _get_road_successor(road: ET.Element) -> Optional[Tuple[str, str, str]]:
    """
    Get road-level successor from explicit <link> element.
    Returns: (elementType, elementId, contactPoint) or None
    """
    link = road.find("link")
    if link is None:
        return None
    succ = link.find("successor")
    if succ is None:
        return None
    return (
        succ.get("elementType"),
        succ.get("elementId"),
        succ.get("contactPoint", "start"),
    )


def _get_road_predecessor(road: ET.Element) -> Optional[Tuple[str, str, str]]:
    """Get road-level predecessor from explicit <link> element."""
    link = road.find("link")
    if link is None:
        return None
    pred = link.find("predecessor")
    if pred is None:
        return None
    return (
        pred.get("elementType"),
        pred.get("elementId"),
        pred.get("contactPoint", "end"),
    )


def _get_boundary_lane_section(road: ET.Element, contact_point: str) -> Optional[ET.Element]:
    """Get the laneSection at the specified road boundary (start/end)."""
    lanes_elem = road.find("lanes")
    if lanes_elem is None:
        return None
    sections = list(lanes_elem.findall("laneSection"))
    if not sections:
        return None
    sections.sort(key=lambda s: float(s.get("s", "0") or 0))
    return sections[0] if contact_point == "start" else sections[-1]


def _get_driving_lane_ids(section: ET.Element) -> Set[int]:
    """Get all driving lane IDs in a laneSection."""
    ids: Set[int] = set()
    for side in ("left", "right", "center"):
        side_elem = section.find(side)
        if side_elem is None:
            continue
        for lane in side_elem.findall("lane"):
            if lane.get("type") == "driving":
                try:
                    ids.add(int(lane.get("id")))
                except (TypeError, ValueError):
                    pass
    return ids


def _build_incoming_lane_candidates(
    root: ET.Element, roads: Dict[str, ET.Element]
) -> Dict[Tuple[str, str], Set[int]]:
    """Map (incomingRoad_id, incoming_lane_id) -> validated target lane ids.

    A target id is validated when it names a *driving* lane on the connecting
    road's boundary laneSection for the connection's ``contactPoint``. Junction
    connections attach to the incoming road at its END; only the connecting
    road boundary obeys ``contactPoint``.
    """
    candidates: Dict[Tuple[str, str], Set[int]] = defaultdict(set)
    for junction in root.findall("junction"):
        for conn in junction.findall("connection"):
            incoming = conn.get("incomingRoad")
            connecting = conn.get("connectingRoad")
            if not incoming or not connecting:
                continue
            if incoming not in roads or connecting not in roads:
                continue
            connecting_section = _get_boundary_lane_section(
                roads[connecting], conn.get("contactPoint", "start")
            )
            if connecting_section is None:
                continue
            driving = _get_driving_lane_ids(connecting_section)
            for lane_link in conn.findall("laneLink"):
                from_id = lane_link.get("from")
                to_id = lane_link.get("to")
                if from_id is None or to_id is None:
                    continue
                try:
                    to_int = int(to_id)
                except (TypeError, ValueError):
                    continue
                if to_int in driving:
                    candidates[(incoming, from_id)].add(to_int)
    return candidates


def _ensure_lane_link(lane: ET.Element) -> ET.Element:
    """Ensure lane has <link> child; create if missing."""
    link = lane.find("link")
    if link is None:
        link = ET.SubElement(lane, "link")
    return link


def _lane_has_successor(lane: ET.Element) -> bool:
    """Check if lane already has a successor element."""
    link = lane.find("link")
    if link is None:
        return False
    return link.find("successor") is not None


def _write_lane_successor(lane: ET.Element, successor_lane_id: str) -> None:
    link = _ensure_lane_link(lane)
    existing = link.find("successor")
    if existing is not None:
        link.remove(existing)
    succ_elem = ET.SubElement(link, "successor")
    succ_elem.set("id", successor_lane_id)


def infer_lane_successors_from_topology(root: ET.Element) -> Dict:
    """
    Infer missing lane-level successors from REAL road topology only.

    Sources (in priority order):
    1. Road-level successor elementType="road" + lane ID match at the target
       boundary laneSection.
    2. Road-level successor elementType="junction": unique validated junction
       laneLink target on the connecting road (terminal laneSection only).

    NO synthetic fallback. If topology does not determine a *unique* successor,
    the lane is left without one and reported as unresolved.

    Returns a report dict with repair counters and the unresolved lane records.
    """
    roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}
    incoming_candidates = _build_incoming_lane_candidates(root, roads)

    inferred_count = 0
    road_to_road_count = 0
    junction_repaired_count = 0
    lanes_without_topology = 0
    unresolved_ambiguous: List[Dict] = []
    unresolved_no_candidate: List[Dict] = []

    for road_id, road in roads.items():
        road_succ = _get_road_successor(road)

        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            continue

        sections = list(lanes_elem.findall("laneSection"))
        sections.sort(key=lambda s: float(s.get("s", "0") or 0))
        last_index = len(sections) - 1

        for section_index, lane_section in enumerate(sections):
            is_terminal = section_index == last_index
            for side_name in ("left", "center", "right"):
                side_elem = lane_section.find(side_name)
                if side_elem is None:
                    continue

                for lane in side_elem.findall("lane"):
                    lane_id_str = lane.get("id")
                    lane_type = lane.get("type")

                    if lane_type not in ("driving", "shoulder", "parking"):
                        continue
                    if lane_id_str == "0":
                        continue
                    if _lane_has_successor(lane):
                        continue

                    successor_lane_id: Optional[str] = None

                    # Strategy 1: ROAD_SUCCESSOR_IS_ROAD (matching lane id at boundary).
                    if road_succ and road_succ[0] == "road":
                        target_road = roads.get(road_succ[1])
                        if target_road is not None:
                            target_section = _get_boundary_lane_section(
                                target_road, road_succ[2]
                            )
                            if target_section is not None:
                                try:
                                    lane_id_int = int(lane_id_str)
                                except (TypeError, ValueError):
                                    lane_id_int = None
                                if (
                                    lane_id_int is not None
                                    and lane_id_int in _get_driving_lane_ids(target_section)
                                ):
                                    successor_lane_id = lane_id_str
                                    road_to_road_count += 1

                    # Strategy 3: ROAD_SUCCESSOR_IS_JUNCTION (unique proof,
                    # terminal laneSection only).
                    elif road_succ and road_succ[0] == "junction" and is_terminal:
                        candidates = incoming_candidates.get((road_id, lane_id_str), set())
                        if len(candidates) == 1:
                            successor_lane_id = str(next(iter(candidates)))
                            junction_repaired_count += 1
                        elif len(candidates) > 1:
                            unresolved_ambiguous.append({
                                "road_id": road_id,
                                "lane_id": lane_id_str,
                                "junction_id": road_succ[1],
                                "candidate_lane_ids": sorted(candidates),
                            })
                        else:
                            unresolved_no_candidate.append({
                                "road_id": road_id,
                                "lane_id": lane_id_str,
                                "junction_id": road_succ[1],
                            })

                    if successor_lane_id is not None:
                        _write_lane_successor(lane, successor_lane_id)
                        inferred_count += 1
                    else:
                        lanes_without_topology += 1

    return {
        "inferred_count": inferred_count,
        "road_to_road_count": road_to_road_count,
        "junction_repaired_count": junction_repaired_count,
        # Backwards-compatible key: junction laneLink repairs (strategy 3).
        "junction_mapped_count": junction_repaired_count,
        "junction_unresolved_ambiguous": len(unresolved_ambiguous),
        "junction_unresolved_no_candidate": len(unresolved_no_candidate),
        "unresolved_ambiguous": unresolved_ambiguous,
        "unresolved_no_candidate": unresolved_no_candidate,
        "roads_processed": len(roads),
        "lanes_without_topology": lanes_without_topology,
    }


# CLI for standalone testing
if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Infer lane successors from road topology (generator stage)")
    parser.add_argument("--xodr", required=True, help="Input XODR")
    parser.add_argument("--out", required=True, help="Output XODR")
    parser.add_argument("--report", help="JSON report path")

    args = parser.parse_args()

    tree = ET.parse(args.xodr)
    root = tree.getroot()

    report = infer_lane_successors_from_topology(root)

    tree.write(args.out, encoding="utf-8", xml_declaration=True)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    print(f"[lane_successor_topology] Inferred: {report['inferred_count']}")
    print(f"[lane_successor_topology] Junction mapped: {report['junction_mapped_count']}")
    print(f"[lane_successor_topology] Lanes without topology: {report['lanes_without_topology']}")

    sys.exit(0)
