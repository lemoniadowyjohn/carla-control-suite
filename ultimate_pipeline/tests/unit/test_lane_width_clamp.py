# -*- coding: utf-8 -*-
"""Tests for LaneWidthClamp (ultimate_pipeline/geometry/lane_width_clamp.py).

Live: called by pipeline_stages/stage_07_lanes.py as the "CARLA safe" lane
width safety clamp (MIN_WIDTH=0.25, MAX_WIDTH=8.0). Zero prior test coverage.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.geometry.lane_width_clamp import LaneWidthClamp


def _road_with_width(a: str):
    road = ET.Element("road", id="1", length="10")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    left = ET.SubElement(section, "left")
    lane = ET.SubElement(left, "lane", id="1", type="driving")
    width = ET.SubElement(lane, "width", sOffset="0", a=a, b="0", c="0", d="0")
    return road, width


def test_clamp_finds_widths_nested_under_real_opendrive_lane_structure():
    # The real OpenDRIVE nesting is lanes/laneSection/{left,center,right}/lane/width
    # -- clamp() must actually reach widths at that depth, not just widths
    # that happen to be a direct child of <lanes>.
    road, width = _road_with_width("999.0")
    root = ET.Element("OpenDRIVE")
    root.append(road)
    LaneWidthClamp.clamp(root)
    assert float(width.get("a")) == LaneWidthClamp.MAX_WIDTH


def test_clamp_raises_too_narrow_width_to_minimum():
    road, width = _road_with_width("0.01")
    root = ET.Element("OpenDRIVE")
    root.append(road)
    LaneWidthClamp.clamp(root)
    assert float(width.get("a")) == LaneWidthClamp.MIN_WIDTH


def test_clamp_leaves_in_range_width_untouched():
    road, width = _road_with_width("3.5")
    root = ET.Element("OpenDRIVE")
    root.append(road)
    LaneWidthClamp.clamp(root)
    assert width.get("a") == "3.5"


def test_clamp_applies_across_left_center_right_sides():
    road = ET.Element("road", id="1", length="10")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    widths = {}
    for side_name, extreme in (("left", "999.0"), ("center", "0.01"), ("right", "999.0")):
        side = ET.SubElement(section, side_name)
        lane = ET.SubElement(side, "lane", id="1" if side_name != "center" else "0", type="driving")
        widths[side_name] = ET.SubElement(lane, "width", sOffset="0", a=extreme)
    root = ET.Element("OpenDRIVE")
    root.append(road)
    LaneWidthClamp.clamp(root)
    assert float(widths["left"].get("a")) == LaneWidthClamp.MAX_WIDTH
    assert float(widths["center"].get("a")) == LaneWidthClamp.MIN_WIDTH
    assert float(widths["right"].get("a")) == LaneWidthClamp.MAX_WIDTH
