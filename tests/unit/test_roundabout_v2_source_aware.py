from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.topology.roundabout_v2 import detect_candidates
from ultimate_pipeline.topology.roundabout_v2.source_aware import (
    detect_osm_spatial_candidates_from_projected_ways,
    extract_osm_roundabout_ways,
)


def _road(road_id: str, *, y: float, junction: str = "-1") -> ET.Element:
    road = ET.Element("road", {"id": road_id, "junction": junction, "length": "10"})
    plan_view = ET.SubElement(road, "planView")
    geometry = ET.SubElement(
        plan_view,
        "geometry",
        {"s": "0", "x": "0", "y": str(y), "hdg": "0", "length": "10"},
    )
    ET.SubElement(geometry, "line")
    return road


def _supported_root() -> ET.Element:
    root = ET.Element("OpenDRIVE")
    root.extend([_road("10", y=0.0), _road("11", y=2.0, junction="j1")])
    junction = ET.SubElement(root, "junction", {"id": "j1"})
    ET.SubElement(
        junction,
        "connection",
        {"id": "c1", "incomingRoad": "10", "connectingRoad": "11"},
    )
    return root


def _projected_way(way_id: str = "w1", *, y: float = 0.0) -> dict[str, object]:
    return {"id": way_id, "geometry": [(0.0, y), (5.0, y), (10.0, y)]}


def test_spatial_detector_requires_multiple_junction_supported_roads() -> None:
    candidates, report = detect_osm_spatial_candidates_from_projected_ways(
        _supported_root(), [_projected_way()]
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.detection_method == "OSM_SPATIAL"
    assert candidate.osm_way_ids == ("w1",)
    assert candidate.road_ids == ("10", "11")
    assert candidate.junction_ids == ("j1",)
    assert report["candidate_count"] == 1
    assert report["records"][0]["aggregate_evidence"]["coverage_within_threshold"] == 1.0


def test_spatial_detector_fails_closed_for_one_supported_road() -> None:
    root = ET.Element("OpenDRIVE")
    root.append(_road("10", y=0.0, junction="j1"))
    ET.SubElement(root, "junction", {"id": "j1"})

    candidates, report = detect_osm_spatial_candidates_from_projected_ways(
        root, [_projected_way()]
    )

    assert candidates == []
    assert report["excluded_reason_counts"] == {"insufficient_supported_roads": 1}


def test_spatial_detector_rejects_unmatched_source_geometry() -> None:
    candidates, report = detect_osm_spatial_candidates_from_projected_ways(
        _supported_root(), [_projected_way(y=100.0)]
    )

    assert candidates == []
    assert report["excluded_reason_counts"] == {"no_spatial_road_support": 1}


def test_raw_osm_extractor_requires_explicit_roundabout_semantics(tmp_path: Path) -> None:
    source = tmp_path / "source.osm"
    source.write_text(
        "<osm>"
        "<node id='1' lon='11.0' lat='48.0'/><node id='2' lon='11.1' lat='48.1'/>"
        "<way id='2'><nd ref='1'/><nd ref='2'/><tag k='junction' v='circular'/></way>"
        "<way id='1'><nd ref='1'/><nd ref='2'/><tag k='junction' v='roundabout'/></way>"
        "<way id='3'><nd ref='1'/><nd ref='2'/><tag k='highway' v='residential'/></way>"
        "</osm>",
        encoding="utf-8",
    )

    records = extract_osm_roundabout_ways(source)

    assert [record["id"] for record in records] == ["1", "2"]
    assert all(record["metadata"]["junction"] in {"roundabout", "circular"} for record in records)


def test_core_detector_adds_opt_in_source_candidates(monkeypatch) -> None:
    root = ET.Element("OpenDRIVE")
    expected, _ = detect_osm_spatial_candidates_from_projected_ways(
        _supported_root(), [_projected_way()]
    )

    import ultimate_pipeline.topology.roundabout_v2.source_aware as source_aware

    monkeypatch.setattr(source_aware, "detect_osm_spatial_candidates", lambda *_: (expected, {}))

    assert detect_candidates(root, osm_path="source.osm") == expected
