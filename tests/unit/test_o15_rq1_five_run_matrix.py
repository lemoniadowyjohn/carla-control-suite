"""Tests for O15 RQ1 five-run matrix."""
from __future__ import annotations

import json
from pathlib import Path

from tools.rq1_five_run_matrix import build_matrix


def test_fewer_than_five_is_incomplete(tmp_path: Path):
    p = tmp_path / "one.json"
    p.write_text(json.dumps({"xodr_sha256": "a"}))
    report = build_matrix([p])
    assert report["verdict"] == "INCOMPLETE"
    assert report["run_count"] == 1


def test_five_identical_receipts_pass(tmp_path: Path):
    paths = []
    for i in range(5):
        p = tmp_path / f"run{i}.json"
        p.write_text(json.dumps({"xodr_sha256": "a", "structural_signature": "s", "feature_counts": {"roads": 1}, "topology_counts": {"junctions": 1}}))
        paths.append(p)
    report = build_matrix(paths)
    assert report["verdict"] == "PASS"
    assert report["mismatches"] == []


def test_structural_difference_fails(tmp_path: Path):
    paths = []
    for i in range(5):
        p = tmp_path / f"run{i}.json"
        p.write_text(json.dumps({"xodr_sha256": "a", "structural_signature": "s" if i < 4 else "different"}))
        paths.append(p)
    report = build_matrix(paths)
    assert report["verdict"] == "FAIL"
    assert any(m["field"] == "structural_signature" for m in report["mismatches"])


def test_unknown_fields_are_not_normalized(tmp_path: Path):
    paths = []
    for i in range(5):
        p = tmp_path / f"run{i}.json"
        p.write_text(json.dumps({"xodr_sha256": "a", "unknown_field": i}))
        paths.append(p)
    report = build_matrix(paths)
    assert report["verdict"] == "PASS"
