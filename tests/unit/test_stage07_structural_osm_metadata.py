from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.pipeline_stages.stage_07_lanes import (
    _build_structural_osm_metadata,
)


def test_stage7_resolves_only_high_confidence_structural_metadata(
    tmp_path, monkeypatch
) -> None:
    osm_path = tmp_path / "source.osm"
    osm_path.write_text("<osm/>", encoding="utf-8")
    root = ET.fromstring(
        '<OpenDRIVE><road id="42" length="10"><planView><geometry '
        's="0" x="0" y="0" hdg="0" length="10"><line/></geometry>'
        '</planView></road></OpenDRIVE>'
    )

    import ultimate_pipeline.enrichment.osm_meta_index as meta_index

    monkeypatch.setattr(
        meta_index,
        "extract_structural_osm_lane_metadata_ways",
        lambda _: [
            {
                "id": "way-1",
                "geometry": [(0.0, 0.0), (10.0, 0.0)],
                "metadata": {"lanes:forward": "2", "lanes:backward": "1"},
            }
        ],
    )
    monkeypatch.setattr(
        meta_index, "project_positioned_osm_metadata_ways", lambda ways, _: ways
    )

    metadata, report = _build_structural_osm_metadata(root, str(osm_path))

    assert report["status"] == "PASS"
    assert report["eligible_road_count"] == 1
    # V103-O1: the raw OSM tags are preserved verbatim, and the directional
    # association is carried alongside them under reserved (non-OSM-tag)
    # keys so the lane stage can honour the OSM way orientation.
    assert metadata["42"]["lanes:forward"] == "2"
    assert metadata["42"]["lanes:backward"] == "1"
    assert metadata["42"]["_osm_direction"] == "forward"
    assert metadata["42"]["_osm_match_class"] in {"EXACT", "HIGH"}
    assert set(metadata) == {"42"}
    assert set(metadata["42"]) == {
        "lanes:forward",
        "lanes:backward",
        "_osm_direction",
        "_osm_way_id",
        "_osm_match_class",
        "_osm_match_confidence",
        # V104 review 4551582442 / 4551582504: the versioned association
        # contract and the OSM source identity reach the geometry consumer.
        "_osm_association_schema",
        "_osm_association_state",
        "_osm_source_sha256",
    }
    assert metadata["42"]["_osm_association_schema"] == "osm_xodr_direction/v1"
    assert metadata["42"]["_osm_association_state"] in {"ok", "incomplete", "ambiguous"}
    # Coverage reporting (registry T06).
    assert report["directional_coverage"]["counts"]["matched"] == 1
    assert report["directional_coverage"]["counts"]["forward"] == 1
    assert report["directional_coverage"]["counts"]["reversed"] == 0


def test_stage7_marks_missing_osm_source_blocked_input(tmp_path) -> None:
    metadata, report = _build_structural_osm_metadata(
        ET.Element("OpenDRIVE"), str(tmp_path / "missing.osm")
    )

    assert metadata == {}
    # V104 review 4551582385: a missing OSM source is BLOCKED_INPUT, and the
    # directional coverage report is still emitted.
    assert report["status"] == "BLOCKED_INPUT"
    assert report["reason"] == "osm_source_unavailable"
    assert report["directional_coverage"]["status"] == "BLOCKED_INPUT"
