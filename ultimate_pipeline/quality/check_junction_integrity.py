"""Junction integrity validation.

This module is intentionally *import-safe* (no CARLA import) and designed as a
lightweight guardrail before expensive steps.

Why this exists
--------------
OpenDRIVE junction metadata is a common source of downstream failures:

- Junction connections referencing non-existent roads.
- Junction connection laneLinks referencing non-existent lane ids.

Some OpenDRIVE consumers treat these as fatal; CARLA can crash or build an
undrivable map.

The validator here is conservative: it focuses on reference integrity.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union


XodrInput = Union[str, os.PathLike, ET.Element]


def _load_root(xodr_path_or_root: XodrInput) -> ET.Element:
    if isinstance(xodr_path_or_root, ET.Element):
        return xodr_path_or_root
    tree = ET.parse(str(xodr_path_or_root))
    return tree.getroot()


def _road_ids(root: ET.Element) -> Set[str]:
    return {r.get("id") for r in root.findall("./road") if r.get("id") is not None}


def _lane_ids_by_road(root: ET.Element) -> Dict[str, Set[str]]:
    """Collect lane ids per road (as strings)."""
    out: Dict[str, Set[str]] = {}
    for road in root.findall("./road"):
        rid = road.get("id")
        if rid is None:
            continue
        lids: Set[str] = set()
        for lane in road.findall(".//lane"):
            lid = lane.get("id")
            if lid is not None:
                lids.add(str(lid))
        out[rid] = lids
    return out


class JunctionIntegrityGate:
    @staticmethod
    def validate(xodr_path_or_root: XodrInput) -> Dict[str, Any]:
        """Validate that junction references point to existing roads/lanes."""

        try:
            root = _load_root(xodr_path_or_root)
        except Exception as e:
            return {"ok": False, "error": f"xml_parse_failed: {e}"}

        road_ids = _road_ids(root)
        lane_ids = _lane_ids_by_road(root)

        issues: List[Dict[str, Any]] = []

        # A junction connection is identified by its incoming/connecting road
        # pair and contact point.  Duplicate rows are almost always generated
        # by an unsafe rewrite; contradictory rows for the same pair cannot be
        # interpreted deterministically by downstream OpenDRIVE consumers.
        for j in root.findall("./junction"):
            jid = j.get("id", "?")
            seen_connections: Dict[Tuple[str, str, str], Tuple[str, Tuple[Tuple[str, str], ...]]] = {}
            for conn in j.findall("./connection"):
                cid = conn.get("id", "?")
                key = (
                    conn.get("incomingRoad", ""),
                    conn.get("connectingRoad", ""),
                    conn.get("contactPoint", ""),
                )
                lane_links = tuple(sorted(
                    (ll.get("from", ""), ll.get("to", ""))
                    for ll in conn.findall("./laneLink")
                ))
                previous = seen_connections.get(key)
                if previous is not None:
                    previous_id, previous_links = previous
                    issue_type = (
                        "conflicting_duplicate_connection"
                        if previous_links != lane_links
                        else "duplicate_connection"
                    )
                    issues.append({
                        "type": issue_type,
                        "junction_id": jid,
                        "connection_id": cid,
                        "duplicate_of": previous_id,
                        "incomingRoad": key[0],
                        "connectingRoad": key[1],
                        "contactPoint": key[2],
                    })
                else:
                    seen_connections[key] = (cid, lane_links)

        # Validate: for each <junction>, ensure its connections reference real roads.
        for j in root.findall("./junction"):
            jid = j.get("id", "?")
            for conn in j.findall("./connection"):
                cid = conn.get("id", "?")
                incoming = conn.get("incomingRoad")
                connecting = conn.get("connectingRoad")

                if incoming is None or incoming not in road_ids:
                    issues.append({
                        "type": "missing_incoming_road",
                        "junction_id": jid,
                        "connection_id": cid,
                        "incomingRoad": incoming,
                    })

                if connecting is None or connecting not in road_ids:
                    issues.append({
                        "type": "missing_connecting_road",
                        "junction_id": jid,
                        "connection_id": cid,
                        "connectingRoad": connecting,
                    })

                # Validate laneLink targets if both roads exist.
                if incoming in road_ids and connecting in road_ids:
                    in_lanes = lane_ids.get(incoming, set())
                    cn_lanes = lane_ids.get(connecting, set())
                    for ll in conn.findall("./laneLink"):
                        frm = ll.get("from")
                        to = ll.get("to")
                        if frm is not None and str(frm) not in in_lanes:
                            issues.append({
                                "type": "missing_lane_in_incoming_road",
                                "junction_id": jid,
                                "connection_id": cid,
                                "incomingRoad": incoming,
                                "lane_from": frm,
                            })
                        if to is not None and str(to) not in cn_lanes:
                            issues.append({
                                "type": "missing_lane_in_connecting_road",
                                "junction_id": jid,
                                "connection_id": cid,
                                "connectingRoad": connecting,
                                "lane_to": to,
                            })

        # Validate road[junction] attribute points to existing junction.
        junction_ids = {j.get("id") for j in root.findall("./junction") if j.get("id") is not None}
        for road in root.findall("./road"):
            rid = road.get("id", "?")
            jref = road.get("junction")
            # OpenDRIVE uses -1 for "not part of a junction".
            if jref is not None and jref != "-1" and jref not in junction_ids:
                issues.append({
                    "type": "road_references_missing_junction",
                    "road_id": rid,
                    "junction": jref,
                })

            link = road.find("./link")
            if link is None:
                continue
            for relation in ("predecessor", "successor"):
                element = link.find(f"./{relation}")
                if element is None:
                    continue
                element_type = element.get("elementType")
                element_id = element.get("elementId")
                known_ids = road_ids if element_type == "road" else junction_ids if element_type == "junction" else set()
                if element_type not in {"road", "junction"} or element_id not in known_ids:
                    issues.append({
                        "type": f"invalid_{relation}_reference",
                        "road_id": rid,
                        "elementType": element_type,
                        "elementId": element_id,
                    })

        # A road must not declare two different predecessor/successor records
        # for the same relation.  XML consumers otherwise disagree on which
        # endpoint is authoritative.
        for road in root.findall("./road"):
            rid = road.get("id", "?")
            link = road.find("./link")
            if link is None:
                continue
            for relation in ("predecessor", "successor"):
                records = link.findall(f"./{relation}")
                if len(records) > 1:
                    issues.append({
                        "type": f"conflicting_{relation}_records",
                        "road_id": rid,
                        "count": len(records),
                    })

        return {
            "ok": len(issues) == 0,
            "issue_count": len(issues),
            "issues": issues,
        }
