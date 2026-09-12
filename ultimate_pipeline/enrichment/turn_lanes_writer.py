# ultimate_pipeline/enrichment/turn_lanes_writer.py
"""
Write OSM turn:lanes values as XODR userData hints.

For each XODR road that has a matching OSM entry with a turn_lanes field,
this module inserts:
    <userData>
        <vector key="turnMarking" value="left|straight|right"/>
    </userData>

Geometry is not modified here.  LaneGenerator only creates approach lanes from
direct XODR OSM provenance or an explicit road-ID correspondence result; this
name-indexed writer remains hint-only for position-specific tags.

Threading note:
    Like speed_limit_writer, this requires osm_roads_by_id to be available.
    In the current pipeline, this mapping must be built externally (e.g. by
    parsing the OSM file and matching xodr road ids to osm way ids).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, Any


def _metadata_value(osm: Any, key: str) -> Any:
    if isinstance(osm, dict):
        return osm.get(key)
    return getattr(osm, key.replace(":", "_"), None)


def _set_vector(user_data: ET.Element, key: str, value: str) -> bool:
    """Set a direct userData vector and return whether it changed."""
    for vector in user_data.findall("vector"):
        if vector.get("key") == key:
            if vector.get("value") == value:
                return False
            vector.set("value", value)
            return True
    ET.SubElement(user_data, "vector", key=key, value=value)
    return True


def apply_turn_lanes(
    root: ET.Element,
    osm_roads_by_id: Dict[str, Any],
    *,
    correspondence_by_road_id: Dict[str, Any] | None = None,
) -> int:
    """
    Stamp <userData><vector key="turnMarking" value="..."/></userData> onto XODR roads
    that have a known OSM turn:lanes value.

    Args:
        root:             Parsed XODR root element (modified in-place).
        osm_roads_by_id:  Mapping from street NAME (str, matches build_osm_meta_index's
                          real output -- XODR road id and OSM way id are disjoint
                          numbering schemes, verified 2026-08-26) to an OSMRoad (or
                          dict with 'turn_lanes' key). May be empty.

    CAVEAT: turn:lanes is position-specific in OSM (one intersection approach), but
    matching is by street name -- a value may be applied to every XODR road segment
    sharing that name, not just the one it originally described. See
    osm_meta_index.py's module docstring.

    Returns:
        Number of roads stamped with turnMarking userData.
    """
    if not osm_roads_by_id:
        return 0

    stamped = 0
    for road in root.findall("road"):
        if correspondence_by_road_id is not None:
            association = correspondence_by_road_id.get(str(road.get("id", "")))
            if not association or str(association.get("class", "")) not in {"EXACT", "HIGH"}:
                continue
            osm = association.get("metadata", {})
        else:
            road_name = road.get("name", "").strip()
            if not road_name:
                continue
            osm = osm_roads_by_id.get(road_name)
        if osm is None:
            continue

        forward = _metadata_value(osm, "turn:lanes:forward")
        backward = _metadata_value(osm, "turn:lanes:backward")
        combined = _metadata_value(osm, "turn_lanes") or _metadata_value(
            osm, "turn:lanes"
        )
        if not forward and not backward and not combined:
            continue

        # Ensure <userData> element exists
        ud = road.find("userData")
        if ud is None:
            ud = ET.SubElement(road, "userData")

        # Directional tags are authoritative.  The historical generic hint is
        # retained for consumers that do not understand directional vectors.
        changed = False
        if forward or backward:
            if forward:
                changed = _set_vector(
                    ud, "turnMarking:forward", str(forward)
                ) or changed
            if backward:
                changed = _set_vector(
                    ud, "turnMarking:backward", str(backward)
                ) or changed
            changed = _set_vector(
                ud, "turnMarking", str(forward or backward)
            ) or changed
        else:
            changed = _set_vector(ud, "turnMarking", str(combined))

        if changed:
            stamped += 1

    return stamped
