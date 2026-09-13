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
    assert metadata == {"42": {"lanes:forward": "2", "lanes:backward": "1"}}


def test_stage7_marks_missing_osm_source_not_run(tmp_path) -> None:
    metadata, report = _build_structural_osm_metadata(
        ET.Element("OpenDRIVE"), str(tmp_path / "missing.osm")
    )

    assert metadata == {}
    assert report["status"] == "NOT_RUN"
