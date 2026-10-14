"""Tests for the RQ1 determinism matrix and receipt assembler.

Regression coverage targets defects that produced a wrong RQ1 verdict:

* the assembler's two-digit stage key collided on ``06``, so a receipt could
  describe ``06_continuity`` or ``06_geometry_frozen`` depending on
  ``os.listdir`` order;
* the matrix compared ``output_path``, which is unique per isolated run and
  therefore forces a FAIL for any five genuine runs;
* the matrix ignored pipeline terminal state, so a crashed run was averaged
  into a determinism comparison;
* v1 receipts use a different junction metric and were silently mixed with v2.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.rq1_five_run_matrix import build_matrix
from tools.rq1_receipt_assembler import assemble_receipt, stage_identity

V2 = "rq1_run_receipt/v2"


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _receipt(run: int, sha: str = "a", *, terminal_stage: str = "08_final", status: str = "ok", **extra) -> dict:
    return {
        "run": run,
        "schema": V2,
        "status": "INCOMPLETE",
        "pipeline_status": {"recorded": True, "status": status, "stage": "final", "error": None},
        "terminal_stage": terminal_stage,
        "completed_stages": {terminal_stage: {"sha256": sha, "bytes": 1, "mtime": 1.0}},
        "xodr_sha256": sha,
        "structural_signature": {"num_roads": 10, "num_junctions": 2, "total_road_length": 1.0},
        "topology_counts": {"junctions": 2, "roads": 10},
        "feature_counts": {"roads": 10},
        "output_path": f"reports/rq1_trial_runs/run_{run:02d}/20261001_000000_000000/08_final_x.xodr",
        "normalized_xodr_sha256": None,
        "tileset_digest": None,
        "map_acceptance_digest": None,
        "final_receipt_digest": None,
        **extra,
    }


# --------------------------------------------------------------------------
# stage_identity: the 06 prefix collision
# --------------------------------------------------------------------------


def test_stage_identity_is_full_stage_name_not_two_digits():
    """Regression: ``06_continuity`` and ``06_geometry_frozen`` collided on "6"."""
    assert stage_identity("06_continuity_20261001_042523_540218.xodr") == "06_continuity"
    assert stage_identity("06_geometry_frozen_20261001_042523_540218.xodr") == "06_geometry_frozen"


def test_stage_identity_rejects_unstamped_names():
    assert stage_identity("05_planview.xodr") is None
    assert stage_identity("notes.txt") is None


# --------------------------------------------------------------------------
# assembler
# --------------------------------------------------------------------------


def _stage(dir_: Path, name: str, data: bytes, mtime: float) -> Path:
    p = dir_ / name
    p.write_bytes(data)
    import os

    os.utime(p, (mtime, mtime))
    return p


def test_assembler_keeps_both_06_artifacts(tmp_path: Path):
    d = tmp_path / "20261001_042523_540218"
    d.mkdir()
    _stage(d, "03_topology_20261001_042523_540218.xodr", b"topo", 100.0)
    _stage(d, "06_continuity_20261001_042523_540218.xodr", b"cont", 200.0)
    _stage(d, "06_geometry_frozen_20261001_042523_540218.xodr", b"frozen", 300.0)

    rec = assemble_receipt(1, d)

    assert set(rec["completed_stages"]) == {"03_topology", "06_continuity", "06_geometry_frozen"}
    # 06_geometry_frozen is later in pipeline order, so it is terminal.
    assert rec["terminal_stage"] == "06_geometry_frozen"
    assert rec["xodr_sha256"] == rec["completed_stages"]["06_geometry_frozen"]["sha256"]


def test_assembler_records_copy2_duplicate(tmp_path: Path):
    """shutil.copy2 output is byte- and mtime-identical; record it explicitly."""
    d = tmp_path / "20261001_042523_540218"
    d.mkdir()
    _stage(d, "03_topology_20261001_042523_540218.xodr", b"same bytes", 1790824503.3667295)
    _stage(d, "05_planview_20261001_042523_540218.xodr", b"same bytes", 1790824503.3667295)

    rec = assemble_receipt(1, d)

    pair = rec["byte_identical_stage_pairs"]
    assert len(pair) == 1
    assert set(pair[0]["stages"]) == {"03_topology", "05_planview"}
    assert rec["completed_stages"]["05_planview"]["duplicate_of"] == "03_topology"
    assert rec["completed_stages"]["05_planview"]["metadata_preserving_copy"] is True


def test_assembler_does_not_call_distinct_bytes_a_duplicate(tmp_path: Path):
    d = tmp_path / "20261001_042523_540218"
    d.mkdir()
    _stage(d, "03_topology_20261001_042523_540218.xodr", b"a", 100.0)
    _stage(d, "05_planview_20261001_042523_540218.xodr", b"b", 100.0)

    rec = assemble_receipt(1, d)
    assert rec["byte_identical_stage_pairs"] == []
    assert rec["completed_stages"]["05_planview"]["duplicate_of"] is None


def test_assembler_reports_unstamped_artifacts_instead_of_dropping_them(tmp_path: Path):
    d = tmp_path / "20261001_042523_540218"
    d.mkdir()
    _stage(d, "03_topology_20261001_042523_540218.xodr", b"a", 100.0)
    _stage(d, "mystery_output.xodr", b"a", 100.0)

    rec = assemble_receipt(1, d)
    assert rec["unattributed_artifacts"] == ["mystery_output.xodr"]


def test_assembler_records_pipeline_failure(tmp_path: Path):
    d = tmp_path / "20261001_042523_540218"
    d.mkdir()
    _stage(d, "03_topology_20261001_042523_540218.xodr", b"a", 100.0)
    (d / "run_status.json").write_text(
        json.dumps({"status": "failed", "stage": "geometry", "error": "F1 CRS contract unresolved"}),
        encoding="utf-8",
    )

    rec = assemble_receipt(1, d)
    assert rec["pipeline_status"]["status"] == "failed"
    assert rec["pipeline_status"]["stage"] == "geometry"


# --------------------------------------------------------------------------
# matrix: admissibility
# --------------------------------------------------------------------------


def test_fewer_than_five_is_incomplete(tmp_path: Path):
    report = build_matrix([_write(tmp_path, "one.json", _receipt(0))])
    assert report["verdict"] == "INCOMPLETE"
    assert report["run_count"] == 1


def test_crashed_run_is_inadmissible(tmp_path: Path):
    """Regression: a crashed run must not be averaged into the comparison."""
    paths = [
        _write(tmp_path, f"r{i}.json", _receipt(i, status="failed" if i == 0 else "completed")) for i in range(5)
    ]
    report = build_matrix(paths)
    assert report["verdict"] == "INCOMPLETE"
    assert report["admissible_run_count"] == 4
    assert any("terminated as" in b for b in report["blocking"])


def test_non_terminal_running_run_is_inadmissible(tmp_path: Path):
    """Regression: run_00 of the real trial batch left status 'running'."""
    paths = [
        _write(tmp_path, f"r{i}.json", _receipt(i, status="running" if i == 0 else "completed")) for i in range(5)
    ]
    report = build_matrix(paths)
    assert report["verdict"] == "INCOMPLETE"
    assert report["admissible_run_count"] == 4
    assert any("not a completed terminal state" in b for b in report["blocking"])


def test_missing_pipeline_status_is_inadmissible(tmp_path: Path):
    rec = _receipt(0)
    rec["pipeline_status"] = {"recorded": False, "status": None, "stage": None, "error": None}
    report = build_matrix([_write(tmp_path, "r0.json", rec)])
    assert report["verdict"] == "INCOMPLETE"
    assert any("terminal pipeline status" in b for b in report["blocking"])


def test_v1_schema_is_inadmissible(tmp_path: Path):
    """Regression: v1 receipts use a different junction metric."""
    rec = _receipt(0)
    rec["schema"] = "rq1_run_receipt/v1"
    report = build_matrix([_write(tmp_path, "r0.json", rec)])
    assert report["verdict"] == "INCOMPLETE"
    assert any("rq1_run_receipt/v1" in b for b in report["blocking"])


def test_divergent_terminal_stages_are_incomplete(tmp_path: Path):
    paths = [_write(tmp_path, f"r{i}.json", _receipt(i, terminal_stage="06_geometry_frozen" if i == 0 else "08_final")) for i in range(5)]
    report = build_matrix(paths)
    assert report["verdict"] == "INCOMPLETE"
    assert "terminal stages" in report["reason"]


# --------------------------------------------------------------------------
# matrix: comparison
# --------------------------------------------------------------------------


def test_five_identical_receipts_pass_despite_distinct_output_paths(tmp_path: Path):
    """Regression: output_path is unique per run and must not force a FAIL."""
    paths = [_write(tmp_path, f"r{i}.json", _receipt(i)) for i in range(5)]
    report = build_matrix(paths)
    assert report["verdict"] == "PASS", report["mismatches"]
    assert report["mismatches"] == []


def test_structural_difference_fails(tmp_path: Path):
    paths = []
    for i in range(5):
        rec = _receipt(i)
        if i == 4:
            rec["structural_signature"] = {"num_roads": 10, "num_junctions": 99, "total_road_length": 1.0}
        paths.append(_write(tmp_path, f"r{i}.json", rec))
    report = build_matrix(paths)
    assert report["verdict"] == "FAIL"
    assert any(m["field"] == "structural_signature" for m in report["mismatches"])


def test_raw_sha_difference_fails_and_is_not_normalized(tmp_path: Path):
    """A differing raw sha256 is a real observation and stays a FAIL."""
    paths = [_write(tmp_path, f"r{i}.json", _receipt(i, sha="a")) for i in range(4)]
    paths.append(_write(tmp_path, "r4.json", _receipt(4, sha="b")))
    report = build_matrix(paths)
    assert report["verdict"] == "FAIL"
    assert any(m["field"] == "xodr_sha256" for m in report["mismatches"])


def test_unknown_fields_are_not_normalized(tmp_path: Path):
    paths = [_write(tmp_path, f"r{i}.json", _receipt(i, unknown_field=i)) for i in range(5)]
    assert build_matrix(paths)["verdict"] == "PASS"


def test_unreadable_receipt_counts_against_five(tmp_path: Path):
    good = [_write(tmp_path, f"r{i}.json", _receipt(i)) for i in range(4)]
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    report = build_matrix([*good, bad])
    assert report["verdict"] == "INCOMPLETE"
    assert any(r["status"] == "UNREADABLE" for r in report["runs"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
