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
            if jref is None or jref == "-1":
                continue
            if jref not in junction_ids:
                issues.append({
                    "type": "road_references_missing_junction",
                    "road_id": rid,
                    "junction": jref,
                })

        return {
            "ok": len(issues) == 0,
            "issue_count": len(issues),
            "issues": issues,
        }
