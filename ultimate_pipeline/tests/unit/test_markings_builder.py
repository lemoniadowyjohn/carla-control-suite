# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/lanes/markings_builder.py.

Live: MarkingBuilder applies CARLA-safe road markings. Zero prior test
coverage. Reviewed carefully for the same defect classes found elsewhere
this session -- one dormant gap noted below, deliberately not fixed
(matching the established "flag it, don't chase zero-impact dead code"
precedent from e.g. lanesection_boundary_fixer.py / project_enable_flag_audit).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.lanes.markings_builder import MarkingBuilder


def _road_xml(road_id: str, left_ids=(), right_ids=(), center=True, userdata: str = "") -> str:
    def _lane(lid: int) -> str:
        return f'<lane id="{lid}" type="driving"><width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane>'

    left_xml = "".join(_lane(i) for i in left_ids)
    right_xml = "".join(_lane(i) for i in right_ids)
    center_xml = '<lane id="0" type="driving"/>' if center else ""
    return (
        f'<road id="{road_id}" length="10" junction="-1">{userdata}'
        f'<lanes><laneSection s="0">'
        f"<left>{left_xml}</left>"
        f"<center>{center_xml}</center>"
        f"<right>{right_xml}</right>"
        f"</laneSection></lanes>"
        f"</road>"
    )


def _root(*roads: str) -> ET.Element:
    return ET.fromstring("<OpenDRIVE>" + "".join(roads) + "</OpenDRIVE>")


def test_center_lane_gets_solid_yellow_noPassing_mark():
    root = _root(_road_xml("1"))
    MarkingBuilder.add_basic_markings(root)
    center = root.find(".//lane[@id='0']")
    rm = center.find("roadMark")
    assert rm.attrib["type"] == "solid"
    assert rm.attrib["color"] == "yellow"
    assert rm.attrib["laneChange"] == "none"
    line = rm.find("line")
    assert line is not None
    assert line.attrib["rule"] == "noPassing"


def test_single_right_lane_gets_solid_outer_mark():
    root = _root(_road_xml("1", right_ids=(-1,)))
    MarkingBuilder.add_basic_markings(root)
    lane = root.find(".//lane[@id='-1']")
    rm = lane.find("roadMark")
    assert rm.attrib["type"] == "solid"
    assert rm.attrib["laneChange"] == "none"


def test_multiple_right_lanes_inner_broken_outer_solid():
    root = _root(_road_xml("1", right_ids=(-1, -2, -3)))
    MarkingBuilder.add_basic_markings(root)
    inner1 = root.find(".//lane[@id='-1']/roadMark")
    inner2 = root.find(".//lane[@id='-2']/roadMark")
    outer = root.find(".//lane[@id='-3']/roadMark")
    assert inner1.attrib["type"] == "broken"
    assert inner2.attrib["type"] == "broken"
    assert outer.attrib["type"] == "solid"
    assert inner1.attrib["laneChange"] == "both"
    assert outer.attrib["laneChange"] == "none"


def test_multiple_left_lanes_inner_broken_outer_solid():
    root = _root(_road_xml("1", left_ids=(1, 2, 3)))
    MarkingBuilder.add_basic_markings(root)
    inner = root.find(".//lane[@id='1']/roadMark")
    outer = root.find(".//lane[@id='3']/roadMark")
    assert inner.attrib["type"] == "broken"
    assert outer.attrib["type"] == "solid"


def test_lane_without_width_is_not_marked():
    road = ET.fromstring(
        '<road id="1" length="10" junction="-1"><lanes><laneSection s="0">'
        '<right><lane id="-1" type="driving"/></right>'
        "</laneSection></lanes></road>"
    )
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    root.append(road)
    MarkingBuilder.add_basic_markings(root)
    lane = root.find(".//lane[@id='-1']")
    assert lane.find("roadMark") is None


def test_disallowed_lane_type_is_not_marked():
    road = ET.fromstring(
        '<road id="1" length="10" junction="-1"><lanes><laneSection s="0">'
        '<right><lane id="-1" type="sidewalk">'
        '<width sOffset="0" a="2.0" b="0" c="0" d="0"/>'
        "</lane></right>"
        "</laneSection></lanes></road>"
    )
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    root.append(road)
    MarkingBuilder.add_basic_markings(root)
    lane = root.find(".//lane[@id='-1']")
    assert lane.find("roadMark") is None


def test_road_level_disable_flag_skips_the_whole_road():
    userdata = (
        '<userData><vector name="disable_markings" value="true"/></userData>'
    )
    root = _root(_road_xml("1", right_ids=(-1,), userdata=userdata))
    MarkingBuilder.add_basic_markings(root)
    lane = root.find(".//lane[@id='-1']")
    assert lane.find("roadMark") is None


def test_lane_level_disable_flag_skips_that_lane_only():
    road = ET.fromstring(
        '<road id="1" length="10" junction="-1"><lanes><laneSection s="0">'
        '<right>'
        '<lane id="-1" mark="off" type="driving">'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        "</lane>"
        '<lane id="-2" type="driving">'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        "</lane>"
        "</right>"
        "</laneSection></lanes></road>"
    )
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    root.append(road)
    MarkingBuilder.add_basic_markings(root)
    assert root.find(".//lane[@id='-1']/roadMark") is None
    assert root.find(".//lane[@id='-2']/roadMark") is not None


def test_lane_disable_flag_is_case_sensitive_dormant_gap():
    # Documented, deliberately-not-fixed gap: FALSE_VALUES is
    # {"0","false","False","no","No","off","OFF"} -- not exhaustively
    # case-insensitive (e.g. "FALSE" or "Off" would slip through and the
    # lane would still get marked). Zero current impact: nothing in the
    # live codebase ever sets a mark/marks/markings attribute anywhere
    # (grepped the whole repo) -- this is an unused, speculative disable
    # mechanism, not a live safety gate, so this is intentionally left as
    # a characterization test rather than a fix.
    road = ET.fromstring(
        '<road id="1" length="10" junction="-1"><lanes><laneSection s="0">'
        '<right><lane id="-1" mark="FALSE" type="driving">'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        "</lane></right>"
        "</laneSection></lanes></road>"
    )
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    root.append(road)
    MarkingBuilder.add_basic_markings(root)
    # Current (documented, unexploited) behavior: "FALSE" is NOT
    # recognized as a disable value, so the lane still gets marked.
    assert root.find(".//lane[@id='-1']/roadMark") is not None


def test_existing_roadmarks_are_replaced_not_duplicated():
    road = ET.fromstring(
        '<road id="1" length="10" junction="-1"><lanes><laneSection s="0">'
        '<right><lane id="-1" type="driving">'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        '<roadMark sOffset="0" type="stale" weight="standard" color="blue" width="0.1"/>'
        "</lane></right>"
        "</laneSection></lanes></road>"
    )
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    root.append(road)
    MarkingBuilder.add_basic_markings(root)
    marks = root.findall(".//lane[@id='-1']/roadMark")
    assert len(marks) == 1
    assert marks[0].attrib["color"] == "white"  # stale mark replaced, not duplicated


def test_add_basic_is_a_backward_compat_alias():
    root = _root(_road_xml("1", right_ids=(-1,)))
    MarkingBuilder.add_basic(root)
    assert root.find(".//lane[@id='-1']/roadMark") is not None


def test_fix_road_markings_public_alias_matches_internal():
    root = _root(_road_xml("1", right_ids=(-1,)))
    road = root.find("road")
    MarkingBuilder.fix_road_markings(road)
    assert road.find(".//lane[@id='-1']/roadMark") is not None


def test_summarize_markings_counts_by_color_and_type():
    root = _root(_road_xml("1", right_ids=(-1, -2)))
    MarkingBuilder.add_basic_markings(root)
    summary = MarkingBuilder.summarize_markings(root)
    assert summary["total_marked_lanes"] == 3  # center + 2 right lanes
    assert summary["total_center_marks"] == 1
    assert summary["by_color"]["white"] == 2
    assert summary["by_color"]["yellow"] == 1
    assert summary["by_type"]["broken"] == 1
    assert summary["by_type"]["solid"] == 2


def test_road_with_no_lanes_element_is_skipped_without_crashing():
    road = ET.fromstring('<road id="1" length="10" junction="-1"/>')
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    root.append(road)
    MarkingBuilder.add_basic_markings(root)  # must not raise
