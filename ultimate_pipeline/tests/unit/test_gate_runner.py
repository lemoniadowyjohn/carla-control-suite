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
