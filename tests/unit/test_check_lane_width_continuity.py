"""ultimate_pipeline/quality/check_lane_width_continuity.py -- flags non-positive lane widths
and sudden width jumps across laneSection boundaries. Found completely untested while
investigating a divergence between this file and its submission/infrastructure/ mirror: the
mirror was missing the same real, documented false-positive fix as
check_lane_geometry_continuity.py (dated 2026-08-17, "DEEP_QUALITY_SWEEP", road 46620) that
skips width-jump comparison across a lane-TYPE transition. Synced the mirror to match and
writing regression coverage for the fix here, since none existed despite it being live on main
for over a week.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.quality.check_lane_width_continuity import (
    _width_at_s,
    check_lane_width_continuity,
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
# _width_at_s
# ---------------------------------------------------------------------------

def test_width_at_s_no_widths_returns_none():
    assert _width_at_s([], 0.0) is None


def test_width_at_s_evaluates_polynomial():
    widths = [ET.Element("width", sOffset="0.0", a="3.5", b="0.0", c="0.0", d="0.0")]
    assert _width_at_s(widths, 5.0) == 3.5


def test_width_at_s_picks_correct_segment_for_multiple_width_records():
    widths = [
        ET.Element("width", sOffset="0.0", a="3.0", b="0.0", c="0.0", d="0.0"),
        ET.Element("width", sOffset="5.0", a="4.0", b="0.0", c="0.0", d="0.0"),
    ]
    assert _width_at_s(widths, 2.0) == 3.0
    assert _width_at_s(widths, 6.0) == 4.0


# ---------------------------------------------------------------------------
# check_lane_width_continuity -- nonpositive width
# ---------------------------------------------------------------------------

def test_nonpositive_width_flagged(tmp_path: Path):
    lane = _lane(-1, "driving", 0.0)
    road = ET.Element("road", id="1", length="10.0")
    lanes_el = ET.SubElement(road, "lanes")
    sec = ET.SubElement(lanes_el, "laneSection", s="0.0")
    right = ET.SubElement(sec, "right")
    right.append(lane)
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_width_continuity(str(xodr))

    assert any(i["type"] == "nonpositive_width" for i in report["issues"])


def test_positive_width_not_flagged(tmp_path: Path):
    lane = _lane(-1, "driving", 3.5)
    road = ET.Element("road", id="1", length="10.0")
    lanes_el = ET.SubElement(road, "lanes")
    sec = ET.SubElement(lanes_el, "laneSection", s="0.0")
    right = ET.SubElement(sec, "right")
    right.append(lane)
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_width_continuity(str(xodr))

    assert report["issues"] == []


# ---------------------------------------------------------------------------
# check_lane_width_continuity -- width jump at laneSection boundary
# ---------------------------------------------------------------------------

def test_same_type_lane_large_width_jump_flagged(tmp_path: Path):
    prev = [_lane(-1, "driving", 3.5)]
    nxt = [_lane(-1, "driving", 10.0)]
    road = _road_with_two_sections("1", 10.0, prev, nxt)
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_width_continuity(str(xodr))

    assert any(i["type"] == "width_jump" for i in report["issues"])


def test_lane_type_transition_large_width_diff_not_flagged(tmp_path: Path):
    # Regression test for the DEEP_QUALITY_SWEEP 20260817 false-positive fix (road 46620):
    # a lane changing type across the boundary (sidewalk -> driving) is not the same lane
    # identity, so a large width delta must NOT be reported as a width jump.
    prev = [_lane(-1, "sidewalk", 1.5)]
    nxt = [_lane(-1, "driving", 3.5)]
    road = _road_with_two_sections("1", 10.0, prev, nxt)
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_width_continuity(str(xodr))

    assert not any(i["type"] == "width_jump" for i in report["issues"])


def test_small_width_jump_within_default_tolerance_not_flagged(tmp_path: Path):
    prev = [_lane(-1, "driving", 3.5)]
    nxt = [_lane(-1, "driving", 3.9)]  # 0.4m delta, within default max_jump=1.0
    road = _road_with_two_sections("1", 10.0, prev, nxt)
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_width_continuity(str(xodr))

    assert not any(i["type"] == "width_jump" for i in report["issues"])


def test_custom_max_jump_respected(tmp_path: Path):
    prev = [_lane(-1, "driving", 3.5)]
    nxt = [_lane(-1, "driving", 3.9)]  # 0.4m delta
    road = _road_with_two_sections("1", 10.0, prev, nxt)
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_width_continuity(str(xodr), max_jump=0.2)

    assert any(i["type"] == "width_jump" for i in report["issues"])


def test_missing_matching_lane_id_in_next_section_skipped(tmp_path: Path):
    prev = [_lane(-1, "driving", 3.5)]
    nxt = [_lane(-2, "driving", 3.5)]  # different lane id -- no match
    road = _road_with_two_sections("1", 10.0, prev, nxt)
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_width_continuity(str(xodr))

    assert not any(i["type"] == "width_jump" for i in report["issues"])


def test_malformed_xml_reports_ok_false_not_crash(tmp_path: Path):
    xodr = tmp_path / "broken.xodr"
    xodr.write_text("<OpenDRIVE><road unclosed", encoding="utf-8")
    report = check_lane_width_continuity(str(xodr))
    assert report["ok"] is False
    assert report["warnings"]
