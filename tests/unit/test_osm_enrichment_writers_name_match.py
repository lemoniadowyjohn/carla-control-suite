"""The 3 OSM enrichment writers (speed_limit, turn_lanes, regulatory_sign) looked up
osm_roads_by_id.get(road.get("id", "")) -- but build_osm_meta_index is now keyed by
street name, not way id (see test_osm_meta_index_name_matching.py). Writers must key
their road-side lookup the same way: by road.get("name", "").strip().
"""
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.speed_limit_writer import apply_speed_limits
from ultimate_pipeline.enrichment.turn_lanes_writer import apply_turn_lanes
from ultimate_pipeline.enrichment.regulatory_sign_writer import apply_regulatory_signs


def _road_with_name(name: str, road_id: str = "42330") -> ET.Element:
    road = ET.Element("road", name=name, length="10.0", id=road_id, junction="-1")
    lanes = ET.SubElement(road, "lanes")
    ls = ET.SubElement(lanes, "laneSection", s="0")
    center = ET.SubElement(ls, "center")
    ET.SubElement(center, "lane", id="0", type="none")
    right = ET.SubElement(ls, "right")
    ET.SubElement(right, "lane", id="-1", type="driving")
    return road


def _root_with_one_named_road(name: str) -> ET.Element:
    root = ET.Element("OpenDRIVE")
    root.append(_road_with_name(name))
    return root


def test_speed_limits_matched_by_road_name_not_id():
    root = _root_with_one_named_road("Bahnhofstrasse")
    # keyed by NAME (matches build_osm_meta_index's real output shape), id would never match
    osm_meta = {"Bahnhofstrasse": {"maxspeed": "50"}}
    n = apply_speed_limits(root, osm_meta)
    assert n == 1, "expected the name-keyed entry to match the road by its name attribute"


def test_turn_lanes_matched_by_road_name_not_id():
    root = _root_with_one_named_road("Bahnhofstrasse")
    osm_meta = {"Bahnhofstrasse": {"turn_lanes": "left|through"}}
    n = apply_turn_lanes(root, osm_meta)
    assert n == 1


def test_regulatory_signs_matched_by_road_name_not_id():
    root = _root_with_one_named_road("Bahnhofstrasse")
    osm_meta = {"Bahnhofstrasse": {"traffic_sign": "DE:274-50"}}
    n = apply_regulatory_signs(root, osm_meta)
    assert n == 1


def test_speed_limits_no_match_for_unnamed_road():
    root = _root_with_one_named_road("")  # no name -- cannot be matched
    osm_meta = {"Bahnhofstrasse": {"maxspeed": "50"}}
    n = apply_speed_limits(root, osm_meta)
    assert n == 0
