"""ultimate_pipeline/tools/final_map_readiness_gate.py -- "intentionally CARLA-free" per its
own docstring, and the gate that directly sets CARLA_VISUAL_READY / PERCEPTION_EVIDENCE_ALLOWED
/ PERCEPTION_READY -- the exact readiness signal RQ2/RQ3's capture pipeline depends on. Had
zero test coverage on this branch (found while sweeping orphaned .pyc files with no matching
.py source alongside carla_visual_smoke_gate.py and run_perception_safe.py).
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.tools.final_map_readiness_gate import (
    evaluate_connector_report,
    evaluate_visual_gate_report,
    evaluate_perception_status,
    _signal_object_counts,
    build_final_map_readiness_report,
)


def _write_xodr(path: Path, *, signals=0, traffic_light_objects=0, stop_objects=0) -> None:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
    signals_el = ET.SubElement(road, "signals")
    for i in range(signals):
        ET.SubElement(signals_el, "signal", id=str(i), s="0", t="0")
    objects_el = ET.SubElement(road, "objects")
    for i in range(traffic_light_objects):
        ET.SubElement(objects_el, "object", id=f"tl{i}", type="traffic_light")
    for i in range(stop_objects):
        ET.SubElement(objects_el, "object", id=f"stop{i}", type="stop")
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# evaluate_connector_report
# ---------------------------------------------------------------------------

def test_connector_report_missing_fails_closed():
    result = evaluate_connector_report(None, xodr_path=Path("nonexistent.xodr"))
    assert result["ok"] is False
    assert result["status"] == "missing"
    assert result["reason"] == "connector_report_missing"


def test_connector_report_all_thresholds_pass(tmp_path: Path):
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    report = {
        "connector_start_mismatch_before": 50, "connector_start_mismatch_after": 5,
        "connector_end_mismatch_before": 60, "connector_end_mismatch_after": 10,
        "connectors_lt_1m_before": 3, "connectors_lt_1m_after": 3,
        "fix_effective": True,
    }
    result = evaluate_connector_report(report, xodr_path=xodr)
    assert result["ok"] is True
    assert result["status"] == "pass"
    assert result["reason"] == ""


def test_connector_report_start_mismatch_over_threshold_fails(tmp_path: Path):
    report = {"connector_start_mismatch_after": 100, "connector_end_mismatch_after": 10,
              "connector_start_mismatch_before": 200}
    result = evaluate_connector_report(report, xodr_path=tmp_path / "x.xodr", max_start_mismatch=100)
    assert result["ok"] is False
    assert "start_mismatch_after_ge_100" in result["reason"]


def test_connector_report_end_mismatch_over_threshold_fails(tmp_path: Path):
    report = {"connector_start_mismatch_after": 5, "connector_end_mismatch_after": 200}
    result = evaluate_connector_report(report, xodr_path=tmp_path / "x.xodr", max_end_mismatch=200)
    assert result["ok"] is False
    assert "end_mismatch_after_ge_200" in result["reason"]


def test_connector_report_missing_after_metrics_fails():
    # A non-empty dict lacking the metric keys -- {} itself is falsy and would hit the
    # "report missing entirely" branch instead of the "present but incomplete" branch
    # this test targets.
    result = evaluate_connector_report({"note": "no metrics recorded"}, xodr_path=Path("x.xodr"))
    assert result["ok"] is False
    assert "start_mismatch_after_missing" in result["reason"]
    assert "end_mismatch_after_missing" in result["reason"]


def test_connector_report_lt1m_regression_fails():
    report = {
        "connector_start_mismatch_after": 5, "connector_end_mismatch_after": 10,
        "connectors_lt_1m_before": 2, "connectors_lt_1m_after": 5,
    }
    result = evaluate_connector_report(report, xodr_path=Path("x.xodr"))
    assert result["ok"] is False
    assert "lt_1m_connectors_increased" in result["reason"]


def test_connector_report_fix_effective_false_fails():
    report = {"connector_start_mismatch_after": 5, "connector_end_mismatch_after": 10,
              "fix_effective": False}
    result = evaluate_connector_report(report, xodr_path=Path("x.xodr"))
    assert result["ok"] is False
    assert "fix_effective_false" in result["reason"]


def test_connector_report_start_not_improved_fails():
    report = {"connector_start_mismatch_before": 5, "connector_start_mismatch_after": 5,
              "connector_end_mismatch_after": 10}
    result = evaluate_connector_report(report, xodr_path=Path("x.xodr"))
    assert result["ok"] is False
    assert "start_mismatch_not_improved" in result["reason"]


def test_connector_report_sha_mismatch_detected(tmp_path: Path):
    xodr = tmp_path / "final.xodr"
    xodr.write_bytes(b"real content")
    wrong_sha = hashlib.sha256(b"different content").hexdigest()
    report = {"connector_start_mismatch_after": 5, "connector_end_mismatch_after": 10,
              "output_sha256": wrong_sha}
    result = evaluate_connector_report(report, xodr_path=xodr)
    assert result["ok"] is False
    assert "output_sha256_mismatch" in result["reason"]
    assert result["sha_issue"] == "output_sha256_mismatch"


def test_connector_report_sha_match_does_not_fail(tmp_path: Path):
    xodr = tmp_path / "final.xodr"
    xodr.write_bytes(b"real content")
    correct_sha = hashlib.sha256(b"real content").hexdigest()
    report = {"connector_start_mismatch_after": 5, "connector_end_mismatch_after": 10,
              "output_sha256": correct_sha}
    result = evaluate_connector_report(report, xodr_path=xodr)
    assert result["ok"] is True
    assert result["sha_issue"] == ""


def test_connector_report_explicit_ok_false_ignored_when_thresholds_present():
    # "Risk reports may be stricter than this final threshold gate" -- an explicit ok=False
    # must NOT fail the gate on its own when the actual threshold metrics are fine.
    report = {"connector_start_mismatch_after": 5, "connector_end_mismatch_after": 10, "ok": False}
    result = evaluate_connector_report(report, xodr_path=Path("x.xodr"))
    assert result["ok"] is True


def test_connector_report_explicit_ok_false_fails_when_no_thresholds_available():
    report = {"ok": False}
    result = evaluate_connector_report(report, xodr_path=Path("x.xodr"))
    assert result["ok"] is False
    assert "connector_report_explicit_ok_false" in result["reason"]


def test_connector_report_accepts_alternate_key_names():
    # _first_int checks multiple historical key-name variants for the same metric.
    report = {"start_gap_over_threshold_after": 5, "end_gap_over_tolerance_after": 10}
    result = evaluate_connector_report(report, xodr_path=Path("x.xodr"))
    assert result["ok"] is True
    assert result["start_mismatch_after"] == 5
    assert result["end_mismatch_after"] == 10


# ---------------------------------------------------------------------------
# evaluate_visual_gate_report
# ---------------------------------------------------------------------------

def test_visual_gate_report_missing_fails_closed():
    result = evaluate_visual_gate_report(None)
    assert result["ok"] is False
    assert result["status"] == "missing"


def test_visual_gate_report_all_views_pass():
    report = {
        "ok": True, "load_ok": True,
        "screenshots": {
            "top_down": {"ok": True, "path": "a.png"},
            "street": {"ok": True, "path": "b.png"},
            "junction": {"ok": True, "path": "c.png"},
        },
    }
    result = evaluate_visual_gate_report(report)
    assert result["ok"] is True
    assert result["CARLA_VISUAL_READY"] == "yes"
    assert result["PERCEPTION_EVIDENCE_ALLOWED"] is True


def test_visual_gate_report_missing_view_fails():
    report = {"ok": True, "load_ok": True, "screenshots": {"top_down": {"ok": True}}}
    result = evaluate_visual_gate_report(report)
    assert result["ok"] is False
    assert "street" in result["missing_views"]
    assert "junction" in result["missing_views"]


# ---------------------------------------------------------------------------
# evaluate_perception_status
# ---------------------------------------------------------------------------

def test_perception_status_blocked_when_visual_not_ok():
    result = evaluate_perception_status({"ok": True, "frames_recorded": 10}, visual_ok=False)
    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["reason"] == "blocked_until_carla_visual_smoke_gate_passes"


def test_perception_status_missing_report_fails():
    result = evaluate_perception_status(None, visual_ok=True)
    assert result["ok"] is False
    assert result["status"] == "missing"


def test_perception_status_enough_frames_passes():
    result = evaluate_perception_status({"ok": True, "frames_recorded": 5}, visual_ok=True, min_frames=1)
    assert result["ok"] is True
    assert result["frames_recorded"] == 5


def test_perception_status_too_few_frames_fails():
    result = evaluate_perception_status({"ok": True, "frames_recorded": 0}, visual_ok=True, min_frames=1)
    assert result["ok"] is False
    assert "frames_recorded_lt_1" in result["reason"]


def test_perception_status_not_ok_uses_failure_reason():
    result = evaluate_perception_status(
        {"ok": False, "failure_reason": "streaming_timeout"}, visual_ok=True
    )
    assert result["ok"] is False
    assert result["reason"] == "streaming_timeout"


# ---------------------------------------------------------------------------
# _signal_object_counts
# ---------------------------------------------------------------------------

def test_signal_object_counts_real_map(tmp_path: Path):
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, signals=3, traffic_light_objects=2, stop_objects=1)
    counts = _signal_object_counts(xodr)
    assert counts["signals_total"] == 3
    assert counts["objects_total"] == 3
    assert counts["traffic_light_objects"] == 2
    assert counts["traffic_sign_objects"] == 1
    assert counts["parse_error"] == ""


def test_signal_object_counts_empty_map_zero(tmp_path: Path):
    xodr = tmp_path / "empty.xodr"
    _write_xodr(xodr)
    counts = _signal_object_counts(xodr)
    assert counts["signals_total"] == 0
    assert counts["objects_total"] == 0


def test_signal_object_counts_malformed_xml_reports_parse_error(tmp_path: Path):
    xodr = tmp_path / "bad.xodr"
    xodr.write_text("<OpenDRIVE><unclosed", encoding="utf-8")
    counts = _signal_object_counts(xodr)
    assert counts["parse_error"] != ""


# ---------------------------------------------------------------------------
# build_final_map_readiness_report -- integration
# ---------------------------------------------------------------------------

def test_build_report_happy_path_all_gates_pass(tmp_path: Path):
    xodr = tmp_path / "final.xodr"
    _write_xodr(xodr, signals=1, traffic_light_objects=1)

    connector_report_path = tmp_path / "final_rebuild_report.json"
    connector_report_path.write_text(json.dumps({
        "connector_start_mismatch_after": 5, "connector_end_mismatch_after": 10,
    }), encoding="utf-8")

    visual_report_path = tmp_path / "carla_visual_smoke_gate.json"
    visual_report_path.write_text(json.dumps({
        "ok": True, "load_ok": True,
        "screenshots": {
            "top_down": {"ok": True}, "street": {"ok": True}, "junction": {"ok": True},
        },
    }), encoding="utf-8")

    report = build_final_map_readiness_report(
        xodr_path=xodr,
        connector_report_path=connector_report_path,
        visual_gate_report_path=visual_report_path,
        require_signals=True,
    )
    assert report["ok"] is True
    assert report["CARLA_VISUAL_READY"] == "yes"
    assert report["STRUCTURAL_ANALYSIS_READY"] == "yes"
    assert report["signal_gate"]["ok"] is True
    assert Path(report["report_path"]).is_file()  # actually written to disk


def test_build_report_missing_visual_gate_fails_overall_by_default(tmp_path: Path):
    xodr = tmp_path / "final.xodr"
    _write_xodr(xodr)
    report = build_final_map_readiness_report(xodr_path=xodr)
    assert report["ok"] is False
    assert report["CARLA_VISUAL_READY"] == "no"


def test_build_report_missing_visual_gate_can_be_allowed(tmp_path: Path):
    xodr = tmp_path / "final.xodr"
    _write_xodr(xodr)
    connector_report_path = tmp_path / "rebuild_report.json"
    connector_report_path.write_text(json.dumps({
        "connector_start_mismatch_after": 5, "connector_end_mismatch_after": 10,
    }), encoding="utf-8")
    report = build_final_map_readiness_report(
        xodr_path=xodr, connector_report_path=connector_report_path, require_visual=False,
    )
    assert report["ok"] is True  # structural passes, visual not required


def test_build_report_require_signals_fails_when_absent(tmp_path: Path):
    xodr = tmp_path / "final.xodr"
    _write_xodr(xodr)  # zero signals/objects
    connector_report_path = tmp_path / "rebuild_report.json"
    connector_report_path.write_text(json.dumps({
        "connector_start_mismatch_after": 5, "connector_end_mismatch_after": 10,
    }), encoding="utf-8")
    report = build_final_map_readiness_report(
        xodr_path=xodr, connector_report_path=connector_report_path,
        require_visual=False, require_signals=True,
    )
    assert report["ok"] is False
    assert report["signal_gate"]["ok"] is False


def test_build_report_perception_blocked_without_visual(tmp_path: Path):
    xodr = tmp_path / "final.xodr"
    _write_xodr(xodr)
    report = build_final_map_readiness_report(xodr_path=xodr, require_perception=True)
    assert report["perception_gate"]["status"] == "blocked"
    assert report["PERCEPTION_READY"] == "no"
