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

    src = inspect.getsource(MainPipeline._publish_final_artifact_authority)
    assert "compute_final_artifact_reports(final_out)" in src
    assert "mandatory_gates=RELEASE_MANDATORY_GATES" in src
    assert "getattr(self.qgate, gate_method)" not in src
    assert "{gate_key} recompute skipped" not in src  # the removed swallow-all loop
    assert "geometric_continuity recompute skipped" not in src
    assert "lane_section_successors recompute skipped" not in src


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
