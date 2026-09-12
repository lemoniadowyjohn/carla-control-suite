"""Contract tests for the opt-in pipeline OSM2World stage."""

from __future__ import annotations

import json
import inspect
from types import SimpleNamespace

import pytest

from ultimate_pipeline.main_pipeline import MainPipeline
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
