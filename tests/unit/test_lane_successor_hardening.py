from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from ultimate_pipeline.fixes.fix_missing_lane_successors import (
    fix_missing_lane_successors,
)
from ultimate_pipeline.quality.check_lane_link_targets_exist import (
    check_lane_link_targets_exist,
)
from ultimate_pipeline.quality.check_lane_section_successors import (
    repair_and_assert_lane_section_successors,
)


def _lane(lane_id: int, lane_type: str = "driving") -> ET.Element:
    lane = ET.Element("lane", id=str(lane_id), type=lane_type)
    ET.SubElement(lane, "width", sOffset="0", a="3.5", b="0", c="0", d="0")
    return lane


def _section(s: float, lane_ids: list[int]) -> ET.Element:
    section = ET.Element("laneSection", s=str(s))
    right = ET.SubElement(section, "right")
    for lane_id in lane_ids:
        right.append(_lane(lane_id))
    return section


def _road(road_id: str, sections: list[ET.Element], *, length: float = 20.0) -> ET.Element:
    road = ET.Element("road", id=road_id, length=str(length), junction="-1")
    plan_view = ET.SubElement(road, "planView")
    geometry = ET.SubElement(
        plan_view, "geometry", s="0", x="0", y="0", hdg="0", length=str(length)
    )
    ET.SubElement(geometry, "line")
    lanes = ET.SubElement(road, "lanes")
    for section in sections:
        lanes.append(section)
    return road


def _write(path: Path, *roads: ET.Element) -> None:
    root = ET.Element("OpenDRIVE")
    for road in roads:
        root.append(road)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_cross_road_fixer_uses_existing_boundary_lane_instead_of_dangling_same_id(tmp_path: Path):
    source = _road("1", [_section(0, [-1, -2])])
    link = ET.SubElement(source, "link")
    ET.SubElement(link, "successor", elementType="road", elementId="2", contactPoint="start")
    target = _road("2", [_section(0, [-1])])
    source_path = tmp_path / "source.xodr"
    output_path = tmp_path / "output.xodr"
    _write(source_path, source, target)

    report = fix_missing_lane_successors(str(source_path), str(output_path))

    assert report["fixed_count"] == 2
    assert report["fallback_applied"] == 1
    assert report["still_broken"] == []
    root = ET.parse(output_path).getroot()
    repaired_lanes = root.findall("road[@id='1']/lanes/laneSection/right/lane")
    assert [lane.find("link/successor").get("id") for lane in repaired_lanes] == ["-1", "-1"]
    assert check_lane_link_targets_exist(str(output_path))["ok"] is True


def test_intra_road_repair_prefers_geometric_lane_center_when_ids_disagree(tmp_path: Path):
    road = _road("1", [_section(0, [-1, -2]), _section(10, [-1, -3])])
    source_path = tmp_path / "source.xodr"
    output_path = tmp_path / "output.xodr"
    _write(source_path, road)

    report = repair_and_assert_lane_section_successors(
        str(source_path), str(output_path), strict=True
    )

    assert report["repairs"] > 0
    root = ET.parse(output_path).getroot()
    source_lane = root.find(
        "road/lanes/laneSection[@s='0']/right/lane[@id='-2']"
    )
    assert source_lane.find("link/successor").get("id") == "-3"
