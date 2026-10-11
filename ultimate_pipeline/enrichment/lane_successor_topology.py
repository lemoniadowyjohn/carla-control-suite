#!/usr/bin/env python3
"""
Lane successor inference from REAL road topology only.

Generator-stage fix for missing road-to-road lane successors.
Operates on pre-final intermediate data (Stage 7 output), derives successors
from explicit road-level <link> topology and junction laneLinks.

Sources (in priority order):
1. Road-level successor (elementType="road") + same lane ID at boundary.
2. ROAD_SUCCESSOR_IS_JUNCTION: non-junction road points at a junction;
   resolve through the junction's connection/laneLink mapping
   (incomingRoad == this road, laneLink from == this lane) to the unique
   (connectingRoad, to-lane) target. Only written when the topology
   uniquely proves exactly one target.

NO synthetic fallback, NO geometric interpolation, NO ID proximity guessing.
If topology doesn't determine a successor, the lane remains a dead-end.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple, Set


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


def _all_driving_lane_ids(road: ET.Element) -> Set[int]:
    """All driving lane IDs anywhere on a road (any section)."""
    ids: Set[int] = set()
    lanes_elem = road.find("lanes")
    if lanes_elem is None:
        return ids
    for section in lanes_elem.findall("laneSection"):
        ids |= _get_driving_lane_ids(section)
    return ids


def resolve_through_junction(
    roads: Dict[str, ET.Element],
    junctions: Dict[str, ET.Element],
    road_id: str,
    lane_id: int,
) -> Tuple[str, Optional[Tuple[str, str]]]:
    """Resolve a lane successor through a junction successor.

    For a lane on a road whose road-level successor is a junction, walk:
    road -> successor junction -> connection with incomingRoad == road_id
    -> laneLink with from == lane_id -> (connectingRoad, to-lane).

    Returns (bucket, target) where target is (connecting_road_id, lane_id_str)
    only for bucket == "THROUGH_JUNCTION_UNAMBIGUOUS". Every other bucket
    means "do not write" with the reason recorded. Buckets match the Phase 2
    population classifier exactly (same function backs both -- no divergence).
    """
    road = roads.get(road_id)
    if road is None:
        return "ROAD_ELEMENT_MISSING", None
    link = road.find("link")
    succ = link.find("successor") if link is not None else None
    if succ is None or succ.get("elementType") != "junction":
        return "NOT_JUNCTION_SUCCESSOR", None
    junction = junctions.get(succ.get("elementId"))
    if junction is None:
        return "NO_JUNCTION_ELEMENT", None
    conns = [c for c in junction.findall("connection")
             if c.get("incomingRoad") == road_id]
    if not conns:
        return "NO_MATCHING_CONNECTION", None
    candidates = []
    bad_contact = False
    for conn in conns:
        contact = conn.get("contactPoint", "start")
        if contact not in ("start", "end"):
            bad_contact = True
            continue
        connecting = conn.get("connectingRoad")
        if not connecting:
            continue
        for link_el in conn.findall("laneLink"):
            try:
                from_id = int(link_el.get("from"))
                to_id = int(link_el.get("to"))
            except (TypeError, ValueError):
                continue
            if from_id != lane_id:
                continue
            candidates.append((connecting, str(to_id)))
    if bad_contact and not candidates:
        return "CONTACT_POINT_INVALID", None
    if not candidates:
        return "NO_MATCHING_LANELINK", None
    verified = []
    missing_road = False
    missing_lane = False
    for connecting, to_str in candidates:
        target_road = roads.get(connecting)
        if target_road is None:
            missing_road = True
            continue
        try:
            to_id = int(to_str)
        except (TypeError, ValueError):
            missing_lane = True
            continue
        if to_id not in _all_driving_lane_ids(target_road):
            missing_lane = True
            continue
        verified.append((connecting, to_str))
    if not verified:
        if missing_road:
            return "CONNECTING_ROAD_MISSING", None
        return "TARGET_LANE_MISSING", None
    distinct = sorted(set(verified))
    if len(distinct) > 1:
        return "AMBIGUOUS_MULTIPLE_TARGETS", None
    return "THROUGH_JUNCTION_UNAMBIGUOUS", distinct[0]


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


def infer_lane_successors_from_topology(root: ET.Element) -> Dict:
    """
    Infer missing lane-level successors from REAL road topology only.

    Sources (in priority order):
    1. Road-level successor (elementType="road") + same lane ID at the
       target boundary.
    2. ROAD_SUCCESSOR_IS_JUNCTION: road points at a junction; resolve the
       unique (connectingRoad, to-lane) through the junction's
       connection/laneLink mapping (see resolve_through_junction).

    NO synthetic fallback. If no topology determines a successor, lane stays without one.

    Returns:
        {
            "inferred_count": int,          # strategy 1 repairs
            "through_junction_count": int,  # strategy 3 repairs
            "junction_mapped_count": int,   # always 0 -- retained for report
                                            # compatibility only (the old
                                            # strategy-2 branch was dead code
                                            # and has been removed; see HH1)
            "roads_processed": int,
            "lanes_without_topology": int,
        }
    """
    roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}
    junctions = {j.get("id"): j for j in root.findall("junction")}

    inferred_count = 0
    through_junction_count = 0
    lanes_without_topology = 0

    for road_id, road in roads.items():
        road_succ = _get_road_successor(road)

        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            continue

        # Process each laneSection - successors are per-lane, not per-section
        for lane_section in lanes_elem.findall("laneSection"):
            for side_name in ("left", "center", "right"):
                side_elem = lane_section.find(side_name)
                if side_elem is None:
                    continue

                for lane in side_elem.findall("lane"):
                    lane_id_str = lane.get("id")
                    lane_type = lane.get("type")

                    # Only fix driving lanes (shoulder/parking if needed)
                    if lane_type not in ("driving", "shoulder", "parking"):
                        continue

                    # Skip center lane (id=0)
                    if lane_id_str == "0":
                        continue

                    # Skip if already has successor
                    if _lane_has_successor(lane):
                        continue

                    try:
                        lane_id = int(lane_id_str)
                    except (TypeError, ValueError):
                        continue

                    successor_lane_id = None

                    # Strategy 1: Road-level successor with matching lane ID at boundary
                    if road_succ and road_succ[0] == "road":
                        target_road_id = road_succ[1]
                        target_contact = road_succ[2]
                        target_road = roads.get(target_road_id)

                        if target_road is not None:
                            target_section = _get_boundary_lane_section(target_road, target_contact)
                            if target_section is not None:
                                target_driving_ids = _get_driving_lane_ids(target_section)
                                if lane_id in target_driving_ids:
                                    successor_lane_id = str(lane_id)
                                    inferred_count += 1

                    # Strategy 3: road successor is a junction -- resolve the
                    # unique through-junction target. Ambiguous or unproven
                    # cases stay unresolved (never guess).
                    elif road_succ and road_succ[0] == "junction":
                        _bucket, target = resolve_through_junction(
                            roads, junctions, road_id, lane_id)
                        if target is not None:
                            successor_lane_id = target[1]
                            through_junction_count += 1

                    # Apply fix ONLY if topology determines a successor.
                    # Counters were incremented at the strategy that proved
                    # the target, so nothing is counted here.
                    if successor_lane_id:
                        link = _ensure_lane_link(lane)
                        existing = link.find("successor")
                        if existing is not None:
                            link.remove(existing)
                        succ_elem = ET.SubElement(link, "successor")
                        succ_elem.set("id", successor_lane_id)
                    else:
                        lanes_without_topology += 1

    return {
        "inferred_count": inferred_count,
        "through_junction_count": through_junction_count,
        "junction_mapped_count": 0,
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
    print(f"[lane_successor_topology] Through junction: {report['through_junction_count']}")
    print(f"[lane_successor_topology] Junction mapped: {report['junction_mapped_count']}")
    print(f"[lane_successor_topology] Lanes without topology: {report['lanes_without_topology']}")

    sys.exit(0)