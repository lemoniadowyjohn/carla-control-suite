import json
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.access_restriction_metadata import (
    AccessMatch,
    AccessWay,
    USERDATA_KEY,
    attach_access_metadata,
    match_access_ways,
)


def _road(road_id: str, name: str, x: float) -> ET.Element:
    return ET.fromstring(
        f'<road id="{road_id}" name="{name}" length="10" junction="-1">'
        f'<planView><geometry s="0" x="{x}" y="0" hdg="0" length="10"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><center><lane id="0" type="none"/></center>'
        '<right><lane id="-1" type="driving"><width sOffset="0" a="3.5"/></lane></right>'
        '</laneSection></lanes></road>'
    )


def test_metadata_round_trip_is_idempotent_and_has_no_lane_effect():
    root = ET.Element("OpenDRIVE")
    root.append(_road("1", "Access Road", 0))
    root.append(_road("2", "No Match", 20))
    before_lanes = len(root.findall(".//lane"))
    report = attach_access_metadata(
        root,
        [
            AccessMatch("w1", "1", {"access": "destination", "vehicle": "no"}, 0.98, "HIGH", 0.1, 1.0),
        ],
    )
    report_repeat = attach_access_metadata(
        root,
        [
            AccessMatch("w1", "1", {"access": "destination", "vehicle": "no"}, 0.98, "HIGH", 0.1, 1.0),
        ],
    )
    vectors = root.findall(f"./road[@id='1']/userData/vector[@key='{USERDATA_KEY}']")
    assert len(vectors) == 1
    assert root.findall(f"./road[@id='2']/userData/vector[@key='{USERDATA_KEY}']") == []
    payload = json.loads(vectors[0].get("value"))
    assert payload["osm_way_id"] == "w1"
    assert payload["tags"] == {"access": "destination", "vehicle": "no"}
    assert len(root.findall(".//lane")) == before_lanes
    assert report["roads_with_access_metadata"] == 1
    assert report_repeat["metadata_records_written"] == 1
    assert report["routing_or_lane_behavior_changed"] is False


def test_exact_name_and_geometry_contract_matches_split_xodr_roads_only():
    root = ET.Element("OpenDRIVE")
    root.append(_road("1", "Access Road", 0))
    root.append(_road("2", "Access Road", 10))
    root.append(_road("3", "Other Road", 0))
    way = AccessWay(
        "w1", "Access Road", "residential", ((0.0, 0.0), (20.0, 0.0)), {"motor_vehicle": "no"}
    )
    matches, outcomes = match_access_ways(root, [way], spacing_m=1.0)
    assert [match.xodr_road_id for match in matches] == ["1", "2"]
    assert all(match.mean_distance_m == 0.0 for match in matches)
    assert all(match.coverage_within_2m == 1.0 for match in matches)
    assert outcomes == {"matched_way": 1}


def test_name_match_without_geometry_coverage_fails_closed():
    root = ET.Element("OpenDRIVE")
    root.append(_road("1", "Access Road", 100))
    way = AccessWay(
        "w1", "Access Road", "residential", ((0.0, 0.0), (10.0, 0.0)), {"psv": "no"}
    )
    matches, outcomes = match_access_ways(root, [way], spacing_m=1.0)
    assert matches == []
    assert outcomes == {"unmatched_way": 1}
