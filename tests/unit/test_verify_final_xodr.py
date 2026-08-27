"""ultimate_pipeline/tools/verify_final_xodr.py -- offline static check for a real
CARLA-rendering defect class (lanes missing a <width> element render as zero-width/degenerate).
Consumed by final_map_readiness_gate.py (tested in test_final_map_readiness_gate.py), but that
test file's synthetic fixtures had no <lanes> at all, so this module's actual lane-width-scan
logic was never exercised even indirectly. Found untested via the orphaned-.pyc sweep.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.tools.verify_final_xodr import (
    _lane_requires_width,
    _scan_lane_width_warnings,
    _count_junctions_and_connectors,
    verify_final_xodr,
)


def _lane(lane_id, lane_type, has_width=True):
    lane = ET.Element("lane", id=str(lane_id), type=lane_type)
    if has_width:
        ET.SubElement(lane, "width", sOffset="0.0", a="3.5", b="0.0", c="0.0", d="0.0")
    return lane


def _road_with_lanes(road_id, lanes, junction="-1"):
    road = ET.Element("road", id=road_id, length="10.0", junction=junction)
    plan = ET.SubElement(road, "planView")
    ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="10.0")
    lanes_el = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes_el, "laneSection", s="0")
    right = ET.SubElement(section, "right")
    center = ET.SubElement(section, "center")
    ET.SubElement(center, "lane", id="0", type="none")  # centerline, always id=0
    for lane in lanes:
        right.append(lane)
    return road


def _xodr(*roads):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    return root


# ---------------------------------------------------------------------------
# _lane_requires_width
# ---------------------------------------------------------------------------

def test_center_lane_id_zero_never_requires_width():
    assert _lane_requires_width(ET.Element("lane", id="0", type="driving")) is False


def test_lane_with_no_id_does_not_require_width():
    assert _lane_requires_width(ET.Element("lane", type="driving")) is False


def test_driving_lane_requires_width():
    assert _lane_requires_width(ET.Element("lane", id="1", type="driving")) is True


def test_restricted_and_none_types_require_width():
    assert _lane_requires_width(ET.Element("lane", id="1", type="restricted")) is True
    assert _lane_requires_width(ET.Element("lane", id="-1", type="none")) is True


def test_empty_type_requires_width():
    assert _lane_requires_width(ET.Element("lane", id="1", type="")) is True


def test_unrecognized_lane_type_does_not_require_width():
    assert _lane_requires_width(ET.Element("lane", id="1", type="bidirectional")) is False


# ---------------------------------------------------------------------------
# _scan_lane_width_warnings
# ---------------------------------------------------------------------------

def test_scan_lane_with_width_not_flagged():
    road = _road_with_lanes("1", [_lane(-1, "driving", has_width=True)])
    root = _xodr(road)
    result = _scan_lane_width_warnings(root)
    assert result["missing_width_lane_count"] == 0


def test_scan_driving_lane_missing_width_is_flagged():
    road = _road_with_lanes("1", [_lane(-1, "driving", has_width=False)])
    root = _xodr(road)
    result = _scan_lane_width_warnings(root)
    assert result["missing_width_lane_count"] == 1
    assert result["examples"][0]["road_id"] == "1"
    assert result["examples"][0]["lane_id"] == "-1"


def test_scan_center_lane_missing_width_not_flagged():
    # id=0 is exempt even without a <width> child (matches real XODR: center lanes
    # conventionally have no width element).
    road = _road_with_lanes("1", [_lane(-1, "driving", has_width=True)])
    root = _xodr(road)
    result = _scan_lane_width_warnings(root)
    assert result["missing_width_lane_count"] == 0  # only the center lane (id=0) has no width


def test_scan_restricted_missing_width_adds_road_to_explicit_set():
    road = _road_with_lanes("42", [_lane(-1, "restricted", has_width=False)])
    root = _xodr(road)
    result = _scan_lane_width_warnings(root)
    assert result["missing_width_lane_count"] == 1
    assert "42" in result["restricted_or_none_missing_width_road_ids"]


def test_scan_driving_missing_width_does_not_add_to_explicit_set():
    road = _road_with_lanes("42", [_lane(-1, "driving", has_width=False)])
    root = _xodr(road)
    result = _scan_lane_width_warnings(root)
    assert "42" not in result["restricted_or_none_missing_width_road_ids"]


def test_scan_max_examples_caps_the_examples_list():
    lanes = [_lane(-(i + 1), "driving", has_width=False) for i in range(10)]
    road = _road_with_lanes("1", lanes)
    root = _xodr(road)
    result = _scan_lane_width_warnings(root, max_examples=3)
    assert result["missing_width_lane_count"] == 10  # full count, not capped
    assert len(result["examples"]) == 3  # examples list IS capped


# ---------------------------------------------------------------------------
# _count_junctions_and_connectors
# ---------------------------------------------------------------------------

def test_count_junctions_via_connection_elements():
    root = ET.Element("OpenDRIVE")
    junction = ET.SubElement(root, "junction", id="1")
    ET.SubElement(junction, "connection", id="0", connectingRoad="100")
    ET.SubElement(junction, "connection", id="1", connectingRoad="101")
    n_junctions, n_connectors = _count_junctions_and_connectors(root)
    assert n_junctions == 1
    assert n_connectors == 2


def test_count_falls_back_to_road_junction_attribute_when_no_connections():
    root = ET.Element("OpenDRIVE")
    ET.SubElement(root, "junction", id="1")  # a junction exists but has no <connection>
    ET.SubElement(root, "road", id="100", junction="1", length="5.0")
    ET.SubElement(root, "road", id="200", junction="-1", length="5.0")  # ordinary road
    n_junctions, n_connectors = _count_junctions_and_connectors(root)
    assert n_junctions == 1
    assert n_connectors == 1  # only the connector road counted, not the ordinary one


# ---------------------------------------------------------------------------
# verify_final_xodr -- end-to-end
# ---------------------------------------------------------------------------

def test_verify_valid_map_all_widths_present_passes(tmp_path: Path):
    road = _road_with_lanes("1", [_lane(-1, "driving", has_width=True)])
    xodr = tmp_path / "final.xodr"
    ET.ElementTree(_xodr(road)).write(str(xodr), encoding="utf-8", xml_declaration=True)
    report = verify_final_xodr(xodr)
    assert report["ok"] is True
    assert report["road_count"] == 1
    assert report["lane_width_missing"] == 0
    assert Path(report["report_path"]).is_file()


def test_verify_missing_width_fails(tmp_path: Path):
    road = _road_with_lanes("1", [_lane(-1, "driving", has_width=False)])
    xodr = tmp_path / "final.xodr"
    ET.ElementTree(_xodr(road)).write(str(xodr), encoding="utf-8", xml_declaration=True)
    report = verify_final_xodr(xodr)
    assert report["ok"] is False
    assert report["lane_width_missing"] == 1


def test_verify_malformed_xodr_reports_parse_error_not_crash(tmp_path: Path):
    xodr = tmp_path / "broken.xodr"
    xodr.write_text("<OpenDRIVE><road unclosed", encoding="utf-8")
    report = verify_final_xodr(xodr)
    assert report["ok"] is False
    assert report["parse_error"]
    assert report["road_count"] == 0


def test_verify_custom_report_path_respected(tmp_path: Path):
    road = _road_with_lanes("1", [_lane(-1, "driving", has_width=True)])
    xodr = tmp_path / "final.xodr"
    ET.ElementTree(_xodr(road)).write(str(xodr), encoding="utf-8", xml_declaration=True)
    custom_out = tmp_path / "custom_report.json"
    report = verify_final_xodr(xodr, custom_out)
    assert Path(report["report_path"]) == custom_out
    assert custom_out.is_file()
