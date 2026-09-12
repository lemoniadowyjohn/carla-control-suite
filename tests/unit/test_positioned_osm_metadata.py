from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.osm_meta_index import extract_positioned_osm_metadata_ways
from ultimate_pipeline.enrichment.osm_xodr_correspondence import build_metadata_associations
from ultimate_pipeline.enrichment.regulatory_sign_writer import apply_regulatory_signs
from ultimate_pipeline.enrichment.speed_limit_writer import apply_speed_limits
from ultimate_pipeline.enrichment.turn_lanes_writer import apply_turn_lanes


def _road(road_id: str = "10", *, name: str = "Shared Street") -> ET.Element:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id=road_id, name=name, length="20")
    plan_view = ET.SubElement(road, "planView")
    geometry = ET.SubElement(
        plan_view,
        "geometry",
        s="0",
        x="0",
        y="0",
        hdg="0",
        length="20",
    )
    ET.SubElement(geometry, "line")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    right = ET.SubElement(section, "right")
    ET.SubElement(right, "lane", id="-1", type="driving")
    return root


def test_extract_positioned_metadata_preserves_way_geometry(tmp_path):
    osm = tmp_path / "source.osm"
    osm.write_text(
        """<osm>
        <node id="1" lon="11.0" lat="48.0"/>
        <node id="2" lon="11.1" lat="48.1"/>
        <way id="42">
          <nd ref="1"/><nd ref="2"/>
          <tag k="name" v="Source Street"/>
          <tag k="highway" v="residential"/>
          <tag k="maxspeed" v="30"/>
          <tag k="turn:lanes" v="left|through"/>
        </way>
        </osm>""",
        encoding="utf-8",
    )

    records = extract_positioned_osm_metadata_ways(str(osm))

    assert records == [
        {
            "id": "42",
            "name": "Source Street",
            "highway": "residential",
            "geometry": [(11.0, 48.0), (11.1, 48.1)],
            "metadata": {"maxspeed": "30", "turn_lanes": "left|through"},
        }
    ]


def test_high_confidence_association_supplies_metadata_to_all_writers():
    root = _road()
    source = [{
        "id": "osm-1",
        "name": "Source Street",
        "highway": "residential",
        "geometry": [(0.0, 0.0), (20.0, 0.0)],
        "metadata": {
            "maxspeed": "30",
            "turn_lanes": "left|through",
            "traffic_sign": "de:206",
        },
    }]

    associations, report = build_metadata_associations(source, root)

    assert report["eligible_road_count"] == 1
    assert associations["10"]["class"] == "HIGH"
    assert associations["10"]["metadata"]["maxspeed"] == "30"
    assert apply_speed_limits(root, {}, correspondence_by_road_id=associations) == 1
    assert apply_turn_lanes(root, {}, correspondence_by_road_id=associations) == 1
    assert apply_regulatory_signs(root, {}, correspondence_by_road_id=associations) == 1


def test_high_confidence_osm_speed_replaces_existing_unprovenanced_speed():
    root = _road()
    lane = root.find("road/lanes/laneSection/right/lane")
    ET.SubElement(lane, "speed", max="8.33")
    associations = {
        "10": {"class": "HIGH", "metadata": {"maxspeed": "30"}}
    }

    written = apply_speed_limits(root, {}, correspondence_by_road_id=associations)

    speed = lane.find("speed")
    assert written == 1
    assert speed.get("max") == "30"
    assert speed.get("unit") == "km/h"
    assert apply_speed_limits(root, {}, correspondence_by_road_id=associations) == 0


def test_legacy_name_match_does_not_replace_an_existing_speed():
    root = _road()
    lane = root.find("road/lanes/laneSection/right/lane")
    ET.SubElement(lane, "speed", max="8.33")

    written = apply_speed_limits(root, {"Shared Street": {"maxspeed": "30"}})

    speed = lane.find("speed")
    assert written == 0
    assert speed.get("max") == "8.33"
    assert speed.get("unit") is None


def test_conflicting_high_confidence_values_fail_closed():
    root = _road()
    source = [
        {
            "id": "osm-a",
            "geometry": [(0.0, 0.0), (20.0, 0.0)],
            "metadata": {"maxspeed": "30"},
        },
        {
            "id": "osm-b",
            "geometry": [(0.0, 0.0), (20.0, 0.0)],
            "metadata": {"maxspeed": "50"},
        },
    ]

    associations, report = build_metadata_associations(source, root)

    assert associations == {}
    assert report["conflicting_road_count"] == 1
    assert report["conflicts"][0]["reason"] == "conflicting_high_confidence_osm_metadata"


def test_spatial_mode_does_not_fall_back_to_name_matching():
    root = _road()
    legacy_name_index = {
        "Shared Street": {
            "maxspeed": "30",
            "turn_lanes": "left|through",
            "traffic_sign": "de:206",
        }
    }

    assert apply_speed_limits(root, legacy_name_index, correspondence_by_road_id={}) == 0
    assert apply_turn_lanes(root, legacy_name_index, correspondence_by_road_id={}) == 0
    assert apply_regulatory_signs(root, legacy_name_index, correspondence_by_road_id={}) == 0


def test_explicit_osm_speed_sign_replaces_only_identifiable_heuristic():
    root = _road()
    objects = ET.SubElement(root.find("road"), "objects")
    heuristic = ET.SubElement(objects, "object", id="speed_10", type="speed_50")
    third_party = ET.SubElement(objects, "object", id="other", type="speed_70")
    associations = {
        "10": {
            "class": "HIGH",
            "metadata": {"traffic_sign": "de:274-30"},
        }
    }

    inserted = apply_regulatory_signs(root, {}, correspondence_by_road_id=associations)

    assert inserted == 1
    assert heuristic not in list(objects)
    assert third_party in list(objects)
    assert objects.find("object[@name='de:274-30']") is not None
