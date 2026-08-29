# -*- coding: utf-8 -*-
"""Tests for LaneGenerator (ultimate_pipeline/enrichment/lane_generator.py).

Live: called by pipeline_stages/stage_07_lanes.py as a fallback/repair pass
for roads that came out of SUMO/OSM2ODR with no driving lanes at all. Its own
docstring calls it "the ONLY LaneGenerator the pipeline must use" -- zero
prior test coverage despite that emphasis.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.lane_generator import LaneGenerator


def _road(rid="1", junction="-1"):
    return ET.Element("road", id=rid, junction=junction, length="10")


def _root(roads):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    return root


def _driving_lane_ids(road, side):
    lanes = road.find("lanes")
    section = lanes.find("laneSection")
    side_elem = section.find(side)
    if side_elem is None:
        return []
    return [
        lane.get("id") for lane in side_elem.findall("lane")
        if lane.get("type") == "driving"
    ]


def test_skips_road_that_already_has_driving_lanes():
    road = _road()
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0.0")
    left = ET.SubElement(section, "left")
    lane = ET.SubElement(left, "lane", id="1", type="driving")
    ET.SubElement(lane, "width", sOffset="0", a="3.5")

    root = _root([road])
    created = LaneGenerator.ensure_lanes(root, verbose=False)
    assert created == 0
    # untouched: still exactly one laneSection, one lane
    assert len(road.find("lanes").findall("laneSection")) == 1


def test_normal_road_gets_bidirectional_driving_lanes():
    road = _road(junction="-1")
    root = _root([road])
    created = LaneGenerator.ensure_lanes(root, verbose=False)
    assert created == 1
    assert _driving_lane_ids(road, "left") == ["1"]
    assert _driving_lane_ids(road, "right") == ["-1"]
    center = road.find("lanes/laneSection/center/lane")
    assert center.get("type") == "none"


def test_connector_road_gets_single_direction_driving_lane():
    road = _road(junction="5")
    root = _root([road])
    created = LaneGenerator.ensure_lanes(root, verbose=False)
    assert created == 1
    assert _driving_lane_ids(road, "left") == []
    assert _driving_lane_ids(road, "right") == ["-1"]


def test_empty_lane_sections_are_pruned_before_regeneration():
    road = _road()
    lanes = ET.SubElement(road, "lanes")
    # A laneSection with no lanes at all (degenerate/orphaned).
    ET.SubElement(lanes, "laneSection", s="0.0")

    root = _root([road])
    created = LaneGenerator.ensure_lanes(root, verbose=False)
    assert created == 1
    sections = road.find("lanes").findall("laneSection")
    assert len(sections) == 1
    assert _driving_lane_ids(road, "left") == ["1"]


def test_nonempty_nondriving_section_at_other_s_is_preserved_alongside_new_section():
    # A road with no driving lanes anywhere, but a legitimate non-empty
    # laneSection (e.g. sidewalk-only) further down the road, should not
    # have that section silently deleted -- only 0-lane sections are pruned.
    road = _road()
    lanes = ET.SubElement(road, "lanes")
    far_section = ET.SubElement(lanes, "laneSection", s="5.0")
    far_left = ET.SubElement(far_section, "left")
    sidewalk = ET.SubElement(far_left, "lane", id="1", type="sidewalk")
    ET.SubElement(sidewalk, "width", sOffset="0", a="1.5")

    root = _root([road])
    created = LaneGenerator.ensure_lanes(root, verbose=False)
    assert created == 1
    sections = road.find("lanes").findall("laneSection")
    # Both the original s=5.0 sidewalk section and the new s=0.0 driving
    # section now coexist -- documenting current behavior.
    section_s_values = sorted(float(s.get("s")) for s in sections)
    assert section_s_values == [0.0, 5.0]
