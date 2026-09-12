from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.quality.map_acceptance import build_map_acceptance
from ultimate_pipeline.quality.semantic_completeness import measure_semantic_completeness


def _write_sources(tmp_path: Path) -> tuple[Path, Path]:
    osm = tmp_path / "source.osm"
    osm.write_text(
        """<osm version=\"0.6\">
        <node id=\"1\" lat=\"48\" lon=\"11\"><tag k=\"highway\" v=\"traffic_signals\"/></node>
        <node id=\"2\" lat=\"48\" lon=\"11\"><tag k=\"highway\" v=\"traffic_signals\"/></node>
        <way id=\"3\"><tag k=\"footway\" v=\"crossing\"/></way>
        <way id=\"4\"><tag k=\"footway\" v=\"crossing\"/></way>
        <way id=\"5\"><tag k=\"traffic_sign\" v=\"DE:206\"/></way>
        <way id=\"6\"><tag k=\"traffic_sign\" v=\"DE:274-30\"/></way>
        </osm>""",
        encoding="utf-8",
    )
    xodr = tmp_path / "candidate.xodr"
    xodr.write_text(
        """<OpenDRIVE>
        <road id=\"1\" length=\"10\" junction=\"-1\"><objects>
          <object id=\"tl_1\" type=\"traffic_light\"/>
          <object id=\"cw_1\" type=\"crosswalk\"/>
          <object id=\"stop_1\" type=\"stop\" name=\"de:206\"/>
        </objects></road></OpenDRIVE>""",
        encoding="utf-8",
    )
    return osm, xodr


def test_measure_semantic_completeness_reports_per_type_ratios_and_boundaries(tmp_path):
    osm, xodr = _write_sources(tmp_path)
    report = measure_semantic_completeness(xodr, osm)
    assert report["status"] == "MEASURED"
    types = report["object_types"]
    assert types["traffic_lights"]["generated_to_source_ratio"] == 0.5
    assert types["crosswalks"]["generated_to_source_ratio"] == 0.5
    assert types["regulatory_signs"]["generated_to_source_ratio"] == 0.5
    assert "not one-to-one" in types["traffic_lights"]["comparability"]
    assert "DIRECT_FEATURE_COUNT" in types["crosswalks"]["comparability"]


def test_zero_source_count_is_not_reported_as_complete(tmp_path):
    osm, xodr = _write_sources(tmp_path)
    osm.write_text("<osm version=\"0.6\"/>", encoding="utf-8")
    report = measure_semantic_completeness(xodr, osm)
    assert report["object_types"]["traffic_lights"]["status"] == "NOT_APPLICABLE"
    assert report["object_types"]["traffic_lights"]["generated_to_source_ratio"] is None


def test_acceptance_exposes_metric_without_turning_mismatch_into_a_false_hard_gate(tmp_path):
    osm, xodr = _write_sources(tmp_path)
    acceptance = build_map_acceptance(
        {}, run_id="run", final_xodr_path=str(xodr), osm_source_path=str(osm)
    )
    assert acceptance["metrics"]["semantic_completeness"]["status"] == "MEASURED"
    assert "semantic_completeness" not in acceptance["failed_gates"]


def test_unreadable_source_is_incomplete_not_measured(tmp_path):
    _, xodr = _write_sources(tmp_path)
    report = measure_semantic_completeness(xodr, tmp_path / "missing.osm")
    assert report["status"] == "INCOMPLETE"
    assert report["ok"] is False
