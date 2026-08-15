# ultimate_pipeline/enrichment/osm_meta_index.py
"""
Build a lightweight OSM way-id → metadata dict from a raw .osm XML file.

Extracts only the tags needed by Tier-2 enrichment writers:
  - maxspeed     → speed_limit_writer
  - turn:lanes   → turn_lanes_writer
  - traffic_sign → regulatory_sign_writer
  - highway/lanes/width -> lane_width_policy

Returns:
    Dict[str, dict]  keyed by OSM way id (as string), e.g. "7765".

The XODR road id produced by osm2xodr / netconvert equals the OSM way id, so
this dict can be passed directly as osm_roads_by_id to any of the three writers.

Failure modes:
  - If the OSM file does not exist or is not valid XML: returns empty dict (safe).
  - Ways without any of the three tags are omitted from the result.
  - Large files (>100 MB) are handled via iterparse to avoid OOM.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict

_TAGS_OF_INTEREST = {
    "maxspeed",
    "maxspeed:type",
    "turn:lanes",
    "turn_lanes",
    "traffic_sign",
    "highway",
    "lanes",
    "lanes:forward",
    "lanes:backward",
    "width",
    "est_width",
}

_LANE_WIDTH_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
    "track",
}


def _has_enrichment_interest(tags: dict) -> bool:
    if any(k in tags for k in ("maxspeed", "maxspeed:type", "turn:lanes", "turn_lanes", "traffic_sign")):
        return True
    if any(k in tags for k in ("lanes", "lanes:forward", "lanes:backward", "width", "est_width")):
        return True
    return str(tags.get("highway", "")).strip().lower() in _LANE_WIDTH_HIGHWAYS


def build_osm_meta_index(osm_path: str) -> Dict[str, dict]:
    """
    Parse *osm_path* and return a dict mapping OSM way id → metadata dict.

    Each metadata dict contains only the keys that were present in the OSM file:
      {
        "maxspeed":    str | None,
        "turn_lanes":  str | None,   # consolidated from turn:lanes or turn_lanes
        "traffic_sign": str | None,
        "highway": str | None,
        "lanes": str | None,
        "width": str | None,
      }

    Returns an empty dict on any error (safe — callers handle missing entries).
    """
    result: Dict[str, dict] = {}

    try:
        context = ET.iterparse(osm_path, events=("start", "end"))
        current_way_id: str | None = None
        current_tags: dict = {}

        for event, elem in context:
            if event == "start" and elem.tag == "way":
                current_way_id = elem.get("id")
                current_tags = {}

            elif event == "start" and elem.tag == "tag" and current_way_id is not None:
                k = elem.get("k", "")
                v = elem.get("v", "")
                if k in _TAGS_OF_INTEREST:
                    current_tags[k] = v

            elif event == "end" and elem.tag == "way" and current_way_id is not None:
                if current_tags and _has_enrichment_interest(current_tags):
                    entry: dict = {}
                    for key in sorted(current_tags):
                        if key in ("turn:lanes", "turn_lanes"):
                            continue
                        entry[key] = current_tags[key]
                    # Normalise turn:lanes → turn_lanes
                    tl = current_tags.get("turn:lanes") or current_tags.get("turn_lanes")
                    if tl:
                        entry["turn_lanes"] = tl
                    if entry:
                        result[current_way_id] = entry
                current_way_id = None
                current_tags = {}
                elem.clear()  # free memory

    except FileNotFoundError:
        pass  # OSM file not present — writers will silently no-op
    except ET.ParseError as exc:
        print(f"[osm_meta_index] ⚠ XML parse error in {osm_path!r}: {exc}")
    except Exception as exc:
        print(f"[osm_meta_index] ⚠ Unexpected error building index: {exc}")

    return result
