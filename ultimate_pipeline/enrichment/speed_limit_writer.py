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


def _existing_speed_kmh(speed_el: ET.Element) -> Optional[float]:
    """Convert an existing <speed max=".." unit=".."/> element to km/h.

    Mirrors realism.py::_infer_speed's unit handling exactly (missing unit
    or explicit "m/s" -- OpenDRIVE's documented default -- times 3.6; "mph"
    via the standard conversion factor; "km/h" as-is) so both readers agree
    on what a given element means.
    """
    raw = speed_el.get("max")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    unit = speed_el.get("unit")
    if unit == "km/h":
        return value
    if unit == "mph":
        return value * 1.60934
    return value * 3.6  # None or "m/s" -- OpenDRIVE's documented default unit


def apply_speed_limits(
    root: ET.Element,
    osm_roads_by_id: Dict[str, Any],
    *,
    correspondence_by_road_id: Dict[str, Any] | None = None,
) -> int:
    """
    Write <speed max="X" unit="km/h"/> under each driving/restricted lane for XODR
    roads that have a matching OSM entry with a known maxspeed.

    Args:
        root:             Parsed XODR root element (modified in-place).
        osm_roads_by_id:  Mapping from street NAME (str, matches build_osm_meta_index's
                          real output -- XODR road id and OSM way id are disjoint
                          numbering schemes, verified 2026-08-26) to an object with a
                          .maxspeed attribute (or dict with 'maxspeed' key). May be empty.

    A spatial HIGH/EXACT association is authoritative for its matched XODR
    road.  It may therefore replace an existing lane speed, including an
    unprovenanced conversion or realism value -- but ONLY when the existing
    value, correctly unit-interpreted, actually disagrees with the OSM one.
    Verified on the pinned map-of-record: comparing by raw attribute string
    (the previous behaviour) treated 123/133 candidates as needing a
    "correction" when they already agreed once units were normalized (the
    base conversion's near-universal <speed max="13.89"/> with no unit
    attribute IS 50 km/h under OpenDRIVE's documented m/s default -- see
    realism.py::_infer_speed, which every existing consumer already relies
    on). Rewriting those would have introduced an explicit unit="km/h" on
    ~92% of touched lanes for zero real-world change, silently mixing two
    unit conventions across the map for a risk with no matching benefit.
    Only the remaining ~8%, where the values genuinely differ (one pinned
    example: 15.7 km/h stored vs. 100 km/h from OSM), are real corrections
    worth the same authoritative overwrite. The legacy street-name mode
    remains insert-only because its correspondence is many-to-many.

    Returns:
        Number of lane speed elements written (inserted or authoritative
        spatial replacements).
    """
    if not osm_roads_by_id and correspondence_by_road_id is None:
        return 0

    written = 0
    spatial_mode = correspondence_by_road_id is not None
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
            speed = lane.find("speed")
            if speed is None:
                ET.SubElement(lane, "speed", max=str(speed_kmh), unit="km/h")
                written += 1
            elif spatial_mode:
                existing_kmh = _existing_speed_kmh(speed)
                if existing_kmh is None or abs(existing_kmh - speed_kmh) >= 0.5:
                    speed.set("max", str(speed_kmh))
                    speed.set("unit", "km/h")
                    written += 1

    return written
