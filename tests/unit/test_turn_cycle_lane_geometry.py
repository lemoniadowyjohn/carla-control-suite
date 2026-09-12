from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.lane_generator import LaneGenerator
from ultimate_pipeline.enrichment.osm_meta_index import build_osm_meta_index
from ultimate_pipeline.enrichment.turn_lanes_writer import apply_turn_lanes
from ultimate_pipeline.lanes.lanelink_builder import LaneLinkBuilder


def _road(
    road_id: str,
    *,
    name: str = "Approach Road",
    length: str = "100",
    predecessor_junction: bool = False,
    successor_junction: bool = False,
) -> ET.Element:
    road = ET.Element(
        "road", id=road_id, name=name, length=length, junction="-1"
    )
    if predecessor_junction or successor_junction:
        link = ET.SubElement(road, "link")
        if predecessor_junction:
            ET.SubElement(
                link, "predecessor", elementType="junction", elementId="10"
            )
        if successor_junction:
            ET.SubElement(
                link, "successor", elementType="junction", elementId="11"
            )
    ET.SubElement(road, "lanes")
    return road


def _lane_by_id(section: ET.Element, side: str, lane_id: int) -> ET.Element:
    lane = section.find(f"./{side}/lane[@id='{lane_id}']")
    assert lane is not None
    return lane


def _vector(lane: ET.Element, key: str) -> str | None:
    vector = lane.find(f"./userData/vector[@key='{key}']")
    return vector.get("value") if vector is not None else None


def test_osm_index_retains_directional_turn_and_cycleway_tags(tmp_path) -> None:
    osm = tmp_path / "directional.osm"
    osm.write_text(
        """<osm version="0.6"><way id="1">
          <tag k="name" v="Approach Road"/>
          <tag k="turn:lanes:forward" v="left|through"/>
          <tag k="turn:lanes:backward" v="through|right"/>
          <tag k="cycleway" v="lane"/>
        </way></osm>""",
        encoding="utf-8",
    )

    metadata = build_osm_meta_index(str(osm))

    assert metadata["Approach Road"]["turn:lanes:forward"] == "left|through"
    assert metadata["Approach Road"]["turn:lanes:backward"] == "through|right"
    assert metadata["Approach Road"]["cycleway"] == "lane"


def test_turn_marking_writer_retains_directional_metadata_without_combining_sides() -> None:
    root = ET.Element("OpenDRIVE")
    root.append(_road("9"))

    assert apply_turn_lanes(
        root,
        {
            "Approach Road": {
                "turn:lanes:forward": "left|through",
                "turn:lanes:backward": "through|right",
                "turn_lanes": "left|left",
            }
        },
    ) == 1

    user_data = root.find("./road/userData")
    assert user_data is not None
    values = {
        vector.get("key"): vector.get("value")
        for vector in user_data.findall("vector")
    }
    assert values["turnMarking:forward"] == "left|through"
    assert values["turnMarking:backward"] == "through|right"
    assert values["turnMarking"] == "left|through"


def test_directional_turn_lanes_become_approach_geometry_with_provenance() -> None:
    root = ET.Element("OpenDRIVE")
    road = _road(
        "42", predecessor_junction=True, successor_junction=True
    )
    root.append(road)
    structural_osm_meta = {
        "42": {
            "lanes:forward": "1",
            "lanes:backward": "1",
            "turn:lanes:forward": "left|through",
            "turn:lanes:backward": "through|right",
        }
    }

    assert LaneGenerator.ensure_lanes(
        root, verbose=False, structural_osm_meta=structural_osm_meta
    ) == 1

    sections = road.findall("./lanes/laneSection")
    assert [float(section.get("s")) for section in sections] == [0.0, 30.0, 70.0]

    start, through_section, end = sections
    assert _vector(_lane_by_id(start, "left", 2), "turn_lane_pattern") == "through"
    assert _vector(_lane_by_id(start, "left", 1), "turn_lane_pattern") == "right"
    assert _vector(_lane_by_id(start, "left", 1), "turn_lane_direction") == "backward"
    assert _vector(_lane_by_id(start, "left", 1), "lane_count_source") == (
        "osm:turn:lanes:backward"
    )

    assert _vector(_lane_by_id(through_section, "left", 1), "turn_lane_pattern") is None
    assert _vector(_lane_by_id(through_section, "right", -1), "turn_lane_pattern") is None

    assert _vector(_lane_by_id(end, "right", -1), "turn_lane_pattern") == "left"
    assert _vector(_lane_by_id(end, "right", -2), "turn_lane_pattern") == "through"
    assert _vector(_lane_by_id(end, "right", -1), "turn_lane_direction") == "forward"
    assert _vector(_lane_by_id(end, "right", -1), "lane_count_source") == (
        "osm:turn:lanes:forward"
    )
    assert _lane_by_id(end, "right", -1).get("type") == "driving"
    assert _lane_by_id(end, "right", -1).find("width").get("a") == "3.5"

    provenance = LaneGenerator.lane_provenance_report(root)
    turn_lanes = [
        lane
        for lane in provenance["roads"][0]["lanes"]
        if lane["turn_pattern"] is not None
    ]
    assert {lane["turn_direction"] for lane in turn_lanes} == {"forward", "backward"}
    assert all(lane["connector_mapping_status"] == "requires_lanelink_rebuild" for lane in turn_lanes)
    assert provenance["known_limitations"]["connector_mapping"]


def test_cycleway_lane_becomes_biking_geometry_with_explicit_uncertainty() -> None:
    root = ET.Element("OpenDRIVE")
    road = _road("84", name="Cycle Street", length="40")
    root.append(road)

    LaneGenerator.ensure_lanes(
        root,
        verbose=False,
        structural_osm_meta={"84": {"cycleway": "lane"}},
    )

    biking = road.find("./lanes/laneSection/right/lane[@type='biking']")
    assert biking is not None
    assert biking.find("width").get("a") == "2.0"
    assert _vector(biking, "lane_count_source") == "osm:cycleway:side_unknown"
    assert _vector(biking, "lane_count_confidence") == "0.500"
    assert _vector(biking, "cycle_lane_source") == "osm:cycleway:side_unknown"


def test_shared_cycleway_and_separate_cycleway_way_do_not_create_biking_lane() -> None:
    root = ET.Element("OpenDRIVE")
    shared = _road("85", name="Shared Street", length="40")
    separate = _road("86", name="Cycleway", length="40")
    root.extend((shared, separate))

    LaneGenerator.ensure_lanes(
        root,
        verbose=False,
        structural_osm_meta={
            "85": {"cycleway": "shared_lane"},
            "86": {"cycleway": "track", "highway": "cycleway"},
        },
    )

    assert not shared.findall(".//lane[@type='biking']")
    assert not separate.findall(".//lane[@type='biking']")


def test_existing_biking_lane_is_preserved_without_duplication() -> None:
    root = ET.Element("OpenDRIVE")
    road = _road("87", name="Existing Cycle Street", length="40")
    root.append(road)
    section = ET.SubElement(road.find("lanes"), "laneSection", s="0")
    center = ET.SubElement(section, "center")
    ET.SubElement(center, "lane", id="0", type="none", level="false")
    right = ET.SubElement(section, "right")
    driving = ET.SubElement(right, "lane", id="-1", type="driving", level="false")
    ET.SubElement(driving, "width", sOffset="0", a="3.5", b="0", c="0", d="0")
    biking = ET.SubElement(right, "lane", id="-2", type="biking", level="false")
    ET.SubElement(biking, "width", sOffset="0", a="2.0", b="0", c="0", d="0")

    LaneGenerator.ensure_lanes(
        root,
        verbose=False,
        structural_osm_meta={"87": {"cycleway": "lane"}},
    )

    assert len(road.findall(".//lane[@type='biking']")) == 1


def test_turn_lane_geometry_survives_lanelink_regeneration() -> None:
    root = ET.Element("OpenDRIVE")
    approach = _road("1", successor_junction=True)
    connector = ET.SubElement(root, "road", id="2", length="10", junction="11")
    connector_lanes = ET.SubElement(connector, "lanes")
    connector_section = ET.SubElement(connector_lanes, "laneSection", s="0")
    ET.SubElement(connector_section, "center")
    connector_right = ET.SubElement(connector_section, "right")
    connector_lane = ET.SubElement(
        connector_right, "lane", id="-1", type="driving", level="false"
    )
    ET.SubElement(connector_lane, "width", sOffset="0", a="3.5", b="0", c="0", d="0")
    root.insert(0, approach)
    junction = ET.SubElement(root, "junction", id="11")
    ET.SubElement(
        junction,
        "connection",
        id="0",
        incomingRoad="1",
        connectingRoad="2",
        contactPoint="start",
    )

    LaneGenerator.ensure_lanes(
        root,
        verbose=False,
        structural_osm_meta={
            "1": {
                "lanes:forward": "1",
                "lanes:backward": "1",
                "turn:lanes:forward": "left|through",
            }
        },
    )
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)

    turn_lane = _lane_by_id(
        approach.findall("./lanes/laneSection")[-1], "right", -1
    )
    assert turn_lane.get("type") == "driving"
    assert _vector(turn_lane, "turn_lane_pattern") == "left"
    assert junction.find("./connection/laneLink[@from='-1'][@to='-1']") is not None


def test_name_indexed_turn_metadata_stays_hint_only_for_structural_geometry() -> None:
    root = ET.Element("OpenDRIVE")
    road = _road("91", successor_junction=True)
    root.append(road)

    LaneGenerator.ensure_lanes(
        root,
        verbose=False,
        osm_meta={
            "Approach Road": {
                "turn:lanes:forward": "left|through",
                "cycleway": "lane",
            }
        },
    )

    assert len(road.findall("./lanes/laneSection")) == 1
    assert not road.findall(".//lane[@type='biking']")
    assert not road.findall(".//lane/userData/vector[@key='turn_lane_pattern']")


def test_direct_xodr_osm_provenance_enables_structural_lane_features() -> None:
    root = ET.Element("OpenDRIVE")
    road = _road("92", successor_junction=True)
    root.append(road)
    user_data = ET.SubElement(road, "userData")
    ET.SubElement(
        user_data,
        "vector",
        key="osm:tag:turn:lanes:forward",
        value="left|through",
    )
    ET.SubElement(
        user_data,
        "vector",
        key="osm:tag:cycleway",
        value="lane",
    )

    LaneGenerator.ensure_lanes(root, verbose=False)

    final_section = road.findall("./lanes/laneSection")[-1]
    assert _vector(_lane_by_id(final_section, "right", -1), "turn_lane_pattern") == "left"
    assert road.find(".//lane[@type='biking']") is not None
