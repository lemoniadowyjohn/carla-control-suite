from __future__ import annotations

import xml.etree.ElementTree as ET
import json

import pytest

from ultimate_pipeline.enrichment.osm_meta_index import build_osm_meta_index
from ultimate_pipeline.lanes.lane_repair import LaneRepair
from ultimate_pipeline.osm.osm_to_xodr_wrapper import OSMToXODRConfig


def _road_with_driving_lane(
    road_id: str,
    *,
    width: float = 6.0,
    highway: str | None = None,
    lanes: str | None = None,
    osm_width: str | None = None,
) -> ET.Element:
    road = ET.Element("road", id=road_id, name=f"road-{road_id}", length="25.0", junction="-1")
    ET.SubElement(road, "type", s="0", type="town")
    if any(v is not None for v in (highway, lanes, osm_width)):
        user_data = ET.SubElement(road, "userData")
        if highway is not None:
            ET.SubElement(user_data, "vector", key="osm:tag:highway", value=highway)
        if lanes is not None:
            ET.SubElement(user_data, "vector", key="osm:tag:lanes", value=lanes)
        if osm_width is not None:
            ET.SubElement(user_data, "vector", key="osm:tag:width", value=osm_width)
    lanes_el = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes_el, "laneSection", s="0.0")
    center = ET.SubElement(section, "center")
    ET.SubElement(center, "lane", id="0", type="none", level="false")
    right = ET.SubElement(section, "right")
    lane = ET.SubElement(right, "lane", id="-1", type="driving", level="false")
    ET.SubElement(lane, "width", sOffset="0.0", a=f"{width:.2f}", b="0.0", c="0.0", d="0.0")
    return road


def _root(*roads: ET.Element) -> ET.Element:
    root = ET.Element("OpenDRIVE")
    for road in roads:
        root.append(road)
    return root


def _driving_width(road: ET.Element) -> float:
    width = road.find(".//lane[@type='driving']/width")
    assert width is not None
    return float(width.get("a", "nan"))


def test_osm_to_xodr_default_lane_width_is_not_six_meter_placeholder() -> None:
    assert OSMToXODRConfig().lane_width == pytest.approx(3.5)


def test_osm_meta_index_includes_lane_width_inputs(tmp_path) -> None:
    # Keyed by street NAME, not way id (OSM way ids and Osm2Odr/netconvert-assigned
    # XODR road ids are disjoint numbering schemes -- verified 2026-08-26 against the
    # real pinned map: 0.0000% direct-id match rate). A way with no name tag cannot
    # be matched by any real consumer and is correctly excluded from the index.
    osm = tmp_path / "roads.osm"
    osm.write_text(
        """<osm>
  <way id="42">
    <nd ref="1" />
    <nd ref="2" />
    <tag k="name" v="Bahnhofstrasse" />
    <tag k="highway" v="residential" />
    <tag k="lanes" v="2" />
    <tag k="width" v="6.6 m" />
  </way>
</osm>
""",
        encoding="utf-8",
    )

    meta = build_osm_meta_index(str(osm))

    assert "42" not in meta
    assert meta["Bahnhofstrasse"]["highway"] == "residential"
    assert meta["Bahnhofstrasse"]["lanes"] == "2"
    assert meta["Bahnhofstrasse"]["width"] == "6.6 m"


def test_width_policy_replaces_converter_six_meter_lane_from_highway_metadata() -> None:
    from ultimate_pipeline.enrichment.lane_width_policy import apply_lane_width_policy

    road = _road_with_driving_lane("1", width=6.0, highway="residential")
    report = apply_lane_width_policy(_root(road))

    assert _driving_width(road) == pytest.approx(3.25)
    assert report["totals"]["driving_widths_updated"] == 1
    assert report["totals"]["six_meter_placeholders_found"] == 1


def test_width_policy_derives_per_lane_width_from_osm_total_width_and_lane_count() -> None:
    from ultimate_pipeline.enrichment.lane_width_policy import apply_lane_width_policy

    road = _road_with_driving_lane("1", width=6.0, highway="primary", lanes="2", osm_width="7.2 m")
    report = apply_lane_width_policy(_root(road))

    assert _driving_width(road) == pytest.approx(3.6)
    assert report["totals"]["source_counts"]["osm_width_per_lane"] == 1


def test_lane_repair_uses_width_policy_instead_of_single_constant() -> None:
    residential = _road_with_driving_lane("1", width=6.0, highway="residential")
    primary = _road_with_driving_lane("2", width=6.0, highway="primary")
    root = _root(residential, primary)

    LaneRepair.standardize(root)

    assert _driving_width(residential) == pytest.approx(3.25)
    assert _driving_width(primary) == pytest.approx(3.5)
    assert _driving_width(residential) != _driving_width(primary)


def test_file_repair_tool_rewrites_existing_placeholder_widths(tmp_path) -> None:
    from ultimate_pipeline.tools.repair_lane_widths import repair

    src = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    report = tmp_path / "report.json"
    ET.ElementTree(_root(_road_with_driving_lane("1", width=6.0, highway="residential"))).write(
        src,
        encoding="utf-8",
        xml_declaration=True,
    )

    result = repair(src, out, report_path=report)

    road = ET.parse(out).getroot().find("road")
    assert road is not None
    assert _driving_width(road) == pytest.approx(3.25)
    assert result["totals"]["six_meter_placeholders_found"] == 1
    assert json.loads(report.read_text(encoding="utf-8"))["totals"]["driving_widths_updated"] == 1
