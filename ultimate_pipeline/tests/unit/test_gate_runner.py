# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/contracts/gate_runner.py.

Live: CumulativeGateRunner is the strict, tally-all-fail-at-end gate
mechanism wired through main_pipeline.py's _stage_gate/_finalize_gates
(main_pipeline.py:2580-2620). Zero prior test coverage despite being the
one thing that decides whether the pipeline raises on a failed gate.
"""
from __future__ import annotations

import pytest

from ultimate_pipeline.contracts.gate_runner import CumulativeGateRunner, GateRunRecord


def test_run_records_passing_dict_report():
    runner = CumulativeGateRunner()
    rep = runner.run("stage", "gate_a", lambda: {"ok": True})
    assert rep == {"ok": True}
    assert runner.results[0].ok is True


def test_run_records_failing_dict_report():
    runner = CumulativeGateRunner()
    rep = runner.run("stage", "gate_a", lambda: {"ok": False, "issues": [1]})
    assert rep == {"ok": False, "issues": [1]}
    assert runner.results[0].ok is False


def test_run_catches_exception_as_failure():
    def _boom():
        raise ValueError("bad xodr")

    runner = CumulativeGateRunner()
    rep = runner.run("stage", "gate_a", _boom)
    assert rep["ok"] is False
    assert "bad xodr" in rep["error"]
    assert runner.results[0].ok is False


def test_run_treats_non_dict_return_as_failure_not_silent_pass():
    # A gate function is contractually Callable[[], dict]. If it returns
    # None (e.g. a missing `return rep` bug in the gate implementation --
    # see quality_gate_manager.gate_junction_integrity), that must NOT be
    # silently treated as an automatic pass: a gate whose implementation
    # is broken is exactly the case a strict gate runner exists to catch.
    runner = CumulativeGateRunner()
    rep = runner.run("stage", "gate_a", lambda: None)
    assert runner.results[0].ok is False
    assert rep["ok"] is False


def test_finalize_non_strict_summarizes_without_raising():
    runner = CumulativeGateRunner(strict=False)
    runner.run("stage", "gate_a", lambda: {"ok": False})
    summary = runner.finalize()
    assert summary["total"] == 1
    assert summary["failed"] == 1
    assert summary["passed"] == 0


def test_finalize_strict_raises_on_any_failure():
    runner = CumulativeGateRunner(strict=True)
    runner.run("stage", "gate_a", lambda: {"ok": True})
    runner.run("stage", "gate_b", lambda: {"ok": False, "detail": "bad"})
    with pytest.raises(RuntimeError, match="gate_b"):
        runner.finalize()


def test_finalize_strict_does_not_raise_when_all_pass():
    runner = CumulativeGateRunner(strict=True)
    runner.run("stage", "gate_a", lambda: {"ok": True})
    summary = runner.finalize()
    assert summary["failed"] == 0


def test_gate_run_record_is_a_plain_dataclass():
    rec = GateRunRecord(stage="s", gate="g", ok=True, detail={}, elapsed_s=0.1)
    assert rec.stage == "s"
    assert rec.ok is True


# ---------------------------------------------------------------------------
# OC-36: CumulativeGateRunner and QualityGateManager._finalize_gate share a
# single normalization authority (`normalize_gate_result`) and MUST always
# agree on the same report -- including malformed / status-only / empty ones.
# ---------------------------------------------------------------------------

from ultimate_pipeline.core.validation_report import ValidationReport  # noqa: E402
from ultimate_pipeline.quality.quality_gate_manager import QualityGateManager  # noqa: E402


def _runner_verdict(report):
    runner = CumulativeGateRunner()
    returned = runner.run("stage", "gate_x", lambda: report)
    return returned, runner.results[0].ok


def _manager_verdict(report):
    qgate = QualityGateManager(ValidationReport())
    qgate._finalize_gate("gate_x", report)
    return "gate_x" not in qgate.get_failures()


def test_runner_and_manager_agree_on_status_only_skipped_report():
    report = {"status": "skipped", "reason": "disabled"}
    returned, runner_ok = _runner_verdict(report)
    assert runner_ok is False
    assert returned is report  # the report is preserved verbatim
    assert _manager_verdict(report) is False


def test_runner_and_manager_agree_on_empty_dict_report():
    report = {}
    _, runner_ok = _runner_verdict(report)
    assert runner_ok is False
    assert _manager_verdict(report) is False


def test_runner_and_manager_agree_on_missing_ok_key():
    report = {"issues": [], "detail": "no verdict expressed"}
    _, runner_ok = _runner_verdict(report)
    assert runner_ok is False
    assert _manager_verdict(report) is False


def test_runner_normalizes_status_pass_to_ok():
    _, runner_ok = _runner_verdict({"status": "pass"})
    assert runner_ok is True


def test_runner_status_error_is_failed():
    _, runner_ok = _runner_verdict({"status": "error", "error": "boom"})
    assert runner_ok is False


def test_runner_status_pending_is_failed():
    # Example: PENDING must map to INCOMPLETE (fail-closed), never OK.
    _, runner_ok = _runner_verdict({"status": "PENDING"})
    assert runner_ok is False


def test_runner_status_gate_timed_out_is_failed():
    _, runner_ok = _runner_verdict({"status": "GATE_TIMED_OUT"})
    assert runner_ok is False


def test_runner_ok_key_wins_over_conflicting_status():
    # structure_elevation_plausibility carries BOTH ok and status.
    ok_report = {"ok": True, "status": "INCOMPLETE"}
    _, runner_ok = _runner_verdict(ok_report)
    assert runner_ok is True
    assert _manager_verdict(ok_report) is True

    failed_report = {"ok": False, "status": "PASS"}
    _, runner_ok = _runner_verdict(failed_report)
    assert runner_ok is False
    assert _manager_verdict(failed_report) is False


def test_runner_unrecognized_status_is_fail_closed():
    _, runner_ok = _runner_verdict({"status": "some_future_status"})
    assert runner_ok is False


def test_runner_strict_finalize_raises_on_status_only_gap():
    runner = CumulativeGateRunner(strict=True)
    runner.run("stage", "gate_x", lambda: {"status": "skipped"})
    with pytest.raises(RuntimeError, match="gate_x"):
        runner.finalize()
