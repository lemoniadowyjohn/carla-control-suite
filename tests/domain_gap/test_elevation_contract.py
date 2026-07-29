import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.domain_gap.elevation_contract import (
    ElevationContract,
    ElevationProfile,
    ElevationSegment,
)


def make_road_elem(
    road_id: str = "1",
    length: float = 100.0,
    elevations: list[tuple[float, float, float, float, float]] | None = None,
) -> ET.Element:
    if elevations is None:
        elevations = [(0.0, 0.0, 0.0, 0.0, 0.0)]
    road = ET.Element("road", id=road_id, length=str(length))
    ep = ET.SubElement(road, "elevationProfile")
    for s, a, b, c, d in elevations:
        ET.SubElement(ep, "elevation", s=str(s), a=str(a), b=str(b), c=str(c), d=str(d))
    return road


def test_flat_profile() -> None:
    road = make_road_elem()
    profile = ElevationProfile.from_xml(road)
    assert profile.road_id == "1"
    assert len(profile.segments) == 1
    assert profile.segments[0].s_start == 0.0
    assert profile.segments[0].s_end == 100.0
    assert profile.height_at(50.0) == 0.0


def test_linear_rise() -> None:
    road = make_road_elem(elevations=[(0.0, 0.0, 0.01, 0.0, 0.0)])
    profile = ElevationProfile.from_xml(road)
    h50 = profile.height_at(50.0)
    assert h50 == pytest.approx(0.5, abs=1e-9)
    h100 = profile.height_at(100.0)
    assert h100 == pytest.approx(1.0, abs=1e-9)


def test_two_segments() -> None:
    road = make_road_elem(length=200.0, elevations=[
        (0.0, 0.0, 0.1, 0.0, 0.0),
        (100.0, 10.0, 0.0, 0.0, 0.0),
    ])
    profile = ElevationProfile.from_xml(road)
    assert len(profile.segments) == 2
    assert profile.segments[0].s_end == 100.0
    assert profile.segments[0].height_end == pytest.approx(10.0, abs=1e-9)
    assert profile.segments[1].s_start == 100.0
    assert profile.segments[1].height_start == 10.0


def test_validate_smooth_ok() -> None:
    road = make_road_elem(length=200.0, elevations=[
        (0.0, 0.0, 0.1, 0.0, 0.0),
        (100.0, 10.0, 0.0, 0.0, 0.0),
    ])
    contract = ElevationContract(height_tol=1e-4)
    report = contract.validate(road)
    assert report.passed


def test_validate_smooth_fail() -> None:
    road = make_road_elem(length=200.0, elevations=[
        (0.0, 0.0, 0.1, 0.0, 0.0),
        (100.0, 20.0, 0.0, 0.0, 0.0),
    ])
    contract = ElevationContract(height_tol=1e-4)
    report = contract.validate(road)
    assert not report.passed
    assert any("discontinuity" in e for e in report.errors)


def test_validate_total_length() -> None:
    road = make_road_elem(length=100.0, elevations=[
        (0.0, 0.0, 0.0, 0.0, 0.0),
        (50.0, 0.0, 0.0, 0.0, 0.0),
    ])
    contract = ElevationContract(length_tol=1e-3)
    report = contract.validate(road)
    assert report.passed


def test_segment_height_at() -> None:
    seg = ElevationSegment(0.0, 10.0, 0.0, 5.0, a=0.0, b=0.5, c=0.0, d=0.0)
    assert seg.height_at(0.0) == 0.0
    assert seg.height_at(10.0) == 5.0
    assert seg.height_at(5.0) == 2.5


def test_profile_height_at_out_of_range() -> None:
    road = make_road_elem()
    profile = ElevationProfile.from_xml(road)
    assert profile.height_at(-1.0) is None
    assert profile.height_at(200.0) is None


def test_empty_profile() -> None:
    road = ET.Element("road", id="99", length="0")
    ET.SubElement(road, "elevationProfile")
    profile = ElevationProfile.from_xml(road)
    assert len(profile.segments) == 0
    assert profile.height_at(0.0) is None
