"""C19 step 2 (current era) — audit_thesis_topic_contract.py's new
current_rq_tables_audit section: fails closed on missing status / bare
DEFERRED-with-no-reason, independent of the legacy run11-era checks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ultimate_pipeline.tools.audit_thesis_topic_contract import _current_rq_tables_audit


def _write_rq_tables(root: Path, rows: list) -> None:
    p = root / "reports" / "post_audit_hardening" / "C19_THESIS_ASSEMBLY" / "rq_tables.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"rows": rows, "counts_by_status": {}}), encoding="utf-8")


def test_reports_not_found_when_rq_tables_missing(tmp_path: Path) -> None:
    result = _current_rq_tables_audit(tmp_path)
    assert result["rq_tables_found"] is False
    assert result["violations"]


def test_positive_control_clean_rows_pass(tmp_path: Path) -> None:
    _write_rq_tables(tmp_path, [
        {"rq": "RQ1", "metric": "lane_width_gap", "status": "BOUNDED", "note": "fine"},
        {"rq": "RQ2", "metric": "perceptual_gap", "status": "DEFERRED", "note": "blocked on CARLA"},
        {"rq": "RQ3", "metric": "miou", "status": "DEFERRED", "note": "blocked"},
        {"rq": "RQ5", "metric": "shift", "status": "DEFERRED", "note": "no real dataset"},
        {"rq": "RQ4", "metric": "natural_dr_present", "status": "AUTHORITATIVE", "note": "measured"},
    ])
    result = _current_rq_tables_audit(tmp_path)
    assert result["ok"] is True
    assert result["violations"] == []


def test_negative_control_bare_deferred_flagged(tmp_path: Path) -> None:
    _write_rq_tables(tmp_path, [
        {"rq": "RQ1", "metric": "x", "status": "BOUNDED", "note": "ok"},
        {"rq": "RQ2", "metric": "y", "status": "DEFERRED", "note": ""},  # no reason given
        {"rq": "RQ3", "metric": "z", "status": "DEFERRED", "note": "ok"},
        {"rq": "RQ5", "metric": "w", "status": "DEFERRED", "note": "ok"},
        {"rq": "RQ4", "metric": "v", "status": "AUTHORITATIVE", "note": "ok"},
    ])
    result = _current_rq_tables_audit(tmp_path)
    assert result["ok"] is False
    assert any("no reason given" in v for v in result["violations"])


def test_negative_control_invalid_status_flagged(tmp_path: Path) -> None:
    _write_rq_tables(tmp_path, [
        {"rq": "RQ1", "metric": "x", "status": "SOMETHING_MADE_UP", "note": "ok"},
        {"rq": "RQ2", "metric": "y", "status": "DEFERRED", "note": "ok"},
        {"rq": "RQ3", "metric": "z", "status": "DEFERRED", "note": "ok"},
        {"rq": "RQ5", "metric": "w", "status": "DEFERRED", "note": "ok"},
        {"rq": "RQ4", "metric": "v", "status": "AUTHORITATIVE", "note": "ok"},
    ])
    result = _current_rq_tables_audit(tmp_path)
    assert result["ok"] is False
    assert any("invalid or missing status" in v for v in result["violations"])


def test_negative_control_missing_rq_coverage_flagged(tmp_path: Path) -> None:
    _write_rq_tables(tmp_path, [
        {"rq": "RQ1", "metric": "x", "status": "BOUNDED", "note": "ok"},
        # RQ2, RQ3, RQ4, RQ5 all absent.
    ])
    result = _current_rq_tables_audit(tmp_path)
    assert result["ok"] is False
    assert any("zero rows" in v for v in result["violations"])


def test_against_real_repo_after_export_tool_ran() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = _current_rq_tables_audit(repo_root)
    assert result["rq_tables_found"] is True
    assert result["ok"] is True, result["violations"]
