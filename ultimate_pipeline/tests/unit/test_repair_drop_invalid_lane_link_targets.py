# ultimate_pipeline/tools/repair_drop_invalid_lane_link_targets.py -- zero
# prior test coverage. Standalone CLI repair tool (not imported by the live
# pipeline), but drops <successor>/<predecessor> lane-link elements whose
# target lane id doesn't exist in the adjacent laneSection -- a real
# geometry-repair operation on real XODR files, matching this session's
# established "lane-link repair tool" bug class (LaneWidthClamp no-op,
# missing lane successors, etc.), so worth verifying by direct
# reproduction rather than just reading.
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.tools.repair_drop_invalid_lane_link_targets import (
    repair_drop_invalid_lane_link_targets as repair,
)


def _write_xodr(path: Path, road_xml_inner: str) -> None:
    xodr = f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <road name="R" length="100.0" id="1" junction="-1">
    <lanes>
      {road_xml_inner}
    </lanes>
  </road>
</OpenDRIVE>
"""
    path.write_text(xodr, encoding="utf-8")


def _lane_section(s: float, lanes: list[tuple[int, dict]]) -> str:
    lane_xml_parts = []
    for lane_id, links in lanes:
        link_inner = ""
        if links:
            if "successor" in links:
                link_inner += f'<successor id="{links["successor"]}"/>'
            if "predecessor" in links:
                link_inner += f'<predecessor id="{links["predecessor"]}"/>'
        link_xml = f"<link>{link_inner}</link>" if link_inner else ""
        lane_xml_parts.append(f'<lane id="{lane_id}" type="driving">{link_xml}</lane>')
    lanes_joined = "".join(lane_xml_parts)
    return f'<laneSection s="{s}"><left>{lanes_joined}</left></laneSection>'


def test_drops_successor_pointing_to_nonexistent_lane_in_next_section(tmp_path: Path):
    inner = (
        _lane_section(0.0, [(1, {"successor": 5})])  # 5 doesn't exist in section 1
        + _lane_section(50.0, [(1, {})])
    )
    src = tmp_path / "in.xodr"
    _write_xodr(src, inner)
    out = tmp_path / "out.xodr"

    result = repair(str(src), str(out))

    assert result["repairs"] == 1
    assert result["dropped_lane_links"]["count"] == 1
    item = result["dropped_lane_links"]["items"][0]
    assert item["link_type"] == "successor"
    assert item["target_lane_id"] == 5
    assert item["lane_section"] == 0

    tree = ET.parse(out)
    lane = tree.getroot().find(".//laneSection[1]/left/lane[@id='1']")
    assert lane.find("./link/successor") is None


def test_keeps_successor_pointing_to_real_lane_in_next_section(tmp_path: Path):
    inner = (
        _lane_section(0.0, [(1, {"successor": 1})])
        + _lane_section(50.0, [(1, {})])
    )
    src = tmp_path / "in.xodr"
    _write_xodr(src, inner)
    out = tmp_path / "out.xodr"

    result = repair(str(src), str(out))

    assert result["repairs"] == 0
    tree = ET.parse(out)
    lane = tree.getroot().find(".//laneSection[1]/left/lane[@id='1']")
    assert lane.find("./link/successor") is not None
    assert lane.find("./link/successor").get("id") == "1"


def test_keeps_predecessor_pointing_to_real_lane_in_previous_section(tmp_path: Path):
    inner = (
        _lane_section(0.0, [(1, {})])
        + _lane_section(50.0, [(1, {"predecessor": 1})])
    )
    src = tmp_path / "in.xodr"
    _write_xodr(src, inner)
    out = tmp_path / "out.xodr"

    result = repair(str(src), str(out))

    assert result["repairs"] == 0


def test_drops_predecessor_pointing_to_nonexistent_lane(tmp_path: Path):
    inner = (
        _lane_section(0.0, [(1, {})])
        + _lane_section(50.0, [(1, {"predecessor": 7})])
    )
    src = tmp_path / "in.xodr"
    _write_xodr(src, inner)
    out = tmp_path / "out.xodr"

    result = repair(str(src), str(out))

    assert result["repairs"] == 1
    assert result["dropped_lane_links"]["items"][0]["link_type"] == "predecessor"


def test_first_section_predecessor_never_touched_no_prior_section_to_validate_against(tmp_path: Path):
    # lane 1 in the FIRST laneSection has a predecessor -- this must point
    # to a DIFFERENT road (a road-level boundary link), which this
    # single-road-scoped tool has no context to validate. Must be left
    # alone even though "99" isn't a lane id anywhere in this file.
    inner = _lane_section(0.0, [(1, {"predecessor": 99})])
    src = tmp_path / "in.xodr"
    _write_xodr(src, inner)
    out = tmp_path / "out.xodr"

    result = repair(str(src), str(out))

    assert result["repairs"] == 0
    tree = ET.parse(out)
    lane = tree.getroot().find(".//laneSection[1]/left/lane[@id='1']")
    assert lane.find("./link/predecessor").get("id") == "99"


def test_last_section_successor_never_touched_no_next_section_to_validate_against(tmp_path: Path):
    inner = (
        _lane_section(0.0, [(1, {})])
        + _lane_section(50.0, [(1, {"successor": 99})])
    )
    src = tmp_path / "in.xodr"
    _write_xodr(src, inner)
    out = tmp_path / "out.xodr"

    result = repair(str(src), str(out))

    assert result["repairs"] == 0
    tree = ET.parse(out)
    lane = tree.getroot().find(".//laneSection[2]/left/lane[@id='1']")
    assert lane.find("./link/successor").get("id") == "99"


def test_single_lane_section_road_never_touched(tmp_path: Path):
    inner = _lane_section(0.0, [(1, {"successor": 42, "predecessor": 42})])
    src = tmp_path / "in.xodr"
    _write_xodr(src, inner)
    out = tmp_path / "out.xodr"

    result = repair(str(src), str(out))

    assert result["repairs"] == 0


def test_lane_with_no_link_element_skipped_without_crash(tmp_path: Path):
    inner = (
        _lane_section(0.0, [(1, {})])
        + _lane_section(50.0, [(1, {})])
    )
    src = tmp_path / "in.xodr"
    _write_xodr(src, inner)
    out = tmp_path / "out.xodr"

    result = repair(str(src), str(out))

    assert result["repairs"] == 0
    assert result["dropped_lane_links"]["count"] == 0


def test_multiple_dropped_links_across_sections_reports_all(tmp_path: Path):
    inner = (
        _lane_section(0.0, [(1, {"successor": 5}), (2, {"successor": 6})])
        + _lane_section(50.0, [(1, {}), (2, {})])
    )
    src = tmp_path / "in.xodr"
    _write_xodr(src, inner)
    out = tmp_path / "out.xodr"

    result = repair(str(src), str(out))

    assert result["repairs"] == 2
    assert result["dropped_lane_links"]["count"] == 2
    assert result["dropped_lane_links"]["roads"] == ["1"]


def test_out_dir_created_if_missing(tmp_path: Path):
    inner = _lane_section(0.0, [(1, {})])
    src = tmp_path / "in.xodr"
    _write_xodr(src, inner)
    out = tmp_path / "nested" / "dir" / "out.xodr"

    result = repair(str(src), str(out))

    assert Path(result["out"]).is_file()
