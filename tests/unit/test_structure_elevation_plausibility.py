from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.core.validation_report import ValidationReport
from ultimate_pipeline.quality.check_structure_elevation_plausibility import (
    check_structure_elevation_plausibility,
    elevation_at_s,
)
from ultimate_pipeline.quality.quality_gate_manager import QualityGateManager


def _road(road_id: str, *, elevation: float, length: float = 20.0) -> ET.Element:
    road = ET.Element("road", id=road_id, length=str(length), junction="-1")
    plan_view = ET.SubElement(road, "planView")
    geometry = ET.SubElement(
        plan_view,
        "geometry",
        s="0",
        x="0",
        y="0",
        hdg="0",
        length=str(length),
    )
    ET.SubElement(geometry, "line")
    profile = ET.SubElement(road, "elevationProfile")
    ET.SubElement(profile, "elevation", s="0", a=str(elevation), b="0", c="0", d="0")
    return road


def _root(*roads: ET.Element) -> ET.Element:
    root = ET.Element("OpenDRIVE")
    for road in roads:
        root.append(road)
    return root


def test_bridge_above_terrain_passes_with_interior_endpoint_exclusion():
    report = check_structure_elevation_plausibility(
        _root(_road("bridge", elevation=101.0)),
        road_classes={"bridge": "bridge"},
        terrain_sampler=lambda x, y: (100.0, True),
    )
    assert report["status"] == "PASS"
    assert report["records"][0]["expectation"] == "above_terrain"
    assert report["records"][0]["violation_count"] == 0


def test_bridge_at_ground_is_flagged_without_attempting_a_height_correction():
    root = _root(_road("bridge", elevation=100.0))
    report = check_structure_elevation_plausibility(
        root,
        road_classes={"bridge": "bridge"},
        terrain_sampler=lambda x, y: (100.0, True),
    )
    assert report["status"] == "FAIL"
    assert report["records"][0]["violation_ratio"] == 1.0
    assert elevation_at_s(root.find("./road"), 10.0) == 100.0


def test_tunnel_below_terrain_passes_and_missing_terrain_is_incomplete():
    root = _root(_road("tunnel", elevation=99.0))
    passing = check_structure_elevation_plausibility(
        root,
        road_classes={"tunnel": "tunnel"},
        terrain_sampler=lambda x, y: (100.0, True),
    )
    incomplete = check_structure_elevation_plausibility(
        root,
        road_classes={"tunnel": "tunnel"},
        terrain_sampler=lambda x, y: (None, False),
    )
    assert passing["status"] == "PASS"
    assert incomplete["status"] == "INCOMPLETE"
    assert incomplete["ok"] is False


def test_active_elevation_polynomial_is_evaluated_at_the_requested_s():
    road = _road("1", elevation=100.0)
    profile = road.find("elevationProfile")
    ET.SubElement(profile, "elevation", s="10", a="105", b="0.5", c="0", d="0")
    assert elevation_at_s(road, 5.0) == 100.0
    assert elevation_at_s(road, 14.0) == 107.0


def test_quality_gate_manager_records_incomplete_evidence_as_a_failure(tmp_path):
    xodr = tmp_path / "bridge.xodr"
    ET.ElementTree(_root(_road("bridge", elevation=101.0))).write(xodr, encoding="utf-8")
    manager = QualityGateManager(ValidationReport())
    report = manager.gate_structure_elevation_plausibility(
        str(xodr), road_classes={"bridge": "bridge"}, terrain_sampler=None
    )
    assert report["status"] == "INCOMPLETE"
    assert "structure_elevation_plausibility" in manager.get_failures()
