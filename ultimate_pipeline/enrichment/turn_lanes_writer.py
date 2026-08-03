# ultimate_pipeline/enrichment/turn_lanes_writer.py
"""
Write OSM turn:lanes values as XODR userData hints.

For each XODR road that has a matching OSM entry with a turn_lanes field,
this module inserts:
    <userData>
        <vector key="turnMarking" value="left|straight|right"/>
    </userData>

Geometry is NOT modified.  These hints can be consumed by downstream lane-marking
renderers or used as metadata in domain-gap analysis.

Threading note:
    Like speed_limit_writer, this requires osm_roads_by_id to be available.
    In the current pipeline, this mapping must be built externally (e.g. by
    parsing the OSM file and matching xodr road ids to osm way ids).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, Any


def apply_turn_lanes(root: ET.Element, osm_roads_by_id: Dict[str, Any]) -> int:
    """
    Stamp <userData><vector key="turnMarking" value="..."/></userData> onto XODR roads
    that have a known OSM turn:lanes value.

    Args:
        root:             Parsed XODR root element (modified in-place).
        osm_roads_by_id:  Mapping from XODR road id (str) → OSMRoad (or dict with
                          'turn_lanes' key).  May be empty.

    Returns:
        Number of roads stamped with turnMarking userData.
    """
    if not osm_roads_by_id:
        return 0

    stamped = 0
    for road in root.findall("road"):
        road_id = road.get("id", "")
        osm = osm_roads_by_id.get(road_id)
        if osm is None:
            continue

        turn_lanes = (
            getattr(osm, "turn_lanes", None)
            if not isinstance(osm, dict)
            else osm.get("turn_lanes")
        )
        if not turn_lanes:
            continue

        # Ensure <userData> element exists
        ud = road.find("userData")
        if ud is None:
            ud = ET.SubElement(road, "userData")

        # Check if turnMarking already present
        already = any(
            v.get("key") == "turnMarking" for v in ud.findall("vector")
        )
        if already:
            continue

        ET.SubElement(ud, "vector", key="turnMarking", value=str(turn_lanes))
        stamped += 1

    return stamped
