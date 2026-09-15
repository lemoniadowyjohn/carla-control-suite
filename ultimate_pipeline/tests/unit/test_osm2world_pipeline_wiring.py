"""Contract tests for the opt-in pipeline OSM2World stage."""

from __future__ import annotations

import json
import inspect
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from ultimate_pipeline.main_pipeline import MainPipeline, _resolve_osm2world_input_path
from ultimate_pipeline.pipeline_stages import stage_04_enrichment


class _Report:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def add_dict(self, name: str, payload: dict) -> None:
        self.records[name] = payload


class _RunnerResult:
    def __init__(self, status: str, *, outputs: dict[str, str] | None = None) -> None:
        self.status = status
        self.outputs = outputs or {}

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": f"runner-{self.status}",
            "outputs": self.outputs,
            "input_osm_hash": "input-hash",
        }


def _valid_obj(path) -> None:
    path.write_text(
        "o valid\n"
        "v 0 0 0\n"
        "v 1 0 0\n"
        "v 0 1 0\n"
        "f 1 2 3\n",
        encoding="utf-8",
    )


def _pipeline(tmp_path, **settings) -> MainPipeline:
    pipeline = MainPipeline.__new__(MainPipeline)
    pipeline.out_dir = str(tmp_path)
    values = {
        "OSM_FILE": str(tmp_path / "source.osm"),
        "ENABLE_OSM2WORLD": False,
        "OSM2WORLD_HOME": "",
        "OSM2WORLD_CONFIG": "",
        "OSM2WORLD_TIMEOUT_SEC": 12,
    }
    values.update(settings)
    pipeline.settings = SimpleNamespace(**values)
    pipeline.vreport = _Report()
    return pipeline


def test_stage_04_defers_visual_generation_until_structural_freeze() -> None:
    source = inspect.getsource(stage_04_enrichment._step4_enrichment)

    assert "post_structural_freeze_authority" in source
    assert "OSM2WorldRunner(" not in source


def test_osm2world_stage_is_not_run_without_explicit_opt_in(tmp_path, monkeypatch) -> None:
    final_xodr = tmp_path / "final.xodr"
    final_xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    monkeypatch.delenv("UP_ENABLE_OSM2WORLD", raising=False)
    monkeypatch.delenv("ENABLE_OSM2WORLD", raising=False)
    pipeline = _pipeline(tmp_path)

    result = pipeline._run_osm2world_visual_stage(str(final_xodr))

    assert result["status"] == "NOT_RUN"
    assert result["road_authority"] == "OpenDRIVE"
    assert pipeline.vreport.records["osm2world_visual"]["status"] == "NOT_RUN"


def test_osm2world_stage_records_external_block_without_failing_pipeline(tmp_path, monkeypatch) -> None:
    final_xodr = tmp_path / "final.xodr"
    final_xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    monkeypatch.setenv("UP_ENABLE_OSM2WORLD", "1")
    calls: list[dict] = []

    class _Runner:
        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

        def run(self) -> _RunnerResult:
            return _RunnerResult("skipped")

    monkeypatch.setattr("ultimate_pipeline.main_pipeline.OSM2WorldRunner", _Runner)
    pipeline = _pipeline(tmp_path, OSM2WORLD_HOME="C:/configured/osm2world")

    result = pipeline._run_osm2world_visual_stage(str(final_xodr))

    assert result["status"] == "BLOCKED_EXTERNAL"
    assert calls[0]["osm2world_home"] == "C:/configured/osm2world"
    receipt = json.loads((tmp_path / "osm2world_pipeline_stage.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "BLOCKED_EXTERNAL"


def test_osm2world_stage_honors_explicit_settings_opt_in(tmp_path, monkeypatch) -> None:
    final_xodr = tmp_path / "final.xodr"
    final_xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    monkeypatch.delenv("UP_ENABLE_OSM2WORLD", raising=False)
    monkeypatch.delenv("ENABLE_OSM2WORLD", raising=False)
    calls: list[dict] = []

    class _Runner:
        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

        def run(self) -> _RunnerResult:
            return _RunnerResult("skipped")

    monkeypatch.setattr("ultimate_pipeline.main_pipeline.OSM2WorldRunner", _Runner)
    pipeline = _pipeline(tmp_path, ENABLE_OSM2WORLD=True)

    result = pipeline._run_osm2world_visual_stage(str(final_xodr))

    assert result["status"] == "BLOCKED_EXTERNAL"
    assert result["enabled"] is True
    assert len(calls) == 1


def test_osm2world_stage_fails_loudly_after_writing_receipt(tmp_path, monkeypatch) -> None:
    final_xodr = tmp_path / "final.xodr"
    final_xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    monkeypatch.setenv("UP_ENABLE_OSM2WORLD", "true")

    class _Runner:
        def __init__(self, **kwargs) -> None:
            pass

        def run(self) -> _RunnerResult:
            return _RunnerResult("failed")

    monkeypatch.setattr("ultimate_pipeline.main_pipeline.OSM2WorldRunner", _Runner)
    pipeline = _pipeline(tmp_path)

    with pytest.raises(RuntimeError, match="OSM2World visual stage did not satisfy"):
        pipeline._run_osm2world_visual_stage(str(final_xodr))

    receipt = json.loads((tmp_path / "osm2world_pipeline_stage.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"


def test_osm2world_stage_records_success_without_mutating_xodr(tmp_path, monkeypatch) -> None:
    final_xodr = tmp_path / "final.xodr"
    final_xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    original_bytes = final_xodr.read_bytes()
    obj_path = tmp_path / "supplemental_scene.obj"
    _valid_obj(obj_path)
    monkeypatch.setenv("ENABLE_OSM2WORLD", "yes")

    class _Runner:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def run(self) -> _RunnerResult:
            return _RunnerResult("ok", outputs={"scene.obj": str(obj_path)})

    monkeypatch.setattr("ultimate_pipeline.main_pipeline.OSM2WorldRunner", _Runner)
    pipeline = _pipeline(tmp_path)

    result = pipeline._run_osm2world_visual_stage(str(final_xodr))

    assert result["status"] == "PASS"
    assert result["runner_status"] == "ok"
    assert result["j1_validation"]["status"] == "PASS"
    assert obj_path.with_name(f"{obj_path.name}.provenance.json").is_file()
    assert final_xodr.read_bytes() == original_bytes


def test_osm2world_stage_rejects_renderer_output_that_fails_j1(tmp_path, monkeypatch) -> None:
    final_xodr = tmp_path / "final.xodr"
    final_xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    obj_path = tmp_path / "duplicate.obj"
    _valid_obj(obj_path)
    with obj_path.open("a", encoding="utf-8") as handle:
        handle.write("o valid\nf 1 2 3\n")
    monkeypatch.setenv("UP_ENABLE_OSM2WORLD", "1")

    class _Runner:
        def __init__(self, **kwargs) -> None:
            pass

        def run(self) -> _RunnerResult:
            return _RunnerResult("ok", outputs={"scene.obj": str(obj_path)})

    monkeypatch.setattr("ultimate_pipeline.main_pipeline.OSM2WorldRunner", _Runner)
    pipeline = _pipeline(tmp_path)

    with pytest.raises(RuntimeError, match="did not satisfy"):
        pipeline._run_osm2world_visual_stage(str(final_xodr))

    receipt = json.loads((tmp_path / "osm2world_pipeline_stage.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"
    assert receipt["runner_status"] == "ok"
    assert receipt["stage_reason"] == "J1 output validation did not satisfy the visual contract"
    assert receipt["j1_validation"]["failed_outputs"] == ["scene.obj"]


# ---------------------------------------------------------------------------
# _resolve_osm2world_input_path (2026-09-15: real-buildings merge wiring)
# ---------------------------------------------------------------------------


def _write_roads_osm(path) -> None:
    root = ET.Element("osm", {"version": "0.6", "generator": "test"})
    ET.SubElement(root, "node", {"id": "1", "lat": "48.70", "lon": "11.40"})
    ET.SubElement(root, "node", {"id": "2", "lat": "48.701", "lon": "11.40"})
    way = ET.SubElement(root, "way", {"id": "10"})
    ET.SubElement(way, "nd", {"ref": "1"})
    ET.SubElement(way, "nd", {"ref": "2"})
    ET.SubElement(way, "tag", {"k": "highway", "v": "residential"})
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def _write_overpass_buildings_json(path) -> None:
    data = {
        "elements": [
            {
                "type": "way",
                "id": 500,
                "tags": {"building": "yes", "height": "9"},
                "geometry": [
                    {"lat": 48.75, "lon": 11.42},
                    {"lat": 48.75, "lon": 11.4205},
                    {"lat": 48.7505, "lon": 11.4205},
                    {"lat": 48.75, "lon": 11.42},
                ],
            }
        ]
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_resolve_input_falls_back_to_roads_only_when_no_buildings_source(tmp_path) -> None:
    roads = tmp_path / "roads.osm"
    _write_roads_osm(roads)
    settings = SimpleNamespace(OSM_FILE=str(roads), PINNED_BUILDINGS_SOURCE="")

    result = _resolve_osm2world_input_path(settings, str(tmp_path / "cache"))

    assert result["source"] == "roads_only"
    assert result["osm_path"] == str(roads)
    assert result["buildings_source"] is None


def test_resolve_input_falls_back_when_buildings_source_missing_on_disk(tmp_path) -> None:
    roads = tmp_path / "roads.osm"
    _write_roads_osm(roads)
    settings = SimpleNamespace(
        OSM_FILE=str(roads),
        PINNED_BUILDINGS_SOURCE=str(tmp_path / "does_not_exist.json"),
    )

    result = _resolve_osm2world_input_path(settings, str(tmp_path / "cache"))

    assert result["source"] == "roads_only"
    assert result["osm_path"] == str(roads)


def test_resolve_input_merges_real_overpass_buildings_into_roads_file(tmp_path) -> None:
    roads = tmp_path / "roads.osm"
    _write_roads_osm(roads)
    buildings = tmp_path / "buildings_overpass.json"
    _write_overpass_buildings_json(buildings)
    settings = SimpleNamespace(OSM_FILE=str(roads), PINNED_BUILDINGS_SOURCE=str(buildings))

    result = _resolve_osm2world_input_path(settings, str(tmp_path / "cache"))

    assert result["source"] == "merged"
    assert result["buildings_source"] == str(buildings)
    assert result["convert_stats"]["ways_written"] == 1
    merged_path = result["osm_path"]
    assert merged_path != str(roads)

    root = ET.parse(merged_path).getroot()
    # Original road way (id=10, highway tag) must survive untouched.
    highway_ways = [w for w in root.findall("way") if any(t.get("k") == "highway" for t in w.findall("tag"))]
    assert len(highway_ways) == 1
    # The converted building way must be present with its tags intact.
    building_ways = [w for w in root.findall("way") if any(t.get("k") == "building" for t in w.findall("tag"))]
    assert len(building_ways) == 1
    building_tags = {t.get("k"): t.get("v") for t in building_ways[0].findall("tag")}
    assert building_tags == {"building": "yes", "height": "9"}


def test_resolve_input_skips_merge_when_buildings_source_already_osm_xml(tmp_path) -> None:
    roads = tmp_path / "roads.osm"
    _write_roads_osm(roads)
    # A buildings source that is already OSM XML (not Overpass JSON) -- the
    # resolver should not attempt to "convert" it and should leave osm_path
    # as roads-only rather than guessing at a merge strategy.
    already_osm = tmp_path / "buildings_already.osm"
    _write_roads_osm(already_osm)
    settings = SimpleNamespace(OSM_FILE=str(roads), PINNED_BUILDINGS_SOURCE=str(already_osm))

    result = _resolve_osm2world_input_path(settings, str(tmp_path / "cache"))

    assert result["source"] == "roads_only"
    assert result["osm_path"] == str(roads)


def test_resolve_input_falls_back_on_conversion_failure_without_raising(tmp_path) -> None:
    roads = tmp_path / "roads.osm"
    _write_roads_osm(roads)
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not valid json", encoding="utf-8")
    settings = SimpleNamespace(OSM_FILE=str(roads), PINNED_BUILDINGS_SOURCE=str(malformed))

    result = _resolve_osm2world_input_path(settings, str(tmp_path / "cache"))

    assert result["source"] == "roads_only"
    assert result["osm_path"] == str(roads)
    assert "failed" in result["reason"]


def test_osm2world_stage_uses_merged_buildings_when_available(tmp_path, monkeypatch) -> None:
    """End-to-end: _run_osm2world_visual_stage must pass the MERGED osm_path
    (not the bare roads OSM_FILE) to OSM2WorldRunner when a real Overpass
    buildings source is configured, and record the resolution in the stage
    receipt."""
    final_xodr = tmp_path / "final.xodr"
    final_xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    roads = tmp_path / "roads.osm"
    _write_roads_osm(roads)
    buildings = tmp_path / "buildings_overpass.json"
    _write_overpass_buildings_json(buildings)
    monkeypatch.setenv("UP_ENABLE_OSM2WORLD", "1")

    calls: list[dict] = []

    class _Runner:
        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

        def run(self) -> _RunnerResult:
            return _RunnerResult("skipped")

    monkeypatch.setattr("ultimate_pipeline.main_pipeline.OSM2WorldRunner", _Runner)
    pipeline = _pipeline(
        tmp_path,
        OSM_FILE=str(roads),
        PINNED_BUILDINGS_SOURCE=str(buildings),
    )

    result = pipeline._run_osm2world_visual_stage(str(final_xodr))

    assert len(calls) == 1
    used_osm_path = calls[0]["osm_path"]
    assert used_osm_path != str(roads), "must not pass the bare roads-only file when buildings are available"
    assert ET is not None
    root = ET.parse(used_osm_path).getroot()
    building_ways = [w for w in root.findall("way") if any(t.get("k") == "building" for t in w.findall("tag"))]
    assert len(building_ways) == 1

    assert result["osm2world_input_resolution"]["source"] == "merged"
