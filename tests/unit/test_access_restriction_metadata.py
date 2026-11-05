import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.enrichment.access_restriction_metadata import (
    AccessMatch,
    AccessWay,
    USERDATA_KEY,
    attach_access_metadata,
    match_access_ways,
)


def _xodr_root() -> ET.Element:
    root = ET.Element("OpenDRIVE")
    root.append(_road("1", "Access Road", 0))
    return root


def _set_non_strict(monkeypatch) -> None:
    from ultimate_pipeline.config.settings import SETTINGS

    monkeypatch.setattr(SETTINGS, "THESIS_STRICT", False)
    monkeypatch.setattr(SETTINGS, "STRICT_QUALITY_GATES", False)
    monkeypatch.setattr(SETTINGS, "RELEASE_PROFILE", "DEVELOPMENT")
    monkeypatch.delenv("THESIS_STRICT", raising=False)
    monkeypatch.delenv("UP_THESIS_STRICT", raising=False)
    monkeypatch.delenv("UP_STRICT_QUALITY_GATES", raising=False)


def test_missing_osm_source_is_strict_failure(tmp_path, monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    from ultimate_pipeline.enrichment.access_restriction_metadata import apply_access_metadata_from_osm

    monkeypatch.setattr(SETTINGS, "THESIS_STRICT", True)
    with pytest.raises(RuntimeError, match="OSM access source failure"):
        apply_access_metadata_from_osm(_xodr_root(), tmp_path / "missing.osm")


@pytest.mark.parametrize("flag", ["THESIS_STRICT", "UP_THESIS_STRICT"])
def test_thesis_strict_environment_blocks_missing_osm(flag, tmp_path, monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    from ultimate_pipeline.enrichment.access_restriction_metadata import apply_access_metadata_from_osm

    _set_non_strict(monkeypatch)
    monkeypatch.setenv(flag, "1")
    monkeypatch.setattr(SETTINGS, "THESIS_STRICT", False)
    with pytest.raises(RuntimeError, match="OSM access source failure"):
        apply_access_metadata_from_osm(_xodr_root(), tmp_path / "missing.osm")


def test_missing_osm_source_is_explicit_source_failure_when_non_strict(tmp_path, monkeypatch):
    from ultimate_pipeline.enrichment.access_restriction_metadata import apply_access_metadata_from_osm

    _set_non_strict(monkeypatch)
    report = apply_access_metadata_from_osm(_xodr_root(), tmp_path / "missing.osm")
    assert report["source_status"] == "SOURCE_FAILURE"
    assert report["source_failure_reason"]
    assert report["osm_access_ways_considered"] == 0


def test_release_profile_missing_osm_is_strict_failure(tmp_path, monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    from ultimate_pipeline.enrichment.access_restriction_metadata import apply_access_metadata_from_osm

    monkeypatch.setattr(SETTINGS, "THESIS_STRICT", False)
    monkeypatch.setattr(SETTINGS, "RELEASE_PROFILE", "STRUCTURAL_RELEASE")
    monkeypatch.setenv("UP_STRICT_QUALITY_GATES", "0")
    with pytest.raises(RuntimeError, match="OSM access source failure"):
        apply_access_metadata_from_osm(_xodr_root(), tmp_path / "missing.osm")


def test_malformed_osm_is_reported_as_source_failure_when_non_strict(tmp_path, monkeypatch):
    from ultimate_pipeline.enrichment.access_restriction_metadata import apply_access_metadata_from_osm

    _set_non_strict(monkeypatch)
    source = tmp_path / "malformed.osm"
    source.write_text("<osm><way></osm>", encoding="utf-8")
    report = apply_access_metadata_from_osm(_xodr_root(), source)
    assert report["source_status"] == "SOURCE_FAILURE"
    assert "parse" in report["source_failure_reason"].lower()
    assert report["osm_access_ways_considered"] == 0


def test_valid_empty_osm_is_empty_not_source_failure(tmp_path, monkeypatch):
    from ultimate_pipeline.enrichment.access_restriction_metadata import (
        apply_access_metadata_from_osm,
        extract_access_ways,
    )

    _set_non_strict(monkeypatch)
    source = tmp_path / "empty.osm"
    source.write_text('<osm version="0.6"></osm>', encoding="utf-8")
    root = _xodr_root()
    assert extract_access_ways(source, root) == []
    report = apply_access_metadata_from_osm(root, source)
    assert report["source_status"] == "EMPTY"
    assert report["osm_access_ways_considered"] == 0


def test_valid_osm_access_restriction_is_extracted_and_attached(tmp_path, monkeypatch):
    from ultimate_pipeline.enrichment import access_restriction_metadata as access

    _set_non_strict(monkeypatch)
    source = tmp_path / "restricted.osm"
    source.write_text(
        '<osm version="0.6"><node id="1" lon="0" lat="0"/>'
        '<node id="2" lon="0.001" lat="0"/><way id="w1">'
        '<nd ref="1"/><nd ref="2"/><tag k="name" v="Access Road"/>'
        '<tag k="highway" v="residential"/><tag k="access" v="destination"/>'
        '</way></osm>',
        encoding="utf-8",
    )
    monkeypatch.setattr(access, "project_wgs84_to_xodr_native", lambda points: [(0.0, 0.0), (10.0, 0.0)])
    root = _xodr_root()
    report = access.apply_access_metadata_from_osm(root, source)
    assert report["source_status"] == "OK"
    assert report["osm_access_ways_considered"] == 1
    assert report["metadata_records_written"] == 1
    vector = root.find(f"./road[@id='1']/userData/vector[@key='{USERDATA_KEY}']")
    assert vector is not None
    assert json.loads(vector.get("value"))["tags"] == {"access": "destination"}


def test_stage09_records_source_failure_without_clean_zero_count(tmp_path, monkeypatch):
    from unittest import mock

    from ultimate_pipeline.config.settings import SETTINGS
    from ultimate_pipeline.pipeline_stages import stage_09_positional_semantics as stage09

    _set_non_strict(monkeypatch)
    final = tmp_path / "final.xodr"
    final.write_text("fixture", encoding="utf-8")
    root = _xodr_root()
    tree = object()
    report_calls = []
    fake = mock.Mock()
    fake.settings = mock.Mock(
        ENABLE_TRAFFIC_LIGHTS=False,
        ENABLE_BUILDINGS=False,
        ENABLE_REALISM=False,
        OSM_BUILDINGS_GEOJSON=None,
        OSM_FILE=str(tmp_path / "missing.osm"),
    )
    fake.vreport.add_dict.side_effect = lambda *args: report_calls.append(args)
    fake.vreport.add.side_effect = lambda *args: report_calls.append(args)
    fake._assert_geometry_frozen = mock.Mock()
    fake.authority_ledger.provide = mock.Mock()
    monkeypatch.setattr(stage09, "_inject_main_pipeline_globals", lambda: None)
    monkeypatch.setattr(stage09, "load_xodr", lambda _: (tree, root), raising=False)
    save_xodr = mock.Mock()
    monkeypatch.setattr(stage09, "save_xodr", save_xodr, raising=False)
    monkeypatch.setattr(stage09, "XODRStatistics", mock.Mock(compute=lambda _: {}), raising=False)
    monkeypatch.setattr(stage09, "RealismModule", mock.Mock(enrich=lambda _: 0), raising=False)
    monkeypatch.setattr(
        "ultimate_pipeline.enrichment.osm_meta_index.extract_positioned_osm_metadata_ways",
        lambda _: [],
    )
    monkeypatch.setattr(
        "ultimate_pipeline.enrichment.osm_meta_index.project_positioned_osm_metadata_ways",
        lambda ways, _: [],
    )
    monkeypatch.setattr("ultimate_pipeline.enrichment.crosswalk_writer.extract_osm_crossings", lambda _: [])
    monkeypatch.setattr(SETTINGS, "THESIS_STRICT", False)

    stage09._step9_positional_semantics(fake, str(final))

    access_reports = [args[1] for args in report_calls if args and args[0] == "osm_access_restriction_metadata_postfreeze"]
    assert len(access_reports) == 1
    assert access_reports[0]["source_status"] == "SOURCE_FAILURE"
    assert access_reports[0]["osm_access_ways_considered"] == 0
    assert not any(args[:2] == ("success", "osm_access_restriction_postfreeze") for args in report_calls)
    save_xodr.assert_not_called()


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


def test_unresolved_matched_road_fails_before_any_metadata_mutation():
    root = ET.Element("OpenDRIVE")
    root.append(_road("1", "Access Road", 0))
    valid = AccessMatch("w1", "1", {"access": "destination"}, 0.98, "HIGH", 0.1, 1.0)
    missing = AccessMatch("w2", "missing", {"vehicle": "no"}, 0.98, "HIGH", 0.1, 1.0)

    with pytest.raises(ValueError, match="access_metadata_unresolved_xodr_road_ids:missing"):
        attach_access_metadata(root, [valid, missing])

    assert root.findall(f"./road[@id='1']/userData/vector[@key='{USERDATA_KEY}']") == []


def test_all_access_metadata_pipeline_callers_fail_closed():
    """Both materialization stages must propagate an unresolved-road failure."""
    repo_root = Path(__file__).resolve().parents[2]
    for relative_path in (
        "ultimate_pipeline/pipeline_stages/stage_04_enrichment.py",
        "ultimate_pipeline/pipeline_stages/stage_09_positional_semantics.py",
    ):
        source = (repo_root / relative_path).read_text(encoding="utf-8")
        assert "access metadata" in source.lower()
        assert "failed closed" in source
        assert "raise RuntimeError" in source
