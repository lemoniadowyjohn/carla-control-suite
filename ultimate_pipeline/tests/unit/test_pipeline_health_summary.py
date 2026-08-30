# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/quality/pipeline_health_summary.py.

Live: build_pipeline_health_summary/write_pipeline_health_summary imported
by main_pipeline.py (line 1544) -- the final pipeline health/dashboard
report, aggregating every stage's gate JSON. Zero prior test coverage.
"""
from __future__ import annotations

import json
import os

from ultimate_pipeline.quality.pipeline_health_summary import (
    _extract_bbox,
    _extract_issue_counts,
    _merge_gate_entry,
    _parse_stage_gate,
    _report_status,
    build_pipeline_health_summary,
    write_pipeline_health_summary,
)


# ---------------------------------------------------------------------------
# _report_status
# ---------------------------------------------------------------------------

def test_report_status_uses_ok_field_when_present():
    assert _report_status({"ok": True}) == (True, "pass")
    assert _report_status({"ok": False}) == (False, "fail")


def test_report_status_falls_back_to_status_string():
    assert _report_status({"status": "FAILED"}) == (False, "failed")
    assert _report_status({"status": "skipped"}) == (True, "skipped")


def test_report_status_falls_back_to_n_errors_count():
    assert _report_status({"n_errors": 3}) == (False, "fail")
    assert _report_status({"n_errors": 0}) == (True, "pass")


def test_report_status_defaults_to_pass_for_empty_dict():
    assert _report_status({}) == (True, "pass")


def test_report_status_non_dict_input_treated_as_unknown_ok():
    assert _report_status("not a dict") == (True, "unknown")


# ---------------------------------------------------------------------------
# _extract_issue_counts
# ---------------------------------------------------------------------------

def test_extract_issue_counts_uses_list_lengths():
    counts = _extract_issue_counts({"issues": [1, 2, 3], "warnings": ["a"]})
    assert counts["issues"] == 3
    assert counts["warnings"] == 1


def test_extract_issue_counts_forces_at_least_one_error_when_failed():
    # A failing report with no explicit error/issue counts must still show
    # at least 1 error -- otherwise a genuine failure could render as
    # "0 issues, 0 errors" in the aggregated dashboard.
    counts = _extract_issue_counts({"ok": False})
    assert counts["errors"] >= 1
    assert counts["issues"] >= 1


# ---------------------------------------------------------------------------
# _merge_gate_entry
# ---------------------------------------------------------------------------

def test_merge_gate_entry_creates_new_entry():
    gates = {}
    _merge_gate_entry(gates, "my_gate", {"ok": True}, "stage:07")
    assert gates["my_gate"]["ok"] is True
    assert gates["my_gate"]["sources"] == ["stage:07"]


def test_merge_gate_entry_combines_pass_and_fail_as_overall_fail():
    gates = {}
    _merge_gate_entry(gates, "my_gate", {"ok": True}, "stage:07")
    _merge_gate_entry(gates, "my_gate", {"ok": False}, "stage:09")
    assert gates["my_gate"]["ok"] is False
    assert set(gates["my_gate"]["sources"]) == {"stage:07", "stage:09"}


# ---------------------------------------------------------------------------
# _parse_stage_gate
# ---------------------------------------------------------------------------

def test_parse_stage_gate_splits_on_double_underscore():
    assert _parse_stage_gate("stage07__geometric_continuity.json") == ("stage07", "geometric_continuity")


def test_parse_stage_gate_without_separator_is_unknown_stage():
    assert _parse_stage_gate("geometric_continuity.json") == ("unknown", "geometric_continuity")


# ---------------------------------------------------------------------------
# _extract_bbox
# ---------------------------------------------------------------------------

def test_extract_bbox_finds_complete_bbox():
    data = {"gps_bounds_wgs84": {"lat_min": 1, "lat_max": 2, "lon_min": 3, "lon_max": 4}}
    assert _extract_bbox(data) == {"lat_min": 1, "lat_max": 2, "lon_min": 3, "lon_max": 4}


def test_extract_bbox_rejects_incomplete_bbox():
    data = {"bbox": {"lat_min": 1, "lat_max": 2}}  # missing lon_min/lon_max
    assert _extract_bbox(data) is None


# ---------------------------------------------------------------------------
# build_pipeline_health_summary -- integration
# ---------------------------------------------------------------------------

def test_all_passing_gates_report_overall_ok_true(tmp_path):
    stage_dir = tmp_path / "qa_stage_reports"
    stage_dir.mkdir()
    (stage_dir / "stage07__gate_a.json").write_text(json.dumps({"ok": True}))
    (stage_dir / "stage09__gate_b.json").write_text(json.dumps({"ok": True}))
    summary = build_pipeline_health_summary(str(tmp_path))
    assert summary["overall_ok"] is True
    assert set(summary["gates"].keys()) == {"gate_a", "gate_b"}


def test_one_failing_gate_flips_overall_ok_false(tmp_path):
    stage_dir = tmp_path / "qa_stage_reports"
    stage_dir.mkdir()
    (stage_dir / "stage07__gate_a.json").write_text(json.dumps({"ok": True}))
    (stage_dir / "stage09__gate_b.json").write_text(json.dumps({"ok": False}))
    summary = build_pipeline_health_summary(str(tmp_path))
    assert summary["overall_ok"] is False
    assert summary["per_stage_failures"]["stage09"] == ["gate_b"]


def test_malformed_gate_report_is_flagged_not_silently_dropped(tmp_path):
    # A gate JSON that exists (the stage attempted to write it) but is
    # unparseable -- e.g. a stage that crashed mid-write -- must not be
    # silently indistinguishable from "this gate never applied to this run".
    stage_dir = tmp_path / "qa_stage_reports"
    stage_dir.mkdir()
    (stage_dir / "stage07__gate_a.json").write_text(json.dumps({"ok": True}))
    (stage_dir / "stage08__gate_crashed.json").write_text("{not valid json")
    summary = build_pipeline_health_summary(str(tmp_path))
    assert summary["overall_ok"] is False
    assert "stage08/gate_crashed" in summary["malformed_gate_reports"]


def test_missing_optional_artifact_files_are_not_flagged_as_malformed(tmp_path):
    # Fixed-name artifact files (e.g. dem_coverage.json) legitimately don't
    # exist for every run -- this must stay silent, unlike a stage report
    # that DOES exist on disk but fails to parse.
    stage_dir = tmp_path / "qa_stage_reports"
    stage_dir.mkdir()
    (stage_dir / "stage07__gate_a.json").write_text(json.dumps({"ok": True}))
    summary = build_pipeline_health_summary(str(tmp_path))
    assert summary["overall_ok"] is True
    assert summary["malformed_gate_reports"] == []


def test_write_pipeline_health_summary_writes_valid_json_file(tmp_path):
    stage_dir = tmp_path / "qa_stage_reports"
    stage_dir.mkdir()
    (stage_dir / "stage07__gate_a.json").write_text(json.dumps({"ok": True}))
    out_path = write_pipeline_health_summary(str(tmp_path))
    assert os.path.isfile(out_path)
    written = json.loads(open(out_path).read())
    assert written["overall_ok"] is True


def test_missing_stage_reports_dir_does_not_crash(tmp_path):
    # No qa_stage_reports/ directory at all -- must not raise.
    summary = build_pipeline_health_summary(str(tmp_path))
    assert summary["overall_ok"] is True
    assert summary["gates"] == {}
