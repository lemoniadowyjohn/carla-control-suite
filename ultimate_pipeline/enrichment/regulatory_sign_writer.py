# ultimate_pipeline/enrichment/regulatory_sign_writer.py
"""
Emit XODR <object> elements for German regulatory traffic signs sourced from OSM tags.

Only emits where the OSM tag is confirmed present — does NOT infer from road type.
Objects are written as <object> (not <signal>) at s=0.0, t=-1.5 (roadside, right).

Threading note:
    Requires an osm_roads_by_id dict where each entry carries a `traffic_sign`
    attribute or dict key (e.g. "de:206", "de:274-50").  This is not yet populated
    in the main pipeline's OSM loading path — add it when OSM feature tagging is
    extended.  The module is safe to import and call with an empty dict.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional, Tuple

# ---------------------------------------------------------------------------
# Lookup table: OSM traffic_sign value → (xodr_type, xodr_subtype)
# Based on German StVO sign catalog.
# ---------------------------------------------------------------------------
SIGN_TABLE: Dict[str, Tuple[str, str]] = {
    "de:206": ("stop", "regulatory"),
    "de:205": ("giveway", "regulatory"),
    "de:274-10": ("speedLimit10", "maxspeed"),
    "de:274-20": ("speedLimit20", "maxspeed"),
    "de:274-30": ("speedLimit30", "maxspeed"),
    "de:274-40": ("speedLimit40", "maxspeed"),
    "de:274-50": ("speedLimit50", "maxspeed"),
    "de:274-60": ("speedLimit60", "maxspeed"),
    "de:274-70": ("speedLimit70", "maxspeed"),
    "de:274-80": ("speedLimit80", "maxspeed"),
    "de:274-100": ("speedLimit100", "maxspeed"),
    "de:274-120": ("speedLimit120", "maxspeed"),
    "de:282": ("speedLimitEnd", "maxspeed"),
    "de:301": ("rightOfWay", "regulatory"),
    "de:306": ("priorityRoad", "regulatory"),
    "de:314": ("parkingAllowed", "parking"),
    "de:315": ("parkingRight", "parking"),
}


def apply_regulatory_signs(root: ET.Element, osm_roads_by_id: Dict[str, Any]) -> int:
    """
    Insert XODR <object> elements for regulatory signs.

    Args:
        root:             Parsed XODR root element (modified in-place).
        osm_roads_by_id:  Mapping from XODR road id (str) → object/dict with
                          'traffic_sign' attribute/key (string value, e.g. "de:206").

    Returns:
        Number of <object> elements inserted.
    """
    if not osm_roads_by_id:
        return 0

    inserted = 0
    obj_counter: Dict[str, int] = {}

    for road in root.findall("road"):
        road_id = road.get("id", "")
        osm = osm_roads_by_id.get(road_id)
        if osm is None:
            continue

        raw_sign = (
            getattr(osm, "traffic_sign", None)
            if not isinstance(osm, dict)
            else osm.get("traffic_sign")
        )
        if not raw_sign:
            continue

        sign_key = str(raw_sign).strip().lower()
        entry = SIGN_TABLE.get(sign_key)
        if entry is None:
            continue  # unknown sign — do not infer

        xodr_type, xodr_subtype = entry
        kind = xodr_type
        obj_counter[kind] = obj_counter.get(kind, 0) + 1
        obj_id = f"{kind}_{obj_counter[kind]}"

        objects_elem = road.find("objects")
        if objects_elem is None:
            objects_elem = ET.SubElement(road, "objects")

        ET.SubElement(objects_elem, "object", {
            "id": obj_id,
            "type": xodr_type,
            "subtype": xodr_subtype,
            "name": sign_key,
            "s": "0.0",
            "t": "-1.5",
            "zOffset": "0.0",
            "hdg": "0.0",
            "pitch": "0.0",
            "roll": "0.0",
            "orientation": "+",
            "dynamic": "no",
            "height": "2.2",
            "length": "0.1",
            "width": "0.6",
        })
        inserted += 1

    return inserted
