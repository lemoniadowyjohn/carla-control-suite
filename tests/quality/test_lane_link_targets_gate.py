"""ultimate_pipeline/quality/check_lane_link_targets_exist.py -- offline gate that catches
dangling lane predecessor/successor links (a lane referencing a target lane id that doesn't
exist in the adjacent laneSection), a real class of downstream CARLA import failure. Used by
sumo_repair.py's gate-count tracking (SUMORepair._gate_counts). Found as an orphaned .pyc in
tests/quality/__pycache__ (test_lane_link_targets_gate.cpython-*.pyc with no matching .py
source) while auditing the newly-discovered tests/quality/ directory.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.quality.check_lane_link_targets_exist import (
    assert_lane_link_targets_exist,
    check_lane_link_targets_exist,
    repair_drop_invalid_lane_links,
    write_report,
)


def _lane(lane_id, lane_type="driving", pred=None, succ=None):
    lane = ET.Element("lane", id=str(lane_id), type=lane_type)
    if pred is not None or succ is not None:
        link = ET.SubElement(lane, "link")
        if pred is not None:
            ET.SubElement(link, "predecessor", id=str(pred))
        if succ is not None:
            ET.SubElement(link, "successor", id=str(succ))
    return lane


def _lane_section(s, lanes):
    section = ET.Element("laneSection", s=str(s))
    right = ET.SubElement(section, "right")
    for lane in lanes:
        right.append(lane)
    return section


def _road(rid, sections):
    road = ET.Element("road", id=rid, length="20.0", junction="-1")
    lanes_el = ET.SubElement(road, "lanes")
    for sec in sections:
        lanes_el.append(sec)
    return road


def _write_xodr(path: Path, *roads) -> None:
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# check_lane_link_targets_exist
# ---------------------------------------------------------------------------

def test_valid_successor_link_to_existing_lane_ok(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1, succ=-1)])
    sec1 = _lane_section(10, [_lane(-1, pred=-1)])
    road = _road("1", [sec0, sec1])
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_link_targets_exist(str(xodr))

    assert report["ok"] is True
    assert report["num_issues"] == 0


def test_successor_pointing_to_missing_lane_flagged(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1, succ=-99)])  # -99 doesn't exist in sec1
    sec1 = _lane_section(10, [_lane(-1)])
    road = _road("1", [sec0, sec1])
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_link_targets_exist(str(xodr))

    assert report["ok"] is False
    assert report["num_issues"] == 1
    assert report["issues"][0]["direction"] == "successor"
    assert report["issues"][0]["target_lane_id"] == -99


def test_predecessor_pointing_to_missing_lane_flagged(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1)])
    sec1 = _lane_section(10, [_lane(-1, pred=-99)])  # -99 doesn't exist in sec0
    road = _road("1", [sec0, sec1])
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_link_targets_exist(str(xodr))

    assert report["ok"] is False
    assert report["issues"][0]["direction"] == "predecessor"


def test_dead_end_first_section_predecessor_allowed_by_default(tmp_path: Path):
    # A predecessor link with no previous laneSection at all -- allowed unless
    # allow_dead_ends=False.
    sec0 = _lane_section(0, [_lane(-1, pred=-5)])
    road = _road("1", [sec0])
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_link_targets_exist(str(xodr), allow_dead_ends=True)
    assert report["ok"] is True


def test_dead_end_disallowed_flags_the_link(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1, pred=-5)])
    road = _road("1", [sec0])
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_link_targets_exist(str(xodr), allow_dead_ends=False)
    assert report["ok"] is False
    assert "no previous laneSection" in report["issues"][0]["message"]


def test_dead_end_last_section_successor_allowed_by_default(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1, succ=-5)])
    road = _road("1", [sec0])
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_link_targets_exist(str(xodr), allow_dead_ends=True)
    assert report["ok"] is True


def test_non_driving_lane_type_filtered_out_by_default(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1, lane_type="sidewalk", succ=-99)])
    sec1 = _lane_section(10, [_lane(-1, lane_type="sidewalk")])
    road = _road("1", [sec0, sec1])
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    # default lane_types=("driving",) -- sidewalk lanes are skipped entirely
    report = check_lane_link_targets_exist(str(xodr))
    assert report["ok"] is True


def test_lane_types_filter_can_be_widened(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1, lane_type="sidewalk", succ=-99)])
    sec1 = _lane_section(10, [_lane(-1, lane_type="sidewalk")])
    road = _road("1", [sec0, sec1])
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_link_targets_exist(str(xodr), lane_types=("sidewalk",))
    assert report["ok"] is False


def test_lane_with_no_link_element_skipped(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1)])  # no link at all
    road = _road("1", [sec0])
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_link_targets_exist(str(xodr))
    assert report["ok"] is True


def test_single_lane_section_road_no_issues(tmp_path: Path):
    road = ET.Element("road", id="1", length="10.0")  # no <lanes> at all
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    report = check_lane_link_targets_exist(str(xodr))
    assert report["ok"] is True
    assert report["totals"]["roads_scanned"] == 1


def test_max_issues_truncates_reported_list(tmp_path: Path):
    roads = []
    for i in range(5):
        sec0 = _lane_section(0, [_lane(-1, succ=-99)])
        sec1 = _lane_section(10, [_lane(-1)])
        roads.append(_road(str(i), [sec0, sec1]))
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, *roads)

    report = check_lane_link_targets_exist(str(xodr), max_issues=2)
    assert len(report["issues"]) <= 2


# ---------------------------------------------------------------------------
# repair_drop_invalid_lane_links
# ---------------------------------------------------------------------------

def test_repair_removes_dangling_successor_link(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1, succ=-99)])
    sec1 = _lane_section(10, [_lane(-1)])
    road = _road("1", [sec0, sec1])
    in_xodr = tmp_path / "in.xodr"
    out_xodr = tmp_path / "out.xodr"
    _write_xodr(in_xodr, road)

    result = repair_drop_invalid_lane_links(str(in_xodr), str(out_xodr))

    assert result["removed_count"] == 1
    assert result["post_ok"] is True
    out_root = ET.parse(str(out_xodr)).getroot()
    lane = out_root.find(".//road[@id='1']//laneSection[@s='0']//lane[@id='-1']")
    assert lane.find("link") is None  # empty link element cleaned up entirely


def test_repair_leaves_valid_links_untouched(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1, succ=-1)])
    sec1 = _lane_section(10, [_lane(-1, pred=-1)])
    road = _road("1", [sec0, sec1])
    in_xodr = tmp_path / "in.xodr"
    out_xodr = tmp_path / "out.xodr"
    _write_xodr(in_xodr, road)

    result = repair_drop_invalid_lane_links(str(in_xodr), str(out_xodr))

    assert result["removed_count"] == 0
    out_root = ET.parse(str(out_xodr)).getroot()
    lane = out_root.find(".//road[@id='1']//laneSection[@s='0']//lane[@id='-1']")
    assert lane.find("link/successor") is not None


def test_repair_creates_output_parent_dirs(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1)])
    road = _road("1", [sec0])
    in_xodr = tmp_path / "in.xodr"
    out_xodr = tmp_path / "nested" / "dir" / "out.xodr"
    _write_xodr(in_xodr, road)

    repair_drop_invalid_lane_links(str(in_xodr), str(out_xodr))
    assert out_xodr.is_file()


# ---------------------------------------------------------------------------
# assert_lane_link_targets_exist
# ---------------------------------------------------------------------------

def test_assert_passes_silently_on_clean_map(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1, succ=-1)])
    sec1 = _lane_section(10, [_lane(-1, pred=-1)])
    road = _road("1", [sec0, sec1])
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    result = assert_lane_link_targets_exist(str(xodr))
    assert result["ok"] is True


def test_assert_raises_on_broken_map(tmp_path: Path):
    sec0 = _lane_section(0, [_lane(-1, succ=-99)])
    sec1 = _lane_section(10, [_lane(-1)])
    road = _road("1", [sec0, sec1])
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, road)

    try:
        assert_lane_link_targets_exist(str(xodr))
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "lane_link_targets_exist failed" in str(exc)


# ---------------------------------------------------------------------------
# write_report
# ---------------------------------------------------------------------------

def test_write_report_creates_parent_dirs_and_valid_json(tmp_path: Path):
    out_path = tmp_path / "nested" / "report.json"
    write_report({"ok": True, "num_issues": 0}, str(out_path))
    assert out_path.is_file()
    assert json.loads(out_path.read_text(encoding="utf-8"))["ok"] is True
