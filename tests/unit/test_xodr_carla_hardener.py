"""ultimate_pipeline/tools/xodr_carla_hardener.py -- applies conservative, deterministic fixes
for XODR patterns known to trigger CARLA 0.9.16 Windows crashes (degenerate roadMarks, junction
laneOffset polynomials, s-attribute overflow, invalid paramPoly3 curvature) plus lane/road
connectivity repair. Fully stdlib, no CARLA dependency. This session's history includes an
extensive, still-unresolved live-CARLA crash investigation (LiveKernelEvent 141 GPU watchdog);
this module exists specifically to prevent a DIFFERENT, already-understood class of CARLA
crashes at the data level, so its correctness matters directly for map loadability. Wired into
run_full_domain_gap.py, carla_smoke_suite.py, and run_auto_xodr_record.py. Found via an expanded
orphaned-.pyc sweep of the top-level tests/ directory (the original
tests/test_xodr_carla_hardener.py no longer exists on this branch, and the module had zero
coverage anywhere on it).
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.tools.xodr_carla_hardener import (
    Finding,
    _clamp,
    _clamp_s_endpoints,
    _curv_proxy,
    _fix_connectivity,
    _float,
    _lane_sections_sorted,
    _lanes_at_contact,
    _remove_degenerate_roadmarks,
    _zero_laneoffset_on_junctions,
    harden_xodr,
)


# ---------------------------------------------------------------------------
# _float / _clamp
# ---------------------------------------------------------------------------

def test_float_none_returns_default():
    assert _float(None, 5.0) == 5.0


def test_float_invalid_string_returns_default():
    assert _float("not_a_number", 5.0) == 5.0


def test_float_valid_string():
    assert _float("3.14") == 3.14


def test_clamp_within_range_unchanged():
    assert _clamp(5.0, 0.0, 10.0) == 5.0


def test_clamp_below_range_clamps_to_lo():
    assert _clamp(-5.0, 0.0, 10.0) == 0.0


def test_clamp_above_range_clamps_to_hi():
    assert _clamp(15.0, 0.0, 10.0) == 10.0


# ---------------------------------------------------------------------------
# _remove_degenerate_roadmarks
# ---------------------------------------------------------------------------

def test_remove_degenerate_roadmark_line_length_and_space_zero():
    root = ET.Element("OpenDRIVE")
    rm = ET.SubElement(root, "roadMark", type="broken")
    ET.SubElement(rm, "line", length="0.0", space="0.0")
    findings = []
    _remove_degenerate_roadmarks(root, findings)
    assert rm.findall("line") == []
    assert findings[0].code == "ROADMARK_DEGENERATE"


def test_remove_degenerate_roadmarks_keeps_valid_line():
    root = ET.Element("OpenDRIVE")
    rm = ET.SubElement(root, "roadMark", type="broken")
    ET.SubElement(rm, "line", length="3.0", space="6.0")
    findings = []
    _remove_degenerate_roadmarks(root, findings)
    assert len(rm.findall("line")) == 1
    assert findings == []


def test_remove_degenerate_roadmarks_ignores_non_solid_broken_types():
    root = ET.Element("OpenDRIVE")
    rm = ET.SubElement(root, "roadMark", type="none")
    ET.SubElement(rm, "line", length="0.0", space="0.0")
    findings = []
    _remove_degenerate_roadmarks(root, findings)
    assert len(rm.findall("line")) == 1  # untouched -- type not in ("solid", "broken")


# ---------------------------------------------------------------------------
# _zero_laneoffset_on_junctions
# ---------------------------------------------------------------------------

def test_zero_laneoffset_zeroes_existing_offsets_on_junction_road():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", junction="5")
    lanes = ET.SubElement(road, "lanes")
    ET.SubElement(lanes, "laneOffset", s="0.0", a="1.5", b="0.1", c="0.0", d="0.0")
    findings = []
    _zero_laneoffset_on_junctions(root, findings)
    lo = lanes.find("laneOffset")
    assert lo.get("a") == "0.0"
    assert lo.get("b") == "0.0"
    assert findings[0].code == "LANEOFFSET_JUNCTION_ZEROED"


def test_zero_laneoffset_adds_offset_when_none_present():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", junction="5")
    lanes = ET.SubElement(road, "lanes")
    findings = []
    _zero_laneoffset_on_junctions(root, findings)
    assert len(lanes.findall("laneOffset")) == 1


def test_zero_laneoffset_skips_non_junction_roads():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", junction="-1")
    lanes = ET.SubElement(road, "lanes")
    ET.SubElement(lanes, "laneOffset", s="0.0", a="1.5", b="0.0", c="0.0", d="0.0")
    findings = []
    _zero_laneoffset_on_junctions(root, findings)
    assert lanes.find("laneOffset").get("a") == "1.5"  # untouched
    assert findings == []


def test_zero_laneoffset_skips_junction_road_with_no_lanes_element():
    root = ET.Element("OpenDRIVE")
    ET.SubElement(root, "road", id="1", junction="5")  # no <lanes> at all
    findings = []
    _zero_laneoffset_on_junctions(root, findings)
    assert findings == []  # must not raise


# ---------------------------------------------------------------------------
# _clamp_s_endpoints
# ---------------------------------------------------------------------------

def test_clamp_s_endpoints_clamps_s_equal_to_length():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="100.0")
    ET.SubElement(road, "signal", s="100.0")
    findings = []
    _clamp_s_endpoints(root, findings)
    signal = road.find("signal")
    assert float(signal.get("s")) < 100.0
    assert findings[0].code == "S_CLAMPED"


def test_clamp_s_endpoints_leaves_interior_s_unchanged():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="100.0")
    ET.SubElement(road, "signal", s="50.0")
    findings = []
    _clamp_s_endpoints(root, findings)
    assert road.find("signal").get("s") == "50.0"
    assert findings == []


def test_clamp_s_endpoints_skips_zero_length_road():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="0.0")
    ET.SubElement(road, "signal", s="0.0")
    findings = []
    _clamp_s_endpoints(root, findings)  # must not raise
    assert findings == []


# ---------------------------------------------------------------------------
# _curv_proxy
# ---------------------------------------------------------------------------

def test_curv_proxy_straight_line_is_zero():
    xs = [0.0, 1.0, 2.0, 3.0]
    ys = [0.0, 0.0, 0.0, 0.0]
    assert _curv_proxy(xs, ys) == 0.0


def test_curv_proxy_right_angle_turn_is_positive():
    xs = [0.0, 1.0, 1.0]
    ys = [0.0, 0.0, 1.0]
    assert _curv_proxy(xs, ys) > 0.0


def test_curv_proxy_needs_at_least_three_points():
    assert _curv_proxy([0.0, 1.0], [0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# _lane_sections_sorted / _lanes_at_contact
# ---------------------------------------------------------------------------

def test_lane_sections_sorted_by_s():
    road = ET.Element("road")
    lanes = ET.SubElement(road, "lanes")
    ET.SubElement(lanes, "laneSection", s="50.0")
    ET.SubElement(lanes, "laneSection", s="0.0")
    sections = _lane_sections_sorted(road)
    assert [s.get("s") for s in sections] == ["0.0", "50.0"]


def test_lane_sections_sorted_no_lanes_element_returns_empty():
    assert _lane_sections_sorted(ET.Element("road")) == []


def test_lanes_at_contact_start_uses_first_section():
    road = ET.Element("road")
    lanes = ET.SubElement(road, "lanes")
    first = ET.SubElement(lanes, "laneSection", s="0.0")
    ET.SubElement(lanes, "laneSection", s="50.0")
    right = ET.SubElement(first, "right")
    ET.SubElement(right, "lane", id="-1")
    result = _lanes_at_contact(road, "start")
    assert -1 in result


def test_lanes_at_contact_end_uses_last_section():
    road = ET.Element("road")
    lanes = ET.SubElement(road, "lanes")
    ET.SubElement(lanes, "laneSection", s="0.0")
    last = ET.SubElement(lanes, "laneSection", s="50.0")
    right = ET.SubElement(last, "right")
    ET.SubElement(right, "lane", id="-2")
    result = _lanes_at_contact(road, "end")
    assert -2 in result


def test_lanes_at_contact_no_lane_sections_returns_empty():
    assert _lanes_at_contact(ET.Element("road"), "start") == {}


# ---------------------------------------------------------------------------
# _fix_connectivity
# ---------------------------------------------------------------------------

def test_fix_connectivity_removes_road_link_to_missing_road_when_repair_true():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", junction="-1")
    link = ET.SubElement(road, "link")
    ET.SubElement(link, "successor", elementType="road", elementId="99")  # road 99 does not exist
    findings = []
    _fix_connectivity(root, findings, repair=True)
    assert link.find("successor") is None
    assert any(f.code == "ROAD_LINK_REMOVED" for f in findings)


def test_fix_connectivity_reports_only_when_repair_false():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", junction="-1")
    link = ET.SubElement(road, "link")
    ET.SubElement(link, "successor", elementType="road", elementId="99")
    findings = []
    _fix_connectivity(root, findings, repair=False)
    assert link.find("successor") is not None  # NOT removed
    assert any(f.code == "ROAD_LINK_INVALID" for f in findings)


def test_fix_connectivity_valid_road_link_untouched():
    root = ET.Element("OpenDRIVE")
    road1 = ET.SubElement(root, "road", id="1", junction="-1")
    ET.SubElement(root, "road", id="2", junction="-1")
    link = ET.SubElement(road1, "link")
    ET.SubElement(link, "successor", elementType="road", elementId="2")
    findings = []
    _fix_connectivity(root, findings, repair=True)
    assert link.find("successor") is not None
    assert findings == []


def test_fix_connectivity_junction_connector_road_link_removed():
    root = ET.Element("OpenDRIVE")
    junction = ET.SubElement(root, "junction", id="5")
    road = ET.SubElement(root, "road", id="1", junction="5")
    ET.SubElement(road, "link")  # connectors should not have a road-level <link>
    ET.SubElement(junction, "connection", id="0", incomingRoad="-1", connectingRoad="1")
    findings = []
    _fix_connectivity(root, findings, repair=True)
    assert road.find("link") is None
    assert any(f.code == "JUNCTION_LINK_REMOVED" for f in findings)


def test_fix_connectivity_missing_junction_reported():
    root = ET.Element("OpenDRIVE")
    ET.SubElement(root, "road", id="1", junction="5")  # junction "5" does not exist anywhere
    findings = []
    _fix_connectivity(root, findings, repair=True)
    assert any(f.code == "JUNCTION_MISSING" for f in findings)


def test_fix_connectivity_connector_missing_from_junction_connections_repaired():
    root = ET.Element("OpenDRIVE")
    junction = ET.SubElement(root, "junction", id="5")
    ET.SubElement(root, "road", id="1", junction="5")  # no matching <connection> in junction "5"
    findings = []
    _fix_connectivity(root, findings, repair=True)
    assert junction.findall("connection[@connectingRoad='1']")
    assert any(f.code == "JUNCTION_CONN_ADDED" for f in findings)


def test_fix_connectivity_lane_link_to_missing_lane_removed():
    root = ET.Element("OpenDRIVE")
    road1 = ET.SubElement(root, "road", id="1", junction="-1")
    road2 = ET.SubElement(root, "road", id="2", junction="-1")
    link = ET.SubElement(road1, "link")
    ET.SubElement(link, "successor", elementType="road", elementId="2", contactPoint="start")
    lanes1 = ET.SubElement(road1, "lanes")
    ls1 = ET.SubElement(lanes1, "laneSection", s="0.0")
    right1 = ET.SubElement(ls1, "right")
    lane1 = ET.SubElement(right1, "lane", id="-1")
    lane1_link = ET.SubElement(lane1, "link")
    ET.SubElement(lane1_link, "successor", id="-5")  # road 2 has no lane "-5"
    lanes2 = ET.SubElement(road2, "lanes")
    ls2 = ET.SubElement(lanes2, "laneSection", s="0.0")
    right2 = ET.SubElement(ls2, "right")
    ET.SubElement(right2, "lane", id="-1")

    findings = []
    _fix_connectivity(root, findings, repair=True)

    assert lane1_link.find("successor") is None
    assert any(f.code == "LANE_LINK_REMOVED" for f in findings)


# ---------------------------------------------------------------------------
# harden_xodr -- end-to-end
# ---------------------------------------------------------------------------

def _write_xodr(path: Path) -> None:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="100.0", junction="-1")
    plan = ET.SubElement(road, "planView")
    ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="100.0")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0.0")
    right = ET.SubElement(section, "right")
    lane = ET.SubElement(right, "lane", id="-1", type="driving")
    rm = ET.SubElement(lane, "roadMark", type="broken")
    ET.SubElement(rm, "line", length="0.0", space="0.0")  # degenerate -- should be removed
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)


def test_harden_xodr_writes_hardened_output_and_report(tmp_path: Path):
    in_path = tmp_path / "in.xodr"
    out_path = tmp_path / "out.xodr"
    report_path = tmp_path / "report.json"
    _write_xodr(in_path)

    report = harden_xodr(in_path, out_path, report_path=report_path)

    assert report["ok"] is True
    assert out_path.is_file()
    assert report_path.is_file()
    on_disk_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert on_disk_report["ok"] is True

    out_root = ET.parse(str(out_path)).getroot()
    assert out_root.find(".//roadMark/line") is None  # degenerate line removed


def test_harden_xodr_validate_only_does_not_write_output(tmp_path: Path):
    in_path = tmp_path / "in.xodr"
    out_path = tmp_path / "out.xodr"
    _write_xodr(in_path)

    harden_xodr(in_path, out_path, validate_only=True)

    assert not out_path.exists()


def test_harden_xodr_disabled_checks_are_skipped(tmp_path: Path):
    in_path = tmp_path / "in.xodr"
    out_path = tmp_path / "out.xodr"
    _write_xodr(in_path)

    report = harden_xodr(
        in_path, out_path,
        fix_roadmarks=False, fix_laneoffset_junctions=False,
        clamp_s_endpoints=False, parampoly3_sanity=False, fix_connectivity=False,
    )

    assert report["repair_count"] == 0
    out_root = ET.parse(str(out_path)).getroot()
    assert out_root.find(".//roadMark/line") is not None  # NOT removed, check was disabled
