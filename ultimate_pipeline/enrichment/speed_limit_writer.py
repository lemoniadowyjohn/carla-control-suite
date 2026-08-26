# ultimate_pipeline/enrichment/speed_limit_writer.py
"""
Write <speed max="X" unit="km/h"/> under driving/restricted lanes from OSM maxspeed data.

Threading note:
    OSMRoad objects (from domain_gap/osm_loader.py) are only available in domain-gap
    analysis, not automatically in the main pipeline enrichment stage.  This module is
    designed to be called from:
      (a) stage_04_enrichment.py — if an osm_roads_by_xodr_id dict is threaded through
      (b) any post-processing script that has loaded both the XODR and an OSM JSON export

Failure mode:
    If osm_roads_by_id is empty or a road has no matching OSM entry, the road is
    silently skipped (heuristic speed signs from RealismModule still apply).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, Optional, Any


# ---------------------------------------------------------------------------
# German road-type zone defaults (RASt 06 / StVO)
# ---------------------------------------------------------------------------
_ZONE_TABLE: Dict[str, int] = {
    "de:urban": 50,
    "de:rural": 100,
    "de:motorway": 130,
    "de:living_street": 7,
    "de:pedestrian": 10,
    "de:zone30": 30,
    "de:zone20": 20,
    "walk": 7,
    "none": 0,       # explicit no-limit — omit element
}

# Pattern: optional leading/trailing whitespace, digits, optional mph suffix
_NUMERIC_RE = re.compile(r"^\s*(\d+)\s*(mph)?\s*$", re.IGNORECASE)


def parse_maxspeed(raw: Any) -> Optional[int]:
    """Convert an OSM maxspeed value to km/h (integer).

    Handles:
      "50"          → 50
      "50 mph"      → 80
      "de:urban"    → 50
      "DE:motorway" → 130
      None          → None
      unparseable   → None
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None

    zone = _ZONE_TABLE.get(s)
    if zone is not None:
        return zone if zone > 0 else None

    m = _NUMERIC_RE.match(s)
    if m:
        v = int(m.group(1))
        if m.group(2):  # mph
            v = round(v * 1.60934)
        return v

    return None


def apply_speed_limits(root: ET.Element, osm_roads_by_id: Dict[str, Any]) -> int:
    """
    Write <speed max="X" unit="km/h"/> under each driving/restricted lane for XODR
    roads that have a matching OSM entry with a known maxspeed.

    Args:
        root:             Parsed XODR root element (modified in-place).
        osm_roads_by_id:  Mapping from street NAME (str, matches build_osm_meta_index's
                          real output -- XODR road id and OSM way id are disjoint
                          numbering schemes, verified 2026-08-26) to an object with a
                          .maxspeed attribute (or dict with 'maxspeed' key). May be empty.

    Returns:
        Number of <speed> elements inserted.
    """
    if not osm_roads_by_id:
        return 0

    inserted = 0
    for road in root.findall("road"):
        road_name = road.get("name", "").strip()
        if not road_name:
            continue
        osm = osm_roads_by_id.get(road_name)
        if osm is None:
            continue

        # Support both object attribute and dict key
        raw_speed = (
            getattr(osm, "maxspeed", None)
            if not isinstance(osm, dict)
            else osm.get("maxspeed")
        )
        speed_kmh = parse_maxspeed(raw_speed)
        if speed_kmh is None:
            continue

        for lane in road.findall(".//lane"):
            if lane.get("type") not in ("driving", "restricted"):
                continue
            if lane.find("speed") is None:
                ET.SubElement(lane, "speed", max=str(speed_kmh), unit="km/h")
                inserted += 1

    return inserted
