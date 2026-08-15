from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.tile_validation.geometry_seam_checker import GeometrySeamChecker
from ultimate_pipeline.tile_validation.lane_seam_checker import LaneSeamChecker


def _road_xml(
    road_id: str,
    *,
    x: float,
    y: float,
    hdg: float = 0.0,
    length: float = 10.0,
    z: float = 0.0,
    lane_id: str = "-1",
    road_mark: bool = True,
) -> ET.Element:
    road = ET.Element("road", id=road_id, name=f"road-{road_id}", length=f"{length}", junction="-1")
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(
        plan,
        "geometry",
        s="0.0",
        x=f"{x}",
        y=f"{y}",
        hdg=f"{hdg}",
        length=f"{length}",
    )
    ET.SubElement(geom, "line")
    elev_profile = ET.SubElement(road, "elevationProfile")
    ET.SubElement(elev_profile, "elevation", s="0.0", a=f"{z}", b="0.0", c="0.0", d="0.0")
    lanes = ET.SubElement(road, "lanes")
    lane_section = ET.SubElement(lanes, "laneSection", s="0.0")
    center = ET.SubElement(lane_section, "center")
    ET.SubElement(center, "lane", id="0", type="none", level="false")
    right = ET.SubElement(lane_section, "right")
    lane = ET.SubElement(right, "lane", id=lane_id, type="driving", level="false")
    if road_mark:
        ET.SubElement(lane, "roadMark", sOffset="0.0", type="solid", weight="standard", color="white", width="0.15")
    ET.SubElement(lane, "width", sOffset="0.0", a="3.5", b="0.0", c="0.0", d="0.0")
    return road


def _write_tile(path: Path, *roads: ET.Element) -> Path:
    root = ET.Element("OpenDRIVE")
    ET.SubElement(root, "header", revMajor="1", revMinor="4", name=path.stem, version="1.00")
    for road in roads:
        root.append(road)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_geometry_seam_checker_accepts_continuous_line_endpoint(tmp_path):
    tile_a = _write_tile(tmp_path / "tile_0_0.xodr", _road_xml("a", x=0.0, y=0.0, length=10.0))
    tile_b = _write_tile(tmp_path / "tile_1_0.xodr", _road_xml("b", x=10.0, y=0.0, length=10.0))

    report = GeometrySeamChecker.check(str(tile_a), str(tile_b))

    assert report["status"] == "ok"
    assert report["planar_jump_m"] == 0.0
    assert report["heading_jump_rad"] == 0.0


def test_geometry_seam_checker_flags_discontinuous_line_endpoint(tmp_path):
    tile_a = _write_tile(tmp_path / "tile_0_0.xodr", _road_xml("a", x=0.0, y=0.0, length=10.0))
    tile_b = _write_tile(tmp_path / "tile_1_0.xodr", _road_xml("b", x=11.0, y=0.0, length=10.0))

    report = GeometrySeamChecker.check(str(tile_a), str(tile_b))

    assert report["status"] == "fail"
    assert report["planar_jump_m"] == 1.0


def test_lane_seam_checker_accepts_continuous_driving_lane_pair(tmp_path):
    tile_a = _write_tile(tmp_path / "tile_0_0.xodr", _road_xml("a", x=0.0, y=0.0, length=10.0))
    tile_b = _write_tile(tmp_path / "tile_1_0.xodr", _road_xml("b", x=10.0, y=0.0, length=10.0))

    report = LaneSeamChecker.analyze(str(tile_a), str(tile_b))

    assert len(report.lane_pairs) == 1
    assert report.max_lateral_offset == 0.0
    assert report.max_heading_error == 0.0
    assert report.max_elevation_jump == 0.0
    assert report.marking_mismatch_pairs == 0
    assert report.warnings == []


def test_lane_seam_checker_flags_matched_lateral_break(tmp_path):
    tile_a = _write_tile(tmp_path / "tile_0_0.xodr", _road_xml("a", x=0.0, y=0.0, length=10.0))
    tile_b = _write_tile(tmp_path / "tile_1_0.xodr", _road_xml("b", x=10.5, y=0.0, length=10.0))

    report = LaneSeamChecker.analyze(str(tile_a), str(tile_b))

    assert len(report.lane_pairs) == 1
    assert report.max_lateral_offset == 0.5
    assert any("Lateral offset exceeds 10 cm" in warning for warning in report.warnings)


def test_lane_seam_checker_flags_matched_heading_break(tmp_path):
    tile_a = _write_tile(tmp_path / "tile_0_0.xodr", _road_xml("a", x=0.0, y=0.0, length=10.0))
    tile_b = _write_tile(tmp_path / "tile_1_0.xodr", _road_xml("b", x=10.0, y=0.0, hdg=0.2, length=10.0))

    report = LaneSeamChecker.analyze(str(tile_a), str(tile_b))

    assert len(report.lane_pairs) == 1
    assert report.max_heading_error == pytest.approx(0.2)
    assert any("Heading jump" in warning for warning in report.warnings)
