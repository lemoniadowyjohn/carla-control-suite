"""--validate-only gate logic for rq2_metric_authority (merge gate for rq2-authority).

These tests pin the pure validation helpers -- citation checks, frozen-results
comparison, and report assembly -- against hand-built documents. They never run
the map computations (those are exercised by
`rq2_metric_authority.py --validate-only`, whose receipt is
RQ2_VALIDATE_ONLY.json).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ultimate_pipeline.domain_gap.rq2_metric_authority import (
    FROZEN_CITATIONS,
    FROZEN_RESULTS_ATOL,
    FROZEN_RESULTS_FILENAME,
    SCOPES,
    _check_citation,
    _compare_frozen,
    _load_frozen_results,
    build_validation_report,
)


def _doc() -> dict:
    return {
        "pair": {
            "auto": {
                "path": "campaigns/x/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr",
                "sha256": "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8",
            },
            "manual": {"path": "Grid0828.xodr", "sha256": "5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c"},
        },
        "scopes": {
            "manual_hull": {
                "metrics": {
                    "road_length_ratio": 2.6831,
                    "junction_ratio": 3.7816,
                    "road_count_ratio": 3.5614,
                    "curvature_gap": 0.22058,
                    "lane_width_gap": 0.05967,
                    "building_density_gap": 0.23084,
                    "frechet_distance": {"mean_m": 58.1835, "median_m": 36.1325, "p90_m": 140.4752, "pairs": 894},
                },
                "support": {"cropped_auto_roads": 3536, "manual_roads": 993},
            },
            "whole_map": {
                "metrics": {"road_length_ratio": 27.821},
                "support": {"auto_length_m": 1489145.6, "manual_length_m": 53525.3},
            },
        },
    }


def _frozen(doc: dict) -> dict:
    frozen = {"pair": doc["pair"], "scopes": {s: {"metrics": v["metrics"], "support": v["support"]} for s, v in doc["scopes"].items()}}
    return json.loads(json.dumps(frozen))  # deep copy: tests mutate doc after freezing


# ---------------------------------------------------------------------------
# FROZEN_CITATIONS table integrity
# ---------------------------------------------------------------------------

def test_citations_cover_both_scopes_and_unique_names():
    names = [c["name"] for c in FROZEN_CITATIONS]
    assert len(names) == len(set(names))
    paths = {c["path"][1] for c in FROZEN_CITATIONS if c["path"][0] == "scopes"}
    assert paths <= set(SCOPES)
    assert {"manual_hull", "whole_map"} <= paths


def test_citation_kinds_are_supported_and_round_has_ndp():
    for c in FROZEN_CITATIONS:
        assert c["kind"] in {"exact", "round", "prefix", "suffix"}
        if c["kind"] == "round":
            assert isinstance(c["ndp"], int)
        assert c["source"], c["name"]


# ---------------------------------------------------------------------------
# _check_citation
# ---------------------------------------------------------------------------

def _cite(name, path, expected, kind, **kw):
    return {"name": name, "source": "test", "path": path, "expected": expected, "kind": kind, **kw}


def test_check_citation_pass_and_fail_for_each_kind():
    doc = {"a": {"b": 2.68349, "s": "campaigns/ingolstadt.xodr", "sha": "370abbbbb3ff", "n": 894}}
    cases = [
        (_cite("r", ("a", "b"), 2.683, "round", ndp=3), "PASS"),
        (_cite("r", ("a", "b"), 2.684, "round", ndp=3), "FAIL"),
        (_cite("e", ("a", "n"), 894, "exact"), "PASS"),
        (_cite("e", ("a", "n"), 895, "exact"), "FAIL"),
        (_cite("pre", ("a", "sha"), "370abbbbb3", "prefix"), "PASS"),
        (_cite("pre", ("a", "sha"), "deadbeef", "prefix"), "FAIL"),
        (_cite("suf", ("a", "s"), "ingolstadt.xodr", "suffix"), "PASS"),
        (_cite("suf", ("a", "s"), "other.xodr", "suffix"), "FAIL"),
    ]
    for citation, want in cases:
        got = _check_citation(citation, doc)
        assert got["status"] == want, (citation["name"], got)


def test_check_citation_missing_path_fails():
    assert _check_citation(_cite("missing", ("a", "zzz"), 1, "exact"), {"a": {}})["status"] == "FAIL"
    assert _check_citation(_cite("wrongtype", ("a", "n"), 1, "round", ndp=0), {"a": {"n": "894"}})["status"] == "FAIL"


def test_check_citation_unknown_kind_fails_closed():
    assert _check_citation(_cite("weird", ("a", "n"), 894, "tolerance_plus"), {"a": {"n": 894}})["status"] == "FAIL"


# ---------------------------------------------------------------------------
# _compare_frozen
# ---------------------------------------------------------------------------

def test_compare_frozen_equal_within_atol_passes():
    failures = []
    _compare_frozen({"x": 1.0, "y": [1, "a", True]}, {"x": 1.0 + FROZEN_RESULTS_ATOL / 4, "y": [1, "a", True]}, "p", failures, FROZEN_RESULTS_ATOL)
    assert failures == []


def test_compare_frozen_reports_missing_unexpected_and_drift():
    failures = []
    _compare_frozen({"x": 1.0, "gone": 2}, {"x": 1.5, "extra": 3}, "p", failures, FROZEN_RESULTS_ATOL)
    assert any("gone: missing" in f for f in failures)
    assert any("extra: unexpected" in f for f in failures)
    assert any("p.x" in f for f in failures)


def test_compare_frozen_bool_is_identity_not_numeric():
    failures = []
    _compare_frozen({"flag": True}, {"flag": 1}, "p", failures, FROZEN_RESULTS_ATOL)
    assert failures, "True vs 1 must fail (bool identity check)"


def test_compare_frozen_list_shape_mismatch():
    failures = []
    _compare_frozen([1, 2, 3], [1, 2], "p", failures, FROZEN_RESULTS_ATOL)
    assert any("list shape mismatch" in f for f in failures)


# ---------------------------------------------------------------------------
# build_validation_report
# ---------------------------------------------------------------------------

def test_report_pass_verdict_with_matching_doc():
    doc = _doc()
    report = build_validation_report(doc, _frozen(doc))
    assert report["schema"] == "rq2_validate_only/v1"
    assert report["verdict"] == "PASS"
    assert report["summary"] == {"total": len(FROZEN_CITATIONS) + 1, "passed": len(FROZEN_CITATIONS) + 1, "failed": 0}
    assert report["gate"] == "merge rq2-authority into production only if verdict == PASS"


def test_report_fail_verdict_on_drifted_metric():
    doc = _doc()
    frozen = _frozen(doc)
    doc["scopes"]["manual_hull"]["metrics"]["road_length_ratio"] = 2.600
    report = build_validation_report(doc, frozen)
    assert report["verdict"] == "FAIL"
    failed = {c["name"] for c in report["checks"] if c["status"] == "FAIL"}
    assert "hull.road_length_ratio" in failed
    assert "frozen_results.metrics_and_pair" in failed


def test_report_fail_when_scope_missing_on_either_side():
    doc = _doc()
    frozen = _frozen(doc)

    def failures_of(report):
        check = next(c for c in report["checks"] if c["name"] == "frozen_results.metrics_and_pair")
        assert isinstance(check["actual"], list)
        return check["actual"]

    frozen["scopes"].pop("whole_map")
    report = build_validation_report(doc, frozen)
    assert report["verdict"] == "FAIL"
    assert any("absent from frozen" in f for f in failures_of(report))

    doc2, frozen2 = _doc(), _frozen(_doc())
    doc2["scopes"].pop("whole_map")
    report2 = build_validation_report(doc2, frozen2)
    assert report2["verdict"] == "FAIL"
    assert any("missing in recomputation" in f for f in failures_of(report2))


def test_report_does_not_mutate_inputs():
    doc = _doc()
    frozen = _frozen(doc)
    doc_before, frozen_before = json.dumps(doc, sort_keys=True), json.dumps(frozen, sort_keys=True)
    build_validation_report(doc, frozen)
    assert json.dumps(doc, sort_keys=True) == doc_before
    assert json.dumps(frozen, sort_keys=True) == frozen_before


# ---------------------------------------------------------------------------
# _load_frozen_results
# ---------------------------------------------------------------------------

def test_load_frozen_results_reads_committed_worktree_file():
    results = _load_frozen_results()
    assert isinstance(results, dict)
    worktree = Path(__file__).resolve().parents[2]
    assert (worktree / FROZEN_RESULTS_FILENAME).is_file()
    for scope in SCOPES:
        assert scope in results.get("scopes", {}), f"committed {FROZEN_RESULTS_FILENAME} lacks scope {scope}"


def test_load_frozen_results_exits_when_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "ultimate_pipeline.domain_gap.rq2_metric_authority.WORKTREE", tmp_path
    )
    with pytest.raises(SystemExit, match=FROZEN_RESULTS_FILENAME):
        _load_frozen_results()
