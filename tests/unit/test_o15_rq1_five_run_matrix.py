"""Tests for O15 RQ1 five-run matrix."""
from __future__ import annotations

import json
from pathlib import Path

from tools.rq1_five_run_matrix import RUN_RECEIPT_SCHEMA, build_matrix

#: Every determinism field build_matrix() compares.  A PASS requires all of
#: them to be populated: NEW-346 makes "null in every receipt" INCOMPLETE
#: rather than an agreement.
_COMPARED_FIELDS = [
    "xodr_sha256",
    "normalized_xodr_sha256",
    "structural_signature",
    "feature_counts",
    "topology_counts",
    "output_path",
    "tileset_digest",
    "map_acceptance_digest",
    "final_receipt_digest",
]


def _receipt(**overrides) -> dict:
    payload = {field: f"{field}-value" for field in _COMPARED_FIELDS}
    payload["schema"] = RUN_RECEIPT_SCHEMA
    payload.update(overrides)
    return payload


def _write(tmp_path: Path, payloads: list[dict]) -> list[Path]:
    paths = []
    for i, payload in enumerate(payloads):
        p = tmp_path / f"run{i}.json"
        p.write_text(json.dumps(payload))
        paths.append(p)
    return paths


def test_fewer_than_five_is_incomplete(tmp_path: Path):
    p = tmp_path / "one.json"
    p.write_text(json.dumps({"xodr_sha256": "a"}))
    report = build_matrix([p])
    assert report["verdict"] == "INCOMPLETE"
    assert report["run_count"] == 1


def test_five_identical_complete_receipts_pass(tmp_path: Path):
    report = build_matrix(_write(tmp_path, [_receipt() for _ in range(5)]))
    assert report["verdict"] == "PASS"
    assert report["mismatches"] == []
    assert report["incomparable_fields"] == []
    assert report["receipt_schema_gaps"] == []


def test_structural_difference_fails(tmp_path: Path):
    payloads = [_receipt(structural_signature="s") for _ in range(4)]
    payloads.append(_receipt(structural_signature="different"))
    report = build_matrix(_write(tmp_path, payloads))
    assert report["verdict"] == "FAIL"
    assert any(m["field"] == "structural_signature" for m in report["mismatches"])


def test_unknown_fields_are_not_normalized(tmp_path: Path):
    # An extra field that differs run-to-run must not be compared at all; the
    # determinism fields themselves are identical, so the matrix passes.
    payloads = [_receipt(unknown_field=i) for i in range(5)]
    report = build_matrix(_write(tmp_path, payloads))
    assert report["verdict"] == "PASS"
    assert report["mismatches"] == []


def test_null_in_every_receipt_is_incomplete_not_agreement(tmp_path: Path):
    # NEW-346: five receipts that all leave every determinism field null agree
    # on nothing -- reporting PASS here was a false certification.
    payloads = [{"schema": RUN_RECEIPT_SCHEMA, "run": i, "status": "INCOMPLETE"} for i in range(5)]
    report = build_matrix(_write(tmp_path, payloads))
    assert report["verdict"] == "INCOMPLETE"
    assert report["status"] == "INCOMPLETE"
    assert len(report["incomparable_fields"]) == len(_COMPARED_FIELDS)
    assert report["mismatches"] == []


def test_null_in_only_some_receipts_is_a_mismatch(tmp_path: Path):
    payloads = [_receipt() for _ in range(4)]
    payloads.append({"schema": RUN_RECEIPT_SCHEMA, "run": 4})
    report = build_matrix(_write(tmp_path, payloads))
    assert report["verdict"] == "FAIL"
    assert report["mismatches"]


def test_receipt_without_schema_is_incomplete(tmp_path: Path):
    payloads = [_receipt() for _ in range(4)]
    bare = _receipt()
    bare.pop("schema")
    payloads.append(bare)
    report = build_matrix(_write(tmp_path, payloads))
    assert report["verdict"] == "INCOMPLETE"
    assert len(report["receipt_schema_gaps"]) == 1


def test_unreadable_receipt_is_reported(tmp_path: Path):
    paths = _write(tmp_path, [_receipt() for _ in range(4)])
    bad = tmp_path / "run4.json"
    bad.write_text("{not json")
    paths.append(bad)
    report = build_matrix(paths)
    assert report["verdict"] == "INCOMPLETE"
    assert any(row["status"] == "UNREADABLE" for row in report["runs"])
