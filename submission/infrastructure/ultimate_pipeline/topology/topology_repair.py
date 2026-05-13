# ultimate_pipeline/topology/topology_repair.py

import xml.etree.ElementTree as ET
from typing import Set

from ultimate_pipeline.core.xodr_sanitizer import _safe_float
from ultimate_pipeline.core.repair_diff import diff_log

class TopologyRepair:
    """
    Conservative topology repair:
    - removes invalid link references
    - removes invalid junction connections
    - ensures each road does not reference itself
    """

    @staticmethod
    def _fix_links(root: ET.Element):
        all_ids: Set[str] = {r.get("id") for r in root.findall("road") if r.get("id")}
        for road in root.findall("road"):
            rid = road.get("id", "")
            link = road.find("link")
            if link is None:
                continue
            seen = set()
            for tag in ("predecessor", "successor"):
                for e in list(link.findall(tag)):
                    etype = e.get("elementType")
                    eid = e.get("elementId")
                    cpt = e.get("contactPoint", "")
                    bad = (etype != "road") or (not eid) or (eid not in all_ids) or (eid == rid)
                    key = (tag, etype, eid, cpt)
                    if bad or key in seen:
                        link.remove(e)
                        diff_log.add(
                            "topology_repair",
                            rid,
                            {
                                "fix": "removed_link",
                                "tag": tag,
                                "etype": etype,
                                "eid": eid,
                                "contactPoint": cpt,
                                "reason": "invalid_or_duplicate",
                            },
                        )
                    else:
                        seen.add(key)


    @staticmethod
    def _fix_junctions(root: ET.Element):
        all_ids: Set[str] = {r.get("id") for r in root.findall("road") if r.get("id")}
        for j in root.findall("junction"):
            seen = set()
            for conn in list(j.findall("connection")):
                inc = conn.get("incomingRoad")
                con = conn.get("connectingRoad")
                cpt = conn.get("contactPoint", "")
                bad = (not inc) or (not con) or (inc == con) or (inc not in all_ids) or (con not in all_ids)
                key = (inc, con, cpt)
                if bad or key in seen:
                    j.remove(conn)
                    diff_log.add(
                        "topology_repair",
                        f"junction_{j.get('id', 'UNKNOWN')}",
                        {
                            "fix": "removed_connection",
                            "incomingRoad": inc,
                            "connectingRoad": con,
                            "contactPoint": cpt,
                            "reason": "invalid_or_duplicate",
                        },
                    )
                else:
                    seen.add(key)


    @staticmethod
    def _remove_empty_junctions(root: ET.Element):
        for j in list(root.findall("junction")):
            if not list(j.findall("connection")):
                root.remove(j)

    @staticmethod
    def run(root: ET.Element) -> None:
        TopologyRepair._fix_links(root)
        TopologyRepair._fix_junctions(root)
        TopologyRepair._remove_empty_junctions(root)
        print("✓ TopologyRepair: basic link/junction cleanup applied.")
