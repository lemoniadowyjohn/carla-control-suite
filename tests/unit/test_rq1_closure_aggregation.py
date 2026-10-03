"""RQ1 closure aggregation tests (batch 14 section 5).

The aggregator must derive RQ1 status from an explicitly declared evidence
set, never from an incidental glob. These tests pin the five scenarios the
batch calls out, including the two that previously produced the wrong answer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE))
sys.path.insert(0, str(WORKTREE / "tools"))

from rq1_determinism_authority import (  # noqa: E402
    _receipts_from_matrix, build_verdict,
)

RECEIPT_SCHEMA = "rq1_run_receipt/v1"


def _write_receipt(path: Path, *, xodr: str, normalized: str,
                   schema: str = RECEIPT_SCHEMA, status: str = "ignored") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": schema,
        "xodr_sha256": xodr,
        "normalized_xodr_sha256": normalized,
        "structural_signature": {"roads": 10},
        "feature_counts": {"a": 1},
        "topology_counts": {"junctions": 2},
        "output_path": f"out/{path.stem}.xodr",
        "tileset_digest": "t",
        "map_acceptance_digest": "m",
        "final_receipt_digest": "f",
        "status": status,
    }), encoding="utf-8")
    return path


def _five(tmp_path: Path, tag: str, *, schema: str = RECEIPT_SCHEMA) -> list:
    return [
        _write_receipt(
            tmp_path / tag / f"run_{i:02d}" / f"receipt_{i:02d}.json",
            xodr=f"raw_{i}", normalized="norm_same", schema=schema)
        for i in range(5)
    ]


# ---------------------------------------------------------------------------
# explicit matrix resolution
# ---------------------------------------------------------------------------

def test_matrix_resolution_uses_complete_receipts(tmp_path):
    m = tmp_path / "M.json"
    m.write_text(json.dumps({"complete_receipts": ["a/one.json", "a/two.json"]}),
                 encoding="utf-8")
    got = _receipts_from_matrix(m)
    assert [p.name for p in got] == ["one.json", "two.json"]


def test_matrix_resolution_accepts_wave_b_receipts_key(tmp_path):
    """The RQ1B matrix uses `receipts`, the RQ1A matrix `complete_receipts`."""
    m = tmp_path / "M.json"
    m.write_text(json.dumps({"receipts": ["b/one.json"]}), encoding="utf-8")
    assert [p.name for p in _receipts_from_matrix(m)] == ["one.json"]


def test_matrix_without_receipt_list_is_refused(tmp_path):
    m = tmp_path / "M.json"
    m.write_text(json.dumps({"verdict": "PASS"}), encoding="utf-8")
    with pytest.raises(ValueError):
        _receipts_from_matrix(m)


def test_matrix_with_empty_receipt_list_is_refused(tmp_path):
    m = tmp_path / "M.json"
    m.write_text(json.dumps({"complete_receipts": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        _receipts_from_matrix(m)


# ---------------------------------------------------------------------------
# the five required scenarios
# ---------------------------------------------------------------------------

def test_five_valid_a_and_zero_valid_b_is_incomplete(tmp_path):
    a = _five(tmp_path, "a")
    b = []
    v = build_verdict(a, b)
    assert v["rq1a_count"] == 5
    assert v["rq1b_count"] == 0
    assert v["verdict"] == "INCOMPLETE"
    assert "RQ1B" in v["reason"]


def test_five_valid_a_and_five_valid_b_is_not_incomplete(tmp_path):
    a = _five(tmp_path, "a")
    b = _five(tmp_path, "b")
    v = build_verdict(a, b)
    assert v["rq1a_count"] == 5
    assert v["rq1b_count"] == 5
    assert v["verdict"] != "INCOMPLETE"


def test_one_valid_a_and_five_valid_b_is_incomplete_on_a(tmp_path):
    """The historical bug: a single A receipt must not read as complete."""
    a = _five(tmp_path, "a")[:1]
    b = _five(tmp_path, "b")
    v = build_verdict(a, b)
    assert v["rq1a_count"] == 1
    assert v["verdict"] == "INCOMPLETE"
    assert "RQ1A" in v["reason"]


def test_wrong_experiment_receipts_do_not_count(tmp_path):
    a = _five(tmp_path, "a", schema="some_other_schema/v9")
    b = _five(tmp_path, "b")
    v = build_verdict(a, b)
    assert v["rq1a_count"] == 0
    assert v["verdict"] == "INCOMPLETE"
    assert "RQ1A" in v["reason"]


def test_duplicate_receipts_are_detected_as_a_mismatch(tmp_path):
    a = _five(tmp_path, "a")
    b = list(a)  # the same five paths reused as "B" evidence
    v = build_verdict(a, b)
    # 5 receipts load fine, so the counts are 5/5; the aggregator must not
    # silently accept the identical evidence set as two independent campaigns.
    assert v["rq1a_count"] == 5
    assert v["rq1b_count"] == 5
    if v["verdict"] != "INCOMPLETE":
        assert v.get("mismatches"), "duplicate evidence must surface a finding"


def test_missing_receipt_file_is_not_counted(tmp_path):
    a = _five(tmp_path, "a")
    a.append(tmp_path / "a" / "run_99" / "receipt_99.json")  # never written
    b = _five(tmp_path, "b")
    v = build_verdict(a, b)
    assert v["rq1a_count"] == 5
    assert v["verdict"] != "INCOMPLETE"


# ---------------------------------------------------------------------------
# committed evidence reflects the corrected semantics
# ---------------------------------------------------------------------------

def test_committed_rq1_closure_reflects_five_rq1a_runs():
    p = WORKTREE / "reports/rq1b_runs/RQ1_CLOSURE.json"
    assert p.is_file()
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["rq1a_count"] == 5, doc
    assert doc["rq1b_count"] == 0, doc
    assert doc["verdict"] == "INCOMPLETE"


def test_committed_rq1a_matrix_is_the_five_run_authority():
    p = WORKTREE / "reports/rq1a_runs/RQ1A_FIVE_RUN_MATRIX.json"
    assert p.is_file()
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["verdict"] == "BYTE_NONDETERMINISTIC_NORMALIZED_DETERMINISTIC"
    assert len(doc["complete_receipts"]) == 5