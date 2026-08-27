"""ultimate_pipeline/tools/carla_visual_smoke_gate.py -- most of this module needs live
CARLA (camera capture, world loading), but `evaluate_visual_smoke_report` is a pure function
over an already-produced report dict, and `run_visual_smoke_gate`'s early-exit paths (missing
XODR, UP_DISABLE_CARLA=1) don't touch CARLA at all -- both were completely untested on this
branch. UP_DISABLE_CARLA=1 is the actual standing state on this machine (GPU TDR blocker), so
this specific code path is the one that genuinely runs here in practice.
"""
from __future__ import annotations

import json
from pathlib import Path

from ultimate_pipeline.tools.carla_visual_smoke_gate import (
    evaluate_visual_smoke_report,
    run_visual_smoke_gate,
)


def _ok_report(**overrides):
    report = {
        "ok": True,
        "load_ok": True,
        "screenshots": {
            "top_down": {"ok": True, "path": "top_down.png"},
            "street": {"ok": True, "path": "street.png"},
            "junction": {"ok": True, "path": "junction.png"},
        },
    }
    report.update(overrides)
    return report


# ---------------------------------------------------------------------------
# evaluate_visual_smoke_report
# ---------------------------------------------------------------------------

def test_evaluate_all_views_present_and_ok_passes():
    result = evaluate_visual_smoke_report(_ok_report())
    assert result["ok"] is True
    assert result["missing_views"] == []
    assert result["failed_views"] == []


def test_evaluate_missing_view_fails():
    report = _ok_report()
    del report["screenshots"]["junction"]
    result = evaluate_visual_smoke_report(report)
    assert result["ok"] is False
    assert result["missing_views"] == ["junction"]


def test_evaluate_failed_view_fails():
    report = _ok_report()
    report["screenshots"]["street"]["ok"] = False
    result = evaluate_visual_smoke_report(report)
    assert result["ok"] is False
    assert "street" in result["failed_views"]


def test_evaluate_load_not_ok_still_evaluates_views_but_ok_stays_false():
    report = _ok_report(ok=False, load_ok=False)
    result = evaluate_visual_smoke_report(report)
    assert result["ok"] is False


def test_evaluate_require_files_missing_file_fails(tmp_path: Path):
    report = _ok_report()
    result = evaluate_visual_smoke_report(report, require_files=True, base_dir=tmp_path)
    assert result["ok"] is False
    assert set(result["missing_files"]) == {"top_down", "street", "junction"}


def test_evaluate_require_files_present_file_passes(tmp_path: Path):
    for name in ("top_down", "street", "junction"):
        (tmp_path / f"{name}.png").write_bytes(b"fake png bytes")
    report = _ok_report()
    result = evaluate_visual_smoke_report(report, require_files=True, base_dir=tmp_path)
    assert result["ok"] is True
    assert result["missing_files"] == []


def test_evaluate_require_files_zero_byte_file_treated_as_missing(tmp_path: Path):
    for name in ("top_down", "street", "junction"):
        (tmp_path / f"{name}.png").touch()  # exists but empty
    report = _ok_report()
    result = evaluate_visual_smoke_report(report, require_files=True, base_dir=tmp_path)
    assert result["ok"] is False
    assert set(result["missing_files"]) == {"top_down", "street", "junction"}


def test_evaluate_screenshots_not_a_dict_treated_as_all_missing():
    report = {"ok": True, "load_ok": True, "screenshots": "not a dict"}
    result = evaluate_visual_smoke_report(report)
    assert result["ok"] is False
    assert set(result["missing_views"]) == {"top_down", "street", "junction"}


# ---------------------------------------------------------------------------
# run_visual_smoke_gate -- offline early-exit paths only (no live CARLA)
# ---------------------------------------------------------------------------

def test_run_gate_missing_xodr_fails_closed_without_touching_carla(tmp_path: Path):
    result = run_visual_smoke_gate(xodr_path=tmp_path / "does_not_exist.xodr", out_dir=tmp_path / "out")
    assert result["ok"] is False
    assert "xodr_missing" in result["errors"]
    assert result["CARLA_VISUAL_READY"] == "no"
    report_path = tmp_path / "out" / "carla_visual_smoke_gate.json"
    assert report_path.is_file()
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["ok"] is False


def test_run_gate_disabled_by_env_skips_cleanly(tmp_path: Path, monkeypatch):
    # This is the actual standing state on this machine (UP_DISABLE_CARLA=1, GPU TDR
    # blocker) -- confirms the gate reports a clean, honest "skipped" rather than
    # silently claiming readiness or crashing.
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    monkeypatch.setenv("UP_DISABLE_CARLA", "1")
    result = run_visual_smoke_gate(xodr_path=xodr, out_dir=tmp_path / "out")
    assert result["ok"] is False
    assert result["CARLA_VISUAL_READY"] == "skipped"
    assert "carla_disabled_by_env" in result["errors"]
    assert result["xodr_sha256"]  # still computed even though CARLA is skipped
