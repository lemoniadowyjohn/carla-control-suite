"""ultimate_pipeline/enrichment/sidewalk_builder.py -- live, correctly wired into
stage_07_lanes.py behind ENABLE_SIDEWALKS (default True, confirmed real 19,390 sidewalk
lanes on the pinned map), but had zero test coverage on this branch. Checked first for
correctness given this session's repeated pattern of enrichment-module bugs hiding behind
an ENABLE flag that reads True -- this one is genuinely wired correctly, no bug found; this
is coverage-gap closure, locking in the real side-selection/ID-assignment/idempotency logic.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.sidewalk_builder import SidewalkBuilder


def _road(rid="1", junction="-1", driving=True, right_ids=(-1,), left_ids=(), name=None):
    road = ET.Element("road", id=rid, junction=junction, length="10.0")
    if name is not None:
        road.set("name", name)
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    left = ET.SubElement(section, "left")
    for lid in left_ids:
        ET.SubElement(left, "lane", id=str(lid), type="driving")
    right = ET.SubElement(section, "right")
    for lid in right_ids:
        ET.SubElement(right, "lane", id=str(lid), type="driving" if driving else "none")
    return road


def _xodr(*roads):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    return root


# ---------------------------------------------------------------------------
# _get_osm_sidewalk_hint
# ---------------------------------------------------------------------------

def test_hint_from_userdata_vector():
    road = _road()
    ud = ET.SubElement(road, "userData")
    ET.SubElement(ud, "vector", key="sidewalk", value="Both")
    assert SidewalkBuilder._get_osm_sidewalk_hint(road) == "both"


def test_hint_from_userdata_vectorobject_variant():
    road = _road()
    ud = ET.SubElement(road, "userData")
    ET.SubElement(ud, "vectorObject", key="sidewalk", value="Left")
    assert SidewalkBuilder._get_osm_sidewalk_hint(road) == "left"


def test_hint_from_road_attribute_osm_prefixed():
    road = _road()
    road.set("osm:sidewalk", "Right")
    assert SidewalkBuilder._get_osm_sidewalk_hint(road) == "right"


def test_hint_from_road_attribute_bare():
    road = _road()
    road.set("sidewalk", "no")
    assert SidewalkBuilder._get_osm_sidewalk_hint(road) == "no"


def test_hint_none_when_absent():
    road = _road()
    assert SidewalkBuilder._get_osm_sidewalk_hint(road) is None


# ---------------------------------------------------------------------------
# add_sidewalks -- side selection
# ---------------------------------------------------------------------------

def test_add_sidewalks_hint_both_adds_left_and_right():
    road = _road()
    ud = ET.SubElement(road, "userData")
    ET.SubElement(ud, "vector", key="sidewalk", value="both")
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root)
    assert added == 2
    section = road.find("lanes/laneSection")
    assert len(section.find("left").findall("lane[@type='sidewalk']")) == 1
    assert len(section.find("right").findall("lane[@type='sidewalk']")) == 1


def test_add_sidewalks_hint_left_only():
    road = _road()
    ud = ET.SubElement(road, "userData")
    ET.SubElement(ud, "vector", key="sidewalk", value="left")
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root)
    assert added == 1
    section = road.find("lanes/laneSection")
    assert len(section.find("left").findall("lane[@type='sidewalk']")) == 1
    assert len(section.find("right").findall("lane[@type='sidewalk']")) == 0


def test_add_sidewalks_no_hint_but_has_driving_lane_defaults_both_sides():
    road = _road(right_ids=(-1,))  # a real driving lane, no OSM hint
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root, default_both_sides=True)
    assert added == 2


def test_add_sidewalks_no_driving_lane_no_hint_adds_nothing():
    road = _road(driving=False)
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root)
    assert added == 0


def test_add_sidewalks_default_both_sides_false_and_no_hint_adds_nothing():
    road = _road(right_ids=(-1,))  # has a driving lane, but heuristic fallback disabled
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root, default_both_sides=False)
    assert added == 0


def test_add_sidewalks_skips_junction_connector_roads():
    road = _road(junction="5", right_ids=(-1,))  # would otherwise qualify
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root)
    assert added == 0


def test_add_sidewalks_no_lanes_element_skipped_safely():
    road = ET.Element("road", id="1", junction="-1", length="10.0")  # no <lanes> at all
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root)
    assert added == 0


# ---------------------------------------------------------------------------
# add_sidewalks -- idempotency and ID assignment
# ---------------------------------------------------------------------------

def test_add_sidewalks_does_not_duplicate_existing_sidewalk():
    road = _road(right_ids=(-1,))
    section = road.find("lanes/laneSection")
    right = section.find("right")
    ET.SubElement(right, "lane", id="-2", type="sidewalk")  # already has one
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root)
    # left gets a new sidewalk (none existed there); right is skipped (already has one)
    assert added == 1
    assert len(right.findall("lane[@type='sidewalk']")) == 1  # still just the pre-existing one


def test_add_sidewalks_left_id_is_max_existing_plus_one():
    road = _road(left_ids=(1, 2, 3), right_ids=(-1,))
    root = _xodr(road)
    SidewalkBuilder.add_sidewalks(root)
    section = road.find("lanes/laneSection")
    sidewalk = section.find("left").find("lane[@type='sidewalk']")
    assert sidewalk.get("id") == "4"


def test_add_sidewalks_right_id_is_min_existing_minus_one():
    road = _road(right_ids=(-1, -2, -3))
    root = _xodr(road)
    SidewalkBuilder.add_sidewalks(root)
    section = road.find("lanes/laneSection")
    sidewalk = section.find("right").find("lane[@type='sidewalk']")
    assert sidewalk.get("id") == "-4"


def test_add_sidewalks_created_lane_has_width_and_roadmark():
    road = _road(right_ids=(-1,))
    root = _xodr(road)
    SidewalkBuilder.add_sidewalks(root)
    section = road.find("lanes/laneSection")
    sidewalk = section.find("right").find("lane[@type='sidewalk']")
    assert sidewalk.find("width") is not None
    assert sidewalk.find("roadMark") is not None


# ---------------------------------------------------------------------------
# _get_osm_highway / add_sidewalks -- road-classification filter (round 5,
# WS-A: the blanket "has driving lane -> add sidewalks" fallback fired for
# ANY road, including motorway/trunk classes with no real sidewalk
# expectation; confirmed nothing in the pipeline ever wrote the more-precise
# <userData> sidewalk hint this module already read for, so every eligible
# road fell through to the blanket fallback 100% of the time on real regens)
# ---------------------------------------------------------------------------

def test_get_osm_highway_matches_by_street_name():
    road = _road(name="Bundesautobahn 9")
    osm_meta = {"Bundesautobahn 9": {"highway": "motorway"}}
    assert SidewalkBuilder._get_osm_highway(road, osm_meta) == "motorway"


def test_get_osm_highway_none_when_osm_meta_absent():
    road = _road(name="Bundesautobahn 9")
    assert SidewalkBuilder._get_osm_highway(road, None) is None


def test_get_osm_highway_none_when_road_name_missing():
    road = _road(name=None)
    osm_meta = {"Bundesautobahn 9": {"highway": "motorway"}}
    assert SidewalkBuilder._get_osm_highway(road, osm_meta) is None


def test_get_osm_highway_none_when_street_not_in_index():
    road = _road(name="Some Unindexed Street")
    osm_meta = {"Bundesautobahn 9": {"highway": "motorway"}}
    assert SidewalkBuilder._get_osm_highway(road, osm_meta) is None


def test_add_sidewalks_skips_motorway_class_road_via_osm_meta():
    road = _road(name="Bundesautobahn 9", right_ids=(-1,))  # has a driving lane, no OSM hint
    osm_meta = {"Bundesautobahn 9": {"highway": "motorway"}}
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root, osm_meta=osm_meta)
    assert added == 0
    section = road.find("lanes/laneSection")
    assert len(section.find("right").findall("lane[@type='sidewalk']")) == 0


def test_add_sidewalks_skips_trunk_link_class_road_via_osm_meta():
    road = _road(name="Ramp X", right_ids=(-1,))
    osm_meta = {"Ramp X": {"highway": "trunk_link"}}
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root, osm_meta=osm_meta)
    assert added == 0


def test_add_sidewalks_residential_class_road_unaffected_by_osm_meta():
    road = _road(name="Hauptstrasse", right_ids=(-1,))
    osm_meta = {"Hauptstrasse": {"highway": "residential"}}
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root, osm_meta=osm_meta)
    assert added == 2


def test_add_sidewalks_explicit_hint_wins_over_motorway_classification():
    road = _road(name="Bundesautobahn 9", right_ids=(-1,))
    ud = ET.SubElement(road, "userData")
    ET.SubElement(ud, "vector", key="sidewalk", value="both")
    osm_meta = {"Bundesautobahn 9": {"highway": "motorway"}}
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root, osm_meta=osm_meta)
    assert added == 2  # explicit OSM hint takes priority over the classification filter


def test_add_sidewalks_no_osm_meta_preserves_prior_blanket_behavior():
    """Regression guard: osm_meta defaults to None, must reproduce exactly
    today's behavior (every road with a driving lane gets sidewalks)."""
    road = _road(name="Bundesautobahn 9", right_ids=(-1,))
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root)
    assert added == 2


def test_add_sidewalks_road_unmatched_in_osm_meta_falls_back_to_blanket_heuristic():
    road = _road(name="Some Unindexed Street", right_ids=(-1,))
    osm_meta = {"Bundesautobahn 9": {"highway": "motorway"}}  # doesn't contain this road
    root = _xodr(road)
    added = SidewalkBuilder.add_sidewalks(root, osm_meta=osm_meta)
    assert added == 2  # unknown classification -> fall back to blanket heuristic, not skip


# ---------------------------------------------------------------------------
# count_sidewalk_lanes
# ---------------------------------------------------------------------------

def test_count_sidewalk_lanes():
    road = _road(right_ids=(-1,))
    root = _xodr(road)
    assert SidewalkBuilder.count_sidewalk_lanes(root) == 0
    SidewalkBuilder.add_sidewalks(root)
    assert SidewalkBuilder.count_sidewalk_lanes(root) == 2
