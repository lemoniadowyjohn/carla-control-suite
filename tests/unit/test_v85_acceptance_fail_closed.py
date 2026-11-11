"""V85 Phase 2: production map acceptance is fail-closed for mandatory gates.

At 31bb6c7a the final acceptance in ``main_pipeline`` recomputed its
"mandatory" gates via ``getattr(QualityGateManager, ...)``. Three of those
methods do not exist, three take a parsed root and return None, all failures
were swallowed as "skipped", and ``elevation_continuity`` was never supplied.
A map with a 6.15 m elevation step at a road join was therefore accepted
(``valid_for_experiments=True``). These tests use the real checker code.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from ultimate_pipeline.quality import final_artifact_gates as fag
from ultimate_pipeline.quality.check_geometric_continuity import check_geometric_continuity
from ultimate_pipeline.quality.check_origin_sanity import check_origin_sanity
from ultimate_pipeline.quality.map_acceptance import build_map_acceptance

STEP_XODR = (
    '<?xml version="1.0" encoding="utf-8"?>'
    "<OpenDRIVE>"
    '<road id="1" length="10.0" junction="-1">'
    '<link><successor elementType="road" elementId="2" contactPoint="start"/></link>'
    '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
    '<elevationProfile><elevation s="0" a="361.85" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
    "</road>"
    '<road id="2" length="10.0" junction="-1">'
    '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
    '<planView><geometry s="0" x="10" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
    '<elevationProfile><elevation s="0" a="368.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
    "</road>"
    "</OpenDRIVE>"
)


def _write(tmp_path: Path, text: str, name: str = "final.xodr") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_every_mandatory_gate_always_yields_a_report(tmp_path):
    reports = fag.compute_final_artifact_reports(_write(tmp_path, STEP_XODR))
    assert set(reports) == set(fag.FINAL_ARTIFACT_MANDATORY_GATES)
    assert all(isinstance(rep, dict) for rep in reports.values())


def test_release_acceptance_rejects_elevation_step_at_road_join(tmp_path):
    """The historical false success: continuity fails but acceptance passed."""
    xodr = _write(tmp_path, STEP_XODR)
    reports = dict(fag.compute_final_artifact_reports(xodr))
    assert reports["elevation_continuity"]["ok"] is False  # ground truth
    reports["origin_sanity"] = check_origin_sanity(xodr)
    reports["geometric_continuity"] = check_geometric_continuity(xodr)
    reports["lane_section_successors"] = {"ok": True}

    acc = build_map_acceptance(
        reports, run_id="v85", final_xodr_path=xodr, out_dir=str(tmp_path),
        mandatory_gates=fag.RELEASE_MANDATORY_GATES,
    )
    assert acc["valid_for_experiments"] is False
    assert "elevation_continuity" in acc["failed_gates"]
    assert acc["mandatory_gate_status"]["elevation_continuity"] == "FAIL"


@pytest.mark.parametrize(
    "report, expected",
    [
        (None, "NOT_RUN"),                                          # missing
        ({"ok": None, "status": "NOT_RUN", "reason": "x"}, "NOT_RUN"),
        ({"ok": None, "status": "BLOCKED_INPUT", "reason": "x"}, "BLOCKED_INPUT"),
        ({"ok": True, "status": "ERROR"}, "NOT_RUN"),               # declared error wins
        ({"ok": None}, "NOT_RUN"),                                  # undecidable
        ({"issues": []}, "NOT_RUN"),                                # no ok key at all
        ({"ok": "true"}, "FAIL"),                                   # non-boolean is not PASS
        ({"ok": 1}, "FAIL"),
        ({"ok": False, "issues": [{"x": 1}]}, "FAIL"),
    ],
)
def test_non_passing_mandatory_reports_are_hard_failures(report, expected):
    reports = {} if report is None else {"elevation_continuity": report}
    acc = build_map_acceptance(reports, run_id="v85", mandatory_gates=("elevation_continuity",))
    assert acc["valid_for_experiments"] is False
    assert acc["mandatory_gate_status"]["elevation_continuity"] == expected
    assert "elevation_continuity" in acc["failed_gates"]


def test_only_exact_true_passes_a_mandatory_gate():
    acc = build_map_acceptance(
        {"elevation_continuity": {"ok": True}}, run_id="v85",
        mandatory_gates=("elevation_continuity",),
    )
    assert acc["valid_for_experiments"] is True
    assert acc["mandatory_gate_status"] == {"elevation_continuity": "PASS"}


def test_gate_exception_becomes_not_run_never_skipped(tmp_path, monkeypatch):
    real_table = fag._gate_table

    def table_with_crashing_gate():
        table = real_table()

        def boom(_p, _r):
            raise RuntimeError("checker crashed")

        table["junction_integrity"] = boom
        return table

    monkeypatch.setattr(fag, "_gate_table", table_with_crashing_gate)
    reports = fag.compute_final_artifact_reports(_write(tmp_path, STEP_XODR))
    assert reports["junction_integrity"]["status"] == "NOT_RUN"
    assert reports["junction_integrity"]["ok"] is None
    acc = build_map_acceptance(reports, run_id="v85", mandatory_gates=("junction_integrity",))
    assert acc["valid_for_experiments"] is False


def test_unparseable_final_artifact_blocks_every_gate(tmp_path):
    reports = fag.compute_final_artifact_reports(_write(tmp_path, "<OpenDRIVE><road", "bad.xodr"))
    assert {rep["status"] for rep in reports.values()} == {"BLOCKED_INPUT"}
    acc = build_map_acceptance(reports, run_id="v85", mandatory_gates=fag.FINAL_ARTIFACT_MANDATORY_GATES)
    assert acc["valid_for_experiments"] is False


def test_legacy_callers_without_mandatory_list_are_unchanged():
    # Opt-in: callers that pass no mandatory list keep the historical behaviour.
    acc = build_map_acceptance({}, run_id="v85")
    assert acc["valid_for_experiments"] is True
    assert acc["mandatory_gate_status"] == {}


def test_production_final_acceptance_uses_fail_closed_wiring():
    """Production call-site reachability: the real release path is wired."""
    from ultimate_pipeline.main_pipeline import MainPipeline

    publish = inspect.getsource(MainPipeline._publish_final_artifact_authority)
    collect = inspect.getsource(MainPipeline._collect_final_acceptance_reports)
    assert "self._collect_final_acceptance_reports(" in publish
    assert "mandatory_gates=RELEASE_MANDATORY_GATES" in publish
    assert "compute_final_artifact_reports(final_out)" in collect
    for src in (publish, collect):
        assert "getattr(self.qgate, gate_method)" not in src
        assert "recompute skipped" not in src
    run_src = inspect.getsource(MainPipeline.run)
    guard = run_src.index("_require_valid_map_acceptance(self.out_dir)")
    assert guard < run_src.index('self._write_run_status(status="ok", stage="done")')
    assert guard < run_src.index("write_success_txt(self.out_dir")


class _StubGate:
    def __init__(self, origin):
        self._origin = origin

    def gate_origin_sanity(self, _path):
        if isinstance(self._origin, Exception):
            raise self._origin
        return self._origin


def _collect(tmp_path, origin):
    from types import SimpleNamespace

    from ultimate_pipeline.main_pipeline import MainPipeline

    stub_self = SimpleNamespace(qgate=_StubGate(origin), out_dir=str(tmp_path))
    return MainPipeline._collect_final_acceptance_reports(
        stub_self, _write(tmp_path, STEP_XODR), seam_report=None
    )


def test_real_assembly_supplies_every_release_mandatory_gate(tmp_path):
    """Behavioural: the real production assembly method, minimal stub self."""
    reports = _collect(tmp_path, {"ok": True})
    missing = [g for g in fag.RELEASE_MANDATORY_GATES if not isinstance(reports.get(g), dict)]
    assert missing == []
    assert reports["elevation_continuity"]["ok"] is False
    acc = build_map_acceptance(reports, run_id="v85", mandatory_gates=fag.RELEASE_MANDATORY_GATES)
    assert acc["valid_for_experiments"] is False
    assert "elevation_continuity" in acc["failed_gates"]


@pytest.mark.parametrize("origin", [RuntimeError("probe failed"), None])
def test_origin_sanity_recompute_failure_is_not_run_not_stale_fallback(tmp_path, origin):
    reports = _collect(tmp_path, origin)
    assert reports["origin_sanity"]["status"] == "NOT_RUN"
    acc = build_map_acceptance(reports, run_id="v85", mandatory_gates=("origin_sanity",))
    assert acc["mandatory_gate_status"]["origin_sanity"] == "NOT_RUN"
    assert acc["valid_for_experiments"] is False


def test_lane_connectivity_is_mandatory_and_computed(tmp_path):
    assert "lane_connectivity" in fag.RELEASE_MANDATORY_GATES
    reports = fag.compute_final_artifact_reports(_write(tmp_path, STEP_XODR))
    assert isinstance(reports["lane_connectivity"], dict)
    acc = build_map_acceptance({}, run_id="v85", mandatory_gates=("lane_connectivity",))
    assert acc["mandatory_gate_status"]["lane_connectivity"] == "NOT_RUN"


@pytest.mark.parametrize(
    "payload",
    [None, "not json", {"valid_for_experiments": False, "failed_gates": ["elevation_continuity"]},
     {"valid_for_experiments": "true"}, {}],
)
def test_success_requires_valid_durable_map_acceptance(tmp_path, payload):
    import json as _json

    from ultimate_pipeline.main_pipeline import _require_valid_map_acceptance

    if payload is not None:
        text = payload if isinstance(payload, str) else _json.dumps(payload)
        (tmp_path / "map_acceptance.json").write_text(text, encoding="utf-8")
    with pytest.raises(RuntimeError, match="TERMINAL_FAILED\\(MAP_ACCEPTANCE\\)"):
        _require_valid_map_acceptance(tmp_path)


def test_success_allowed_when_map_acceptance_valid(tmp_path):
    import json as _json

    from ultimate_pipeline.main_pipeline import _require_valid_map_acceptance

    (tmp_path / "map_acceptance.json").write_text(
        _json.dumps({"valid_for_experiments": True}), encoding="utf-8"
    )
    _require_valid_map_acceptance(tmp_path)  # does not raise


def test_e2_acceptance_requires_elevation_continuity():
    from ultimate_pipeline.tools.e2_map_quality_repair import _acceptance

    counts = {"roads": 2, "junctions": 0, "signals": 0, "objects": 0, "crosswalk_objects": 0,
              "nonzero_elevation_segments": 500000}
    qa_ok = {"strict_elev_jump_count": 0, "seams": {"ok": True}, "missing_and_cliffs": {"ok": True},
             "structure": {"ok": True}, "continuity": {"ok": True, "num_issues": 0}}
    qa_bad = dict(qa_ok, continuity={"ok": False, "num_issues": 574})
    common = dict(before_counts=counts, after_counts=counts, before_g19={"violations": 0},
                  after_g19={"violations": 0}, before_qa=qa_ok,
                  preflight_after={"available": True, "summary": {"error_count": 0}})
    assert _acceptance(after_qa=qa_ok, **common)["pass"] is True
    result = _acceptance(after_qa=qa_bad, **common)
    assert result["pass"] is False
    assert result["checks"]["elevation_continuity_ok"] is False


def test_run_does_not_publish_success_when_map_acceptance_invalid(tmp_path, monkeypatch):
    """Behavioural, real MainPipeline.run(): an invalid final acceptance blocks SUCCESS.

    Mirrors tests/adversarial/test_terminal_authority.py::TestMainPipelineRunTerminalChain
    with only the acceptance outcome changed.
    """
    import json as _json

    from ultimate_pipeline.main_pipeline import MainPipeline
    from ultimate_pipeline.quality import pipeline_health_summary as phs_module
    from ultimate_pipeline.signals import registry as registry_module
    from ultimate_pipeline.signals import verdict as verdict_module
    from ultimate_pipeline.utils import finalize_run_pack as frp_module

    class MockSettings:
        def output_dir(self): return str(tmp_path)
        def logs_dir(self): return str(tmp_path / "logs")
        RELEASE_PROFILE = "structural_release"
        ENABLE_CARLA = False
        DETERMINISTIC_MODE = False
        KEEP_LAST_RUNS = 10
        INPUT_XODR = str(tmp_path / "input.xodr")
        OSM_FILE = str(tmp_path / "input.osm")
        DEM_TIF = str(tmp_path / "dem.tif")
        GPS_BOUNDS = {"lat_min": 0, "lat_max": 1, "lon_min": 0, "lon_max": 1}
        BASE_OUTPUT_DIR = str(tmp_path)
        LOG_DIR = str(tmp_path / "logs")
        STAGE_DIRS = {}
        def stage_path(self, name): return str(tmp_path / f"{name}.xodr")
        def load_gps_bounds(self): return self.GPS_BOUNDS
        def to_dict(self): return {}

    (tmp_path / "input.xodr").write_text("<?xml version='1.0'?><OpenDRIVE/>", encoding="utf-8")
    (tmp_path / "input.osm").write_text("<osm/>", encoding="utf-8")
    (tmp_path / "dem.tif").write_text("dummy", encoding="utf-8")
    (tmp_path / "logs").mkdir(exist_ok=True)
    pipeline = MainPipeline(settings=MockSettings())

    def run_internal_with_failing_acceptance():
        (tmp_path / "final.xodr").write_text("<OpenDRIVE/>", encoding="utf-8")
        (tmp_path / "map_acceptance.json").write_text(_json.dumps(
            {"valid_for_experiments": False, "failed_gates": ["elevation_continuity"]}
        ), encoding="utf-8")

    pipeline._run_internal = run_internal_with_failing_acceptance
    pipeline._find_final_xodr = lambda: str(tmp_path / "final.xodr")
    monkeypatch.setattr(phs_module, "write_pipeline_health_summary", lambda out_dir, **_k: (
        Path(out_dir) / "pipeline_health_summary.json").write_text(
            _json.dumps({"schema": "pipeline_health_summary/v1", "overall_ok": True, "gates": {}}),
            encoding="utf-8"))

    def fake_verdict(out_dir, **_k):
        (Path(out_dir) / "final_run_verdict.json").write_text(
            _json.dumps({"schema": "final_run_verdict/v1", "status": "PASS"}), encoding="utf-8")
        return {"status": "PASS"}

    monkeypatch.setattr(verdict_module, "write_final_run_verdict", fake_verdict)
    monkeypatch.setattr(registry_module, "mandatory_pack_artifacts", lambda profile, final_xodr, settings=None: [
        final_xodr, str(tmp_path / "pipeline_health_summary.json")])
    success_calls = []
    real_success = frp_module.write_success_txt
    monkeypatch.setattr(frp_module, "write_success_txt",
                        lambda *a, **k: (success_calls.append(1), real_success(*a, **k)))
    statuses = []
    real_status = pipeline._write_run_status
    pipeline._write_run_status = lambda status, stage, message=None, error=None: (
        statuses.append(status), real_status(status=status, stage=stage, message=message, error=error))

    with pytest.raises(Exception, match="MAP_ACCEPTANCE"):
        pipeline.run()
    assert success_calls == []
    assert not (tmp_path / "SUCCESS.txt").exists()
    assert "ok" not in statuses
