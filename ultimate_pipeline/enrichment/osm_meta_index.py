# ultimate_pipeline/enrichment/osm_meta_index.py
"""
Build a lightweight OSM street-name → metadata dict from a raw .osm XML file.

Extracts only the tags needed by Tier-2 enrichment writers:
  - maxspeed     → speed_limit_writer
  - turn:lanes   → turn_lanes_writer
  - traffic_sign → regulatory_sign_writer
  - highway/lanes/width -> lane_width_policy

Returns:
    Dict[str, dict]  keyed by street name (OSM way `name` tag, exact string match).

CORRECTED (2026-08-26): the original design keyed by OSM way id under the assumption
"XODR road id == OSM way id". Verified FALSE against the real pinned pair: XODR road
ids are Osm2Odr/netconvert-assigned sequence numbers (e.g. "42330"), OSM way ids are
the original OSM entity ids (e.g. "4058127") -- disjoint numbering schemes, 0.0000%
direct-id match rate on 32,297 real roads. The feature silently inserted nothing on
every real regen (fails open, not closed -- no error was ever raised).

Matching by street NAME instead is verified viable (90.3% of distinct enrichment-
tagged OSM way names match a real XODR road name on the pinned pair) but is a
many-to-many correspondence at the STREET level: one street is commonly both several
OSM ways (this module merges their tags) *and* several XODR road segments after
netconvert splits it at intersections (all matching segments receive the same entry).
This is semantically fine for a street-level attribute like maxspeed, but an HONEST
CAVEAT for position-specific tags (turn:lanes, traffic_sign): a value that originally
described only one specific way/intersection-approach may now be applied to every
XODR segment sharing that street name. Not silently hidden -- callers writing those
two tags should treat matches as approximate, not exact.

Failure modes:
  - If the OSM file does not exist or is not valid XML: returns empty dict (safe).
  - A way with enrichment tags but no `name` tag cannot be matched by name and is
    correctly excluded (not indexed under an empty-string key).
  - Large files (>100 MB) are handled via iterparse to avoid OOM.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict

_TAGS_OF_INTEREST = {
    "name",
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
    Parse *osm_path* and return a dict mapping street name → metadata dict.

    Each metadata dict contains only the keys that were present in the OSM file(s)
    contributing to that street name:
      {
        "maxspeed":    str,
        "turn_lanes":  str,   # consolidated from turn:lanes or turn_lanes
        "traffic_sign": str,
        "highway": str,
        "lanes": str,
        "width": str,
      }
    When multiple OSM ways share the same street name, their tags are MERGED
    (first-seen value wins per key on conflict) rather than the later way
    silently discarding the earlier one's data.

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
                name = current_tags.get("name", "").strip()
                if name and current_tags and _has_enrichment_interest(current_tags):
                    entry: dict = {}
                    for key in sorted(current_tags):
                        if key in ("name", "turn:lanes", "turn_lanes"):
                            continue
                        entry[key] = current_tags[key]
                    # Normalise turn:lanes → turn_lanes
                    tl = current_tags.get("turn:lanes") or current_tags.get("turn_lanes")
                    if tl:
                        entry["turn_lanes"] = tl
                    if entry:
                        existing = result.setdefault(name, {})
                        for key, value in entry.items():
                            existing.setdefault(key, value)  # first-seen wins on conflict
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
