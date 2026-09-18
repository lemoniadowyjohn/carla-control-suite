#!/usr/bin/env python3
"""
Fix missing lane-level successors by inferring from road/junction topology.

Deterministic repair for CARLA lane connectivity invariant violations.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Optional


def _get_road_successor(road: ET.Element) -> Optional[Tuple[str, str, str]]:
    """
    Get road-level successor.
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


def _build_junction_connection_index(root: ET.Element) -> Dict[str, List[Dict]]:
    """
    Build index: connectingRoad -> [connection records]
    Each record: {junction_id, incomingRoad, laneLinks: [{from, to}]}
    """
    index: Dict[str, List[Dict]] = {}
    for junction in root.findall("junction"):
        jid = junction.get("id")
        for conn in junction.findall("connection"):
            connecting = conn.get("connectingRoad")
            incoming = conn.get("incomingRoad")

            lane_links = []
            for ll in conn.findall("laneLink"):
                lane_links.append({
                    "from": ll.get("from"),
                    "to": ll.get("to"),
                })

            rec = {
                "junction_id": jid,
                "incomingRoad": incoming,
                "laneLinks": lane_links,
            }

            if connecting not in index:
                index[connecting] = []
            index[connecting].append(rec)

    return index


def _lane_has_successor(lane: ET.Element) -> bool:
    """Check if lane already has a successor element."""
    link = lane.find("link")
    if link is None:
        return False
    return link.find("successor") is not None


def _ensure_lane_link_element(lane: ET.Element) -> ET.Element:
    """Ensure lane has <link> child; create if missing."""
    link = lane.find("link")
    if link is None:
        link = ET.SubElement(lane, "link")
    return link


def fix_missing_lane_successors(
    xodr_path: str,
    output_path: str,
    allow_dead_ends: bool = True,
) -> Dict:
    """
    Fix missing lane-level successors by inferring from road topology.

    Returns:
        {
            "fixed_count": int,
            "still_broken": [{road_id, lane_id, reason}],
            "fallback_applied": int,
            "dead_ends_allowed": int,
        }
    """
    tree = ET.parse(xodr_path)
    root = tree.getroot()

    # Build junction index
    junction_index = _build_junction_connection_index(root)

    fixed_count = 0
    fallback_applied = 0
    dead_ends_allowed = 0
    still_broken = []

    for road in root.findall("road"):
        road_id = road.get("id")
        junction_attr = road.get("junction")
        is_junction_road = junction_attr and junction_attr != "-1"

        # Get road-level successor
        road_succ = _get_road_successor(road)

        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            continue

        for lane_section in lanes_elem.findall("laneSection"):
            # Check all lane types (not just driving - to be safe)
            for side in ["left", "center", "right"]:
                side_elem = lane_section.find(side)
                if side_elem is None:
                    continue

                for lane in side_elem.findall("lane"):
                    lane_id = lane.get("id")
                    lane_type = lane.get("type")

                    # Only fix driving lanes (and maybe shoulder/parking if critical)
                    if lane_type not in ("driving", "shoulder", "parking"):
                        continue

                    # Skip if already has successor
                    if _lane_has_successor(lane):
                        continue

                    # Skip center lane (id=0)
                    if lane_id == "0":
                        continue

                    # Try to infer successor
                    successor_lane_id = None
                    is_dead_end = False
                    is_fallback = False

                    # Strategy 1: Use road-level successor (simple case)
                    if road_succ and road_succ[0] == "road":
                        # Assume same lane ID on successor road
                        successor_lane_id = lane_id

                    # Strategy 2: Junction connection mapping
                    elif is_junction_road and road_id in junction_index:
                        # Check if there's a laneLink mapping for this lane
                        for conn in junction_index[road_id]:
                            for ll in conn["laneLinks"]:
                                if ll["to"] == lane_id:
                                    # This lane receives traffic; need to check road successor
                                    if road_succ and road_succ[0] == "road":
                                        successor_lane_id = lane_id
                                    break
                            if successor_lane_id:
                                break

                    # Strategy 3: Dead-end detection
                    if not successor_lane_id and allow_dead_ends:
                        if not road_succ:
                            # Road has no successor -> legitimate dead-end
                            is_dead_end = True
                            dead_ends_allowed += 1
                            continue  # Skip adding successor

                    # Strategy 4: Fallback (best-effort to avoid crash)
                    if not successor_lane_id and not is_dead_end:
                        # As last resort, assume same lane ID if road has successor
                        if road_succ:
                            successor_lane_id = lane_id
                            is_fallback = True
                            fallback_applied += 1

                    # Apply fix if we determined a successor
                    if successor_lane_id:
                        link = _ensure_lane_link_element(lane)

                        # Remove existing successor if somehow present
                        existing_succ = link.find("successor")
                        if existing_succ is not None:
                            link.remove(existing_succ)

                        # Create new successor element
                        succ = ET.SubElement(link, "successor")
                        succ.set("id", successor_lane_id)

                        fixed_count += 1

                    # Still broken if not fixed and not a dead-end
                    elif not is_dead_end and lane_type == "driving":
                        still_broken.append({
                            "road_id": road_id,
                            "lane_id": lane_id,
                            "lane_type": lane_type,
                            "reason": "cannot_infer_successor",
                            "is_junction_road": is_junction_road,
                            "has_road_successor": road_succ is not None,
                        })

    # Save fixed XODR
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

    return {
        "fixed_count": fixed_count,
        "still_broken": still_broken,
        "fallback_applied": fallback_applied,
        "dead_ends_allowed": dead_ends_allowed,
        "input_xodr": xodr_path,
        "output_xodr": output_path,
    }


# CLI for standalone testing
if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Fix missing lane successors")
    parser.add_argument("--xodr", required=True, help="Input XODR")
    parser.add_argument("--out", required=True, help="Output XODR")
    parser.add_argument("--report", help="JSON report path")
    parser.add_argument("--allow-dead-ends", action="store_true", default=True)

    args = parser.parse_args()

    report = fix_missing_lane_successors(
        xodr_path=args.xodr,
        output_path=args.out,
        allow_dead_ends=args.allow_dead_ends,
    )

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    print(f"[fix_missing_lane_successors] Fixed: {report['fixed_count']}")
    print(f"[fix_missing_lane_successors] Still broken: {len(report['still_broken'])}")
    print(f"[fix_missing_lane_successors] Fallback: {report['fallback_applied']}")

    sys.exit(0 if len(report['still_broken']) == 0 else 1)
