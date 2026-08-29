# -*- coding: utf-8 -*-
"""Tests for CrossSectionRepair (ultimate_pipeline/geometry/crosssection_repair.py).

Live geometry-repair module: snaps a lane's width forward to match the
previous laneSection's width for the same lane id when the jump exceeds
max_gap. Zero prior test coverage.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.geometry.crosssection_repair import CrossSectionRepair


def _road_with_two_sections(width_a: str, width_b: str, *, lane_id="1", side="left"):
    road = ET.Element("road", id="1", length="20")
    lanes = ET.SubElement(road, "lanes")
    sec_a = ET.SubElement(lanes, "laneSection", s="0")
    side_a = ET.SubElement(sec_a, side)
    lane_a = ET.SubElement(side_a, "lane", id=lane_id, type="driving")
    w_a = ET.SubElement(lane_a, "width", sOffset="0", a=width_a)

    sec_b = ET.SubElement(lanes, "laneSection", s="10")
    side_b = ET.SubElement(sec_b, side)
    lane_b = ET.SubElement(side_b, "lane", id=lane_id, type="driving")
    w_b = ET.SubElement(lane_b, "width", sOffset="0", a=width_b)

    return road, w_a, w_b


def _root(road):
    root = ET.Element("OpenDRIVE")
    root.append(road)
    return root


def test_large_width_jump_snapped_to_previous_section():
    road, w_a, w_b = _road_with_two_sections("3.5", "1.0")
    CrossSectionRepair.enforce(_root(road), max_gap=0.3)
    assert float(w_a.get("a")) == 3.5  # source untouched
    assert float(w_b.get("a")) == 3.5  # snapped to match


def test_small_width_jump_within_tolerance_untouched():
    road, w_a, w_b = _road_with_two_sections("3.5", "3.6")
    CrossSectionRepair.enforce(_root(road), max_gap=0.3)
    assert float(w_b.get("a")) == 3.6


def test_only_one_lanesection_is_a_noop():
    road = ET.Element("road", id="1", length="10")
    lanes = ET.SubElement(road, "lanes")
    sec = ET.SubElement(lanes, "laneSection", s="0")
    left = ET.SubElement(sec, "left")
    lane = ET.SubElement(left, "lane", id="1", type="driving")
    w = ET.SubElement(lane, "width", sOffset="0", a="3.5")
    CrossSectionRepair.enforce(_root(road))
    assert w.get("a") == "3.5"


def test_mismatched_lane_ids_across_sections_are_not_touched():
    road, w_a, w_b = _road_with_two_sections("3.5", "1.0", lane_id="1")
    # Change the second section's lane id so it no longer matches lane 1.
    lanes = road.find("lanes")
    second_section_lane = lanes.findall("laneSection")[1].find("left/lane")
    second_section_lane.set("id", "2")
    CrossSectionRepair.enforce(_root(road), max_gap=0.3)
    assert w_b.get("a") == "1.0"  # no matching lane id -- left alone


def test_zero_width_lane_is_not_used_as_repair_source_or_target():
    road, w_a, w_b = _road_with_two_sections("0.0", "3.5")
    CrossSectionRepair.enforce(_root(road), max_gap=0.3)
    # wa == 0 fails the `wa > 0` guard, so no repair is attempted.
    assert w_b.get("a") == "3.5"
