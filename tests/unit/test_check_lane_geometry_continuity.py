"""ultimate_pipeline/quality/check_lane_geometry_continuity.py -- detects laneOffset and lane
width discontinuities at laneSection boundaries. Found completely untested while investigating
a divergence between this file and its submission/infrastructure/ mirror: the mirror was
missing a real, documented false-positive fix (dated 2026-08-17, "DEEP_QUALITY_SWEEP", road
46620) that skips width comparison across a lane-TYPE transition (e.g. sidewalk<->driving),
since the lane's identity changes there and comparing incompatible types is meaningless. Synced
the mirror to match and writing regression coverage for the fix here, since none existed
despite it already being live on main for over a week.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.quality.check_lane_geometry_continuity import (
    _eval_poly,
    _lane_offset_at,
    _lane_width_at,
    check_lane_geometry_continuity,
)


def _lane(lane_id, lane_type, width_a):
    lane = ET.Element("lane", id=str(lane_id), type=lane_type)
    ET.SubElement(lane, "width", sOffset="0.0", a=str(width_a), b="0.0", c="0.0", d="0.0")
    return lane


def _road_with_two_sections(rid, s_boundary, prev_lanes, next_lanes, length=20.0):
    road = ET.Element("road", id=rid, length=str(length), junction="-1")
    lanes_el = ET.SubElement(road, "lanes")
    sec1 = ET.SubElement(lanes_el, "laneSection", s="0.0")
    right1 = ET.SubElement(sec1, "right")
    for lane in prev_lanes:
        right1.append(lane)
    sec2 = ET.SubElement(lanes_el, "laneSection", s=str(s_boundary))
    right2 = ET.SubElement(sec2, "right")
    for lane in next_lanes:
        right2.append(lane)
    return road


def _write_xodr(path: Path, *roads) -> None:
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# _eval_poly / _lane_offset_at / _lane_width_at
# ---------------------------------------------------------------------------

def test_eval_poly_constant_term_only():
    assert _eval_poly(3.5, 0.0, 0.0, 0.0, 10.0) == 3.5


def test_eval_poly_cubic_terms():
    assert _eval_poly(1.0, 2.0, 3.0, 4.0, 2.0) == 1.0 + 2 * 2 + 3 * 4 + 4 * 8


def test_lane_offset_at_no_offset_elements_defaults_zero():
    road = ET.Element("road")
    ET.SubElement(road, "lanes")
    assert _lane_offset_at(road, 5.0) == 0.0


def test_lane_width_at_no_widths_returns_none():
    lane = ET.Element("lane", id="-1")
    assert _lane_width_at(lane, 0.0) is None


def test_lane_width_at_constant_width():
    lane = _lane(-1, "driving", 3.5)
    assert _lane_width_at(lane, 5.0) == 3.5


# ---------------------------------------------------------------------------
# check_lane_geometry_continuity -- the lane-type-transition guard
# ---------------------------------------------------------------------------

def test_same_type_lane_large_width_jump_is_flagged(tmp_path: Path):
    prev = [_lane(-1, "driving", 3.5)]
    nxt = [_lane(-1, "driving", 10.0)]  # implausible jump, same type
    road = _road_with_two_sections("1", 10.0, prev, nxt)
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_geometry_continuity(str(xodr))

    assert report["ok"] is False
    width_issues = [i for i in report["issues"] if i["type"] == "lane_width"]
    assert len(width_issues) == 1


def test_lane_type_transition_large_width_diff_not_flagged(tmp_path: Path):
    # Regression test for the DEEP_QUALITY_SWEEP 20260817 false-positive fix (road 46620):
    # a lane changing type across the boundary (sidewalk -> driving) is NOT the same lane
    # identity, so a large width delta here must NOT be reported as a continuity defect.
    prev = [_lane(-1, "sidewalk", 1.5)]
    nxt = [_lane(-1, "driving", 3.5)]
    road = _road_with_two_sections("1", 10.0, prev, nxt)
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_geometry_continuity(str(xodr))

    assert report["ok"] is True
    width_issues = [i for i in report["issues"] if i["type"] == "lane_width"]
    assert width_issues == []


def test_small_width_delta_same_type_within_tolerance_not_flagged(tmp_path: Path):
    prev = [_lane(-1, "driving", 3.5)]
    nxt = [_lane(-1, "driving", 3.55)]  # 0.05m delta, within default 0.10 eps
    road = _road_with_two_sections("1", 10.0, prev, nxt)
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_geometry_continuity(str(xodr))

    assert report["ok"] is True


def test_single_lane_section_road_skipped(tmp_path: Path):
    road = ET.Element("road", id="1", length="10.0", junction="-1")
    lanes_el = ET.SubElement(road, "lanes")
    sec = ET.SubElement(lanes_el, "laneSection", s="0.0")
    right = ET.SubElement(sec, "right")
    right.append(_lane(-1, "driving", 3.5))
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_geometry_continuity(str(xodr))

    assert report["ok"] is True
    assert report["issues"] == []


def test_malformed_xml_reports_parse_error_not_crash(tmp_path: Path):
    xodr = tmp_path / "broken.xodr"
    xodr.write_text("<OpenDRIVE><road unclosed", encoding="utf-8")
    report = check_lane_geometry_continuity(str(xodr))
    assert report["ok"] is False
    assert report["issues"][0]["type"] == "parse_error"


def test_custom_tolerances_respected(tmp_path: Path):
    prev = [_lane(-1, "driving", 3.5)]
    nxt = [_lane(-1, "driving", 3.6)]  # 0.10m delta
    road = _road_with_two_sections("1", 10.0, prev, nxt)
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    # Default eps=0.10 would just barely pass; a tighter eps must flag it.
    report = check_lane_geometry_continuity(str(xodr), lane_width_eps=0.05)
    assert report["ok"] is False
