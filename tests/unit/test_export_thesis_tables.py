"""C19 step 1 — export_thesis_tables.py: honesty-gate row assembly.

Core invariant this protects: every RQ metric this tool knows about must
get an explicit status (never silently omitted), and when both a stale and
a corrected evidence file exist for the same metric (RQ1's curvature gap),
the corrected value must win.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.export_thesis_tables import build_tables, DEFERRED, MISSING, AUTHORITATIVE, BOUNDED, PROTOTYPE


def _mk(tmp_path: Path, rel: str, payload: dict) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def test_missing_evidence_reports_missing_not_omitted(tmp_path: Path) -> None:
    payload = build_tables(tmp_path)
    statuses = {r["status"] for r in payload["rows"] if r["rq"] == "RQ1"}
    assert statuses == {MISSING}
    statuses4 = {r["status"] for r in payload["rows"] if r["rq"] == "RQ4"}
    assert statuses4 == {MISSING}


def test_rq2_always_deferred_with_reason(tmp_path: Path) -> None:
    payload = build_tables(tmp_path)
    rq2 = [r for r in payload["rows"] if r["rq"] == "RQ2"]
    assert len(rq2) == 1
    assert rq2[0]["status"] == DEFERRED
    assert rq2[0]["note"]  # must state why, never a bare DEFERRED


def test_every_row_has_explicit_status(tmp_path: Path) -> None:
    payload = build_tables(tmp_path)
    for row in payload["rows"]:
        assert row["status"] in {"AUTHORITATIVE", "BOUNDED", "PROTOTYPE", "DEFERRED", "MISSING"}
        assert row["rq"] and row["metric"]


def test_rq1_prefers_corrected_curvature_over_stale_main_json(tmp_path: Path) -> None:
    _mk(tmp_path, "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/C14_RQ1_STRUCTURAL_GAP.json", {
        "auto_map": {"path": "auto.xodr", "sha256": "aa" * 32},
        "manual_map": {"path": "manual.xodr", "sha256": "bb" * 32},
        "scores": {"lane_width_gap": 0.04, "curvature_gap": 1.0, "road_length_gap": 1.0,
                   "traffic_light_density_gap": 1.0, "building_density_gap": 0.8, "road_type_coverage_gap": 0.0},
    })
    _mk(tmp_path, "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/curvature_recompute.json", {
        "all_scores": {"lane_width_gap": 0.04, "curvature_gap": 0.093117, "road_length_gap": 1.0,
                        "traffic_light_density_gap": 1.0, "building_density_gap": 0.8, "road_type_coverage_gap": 0.0},
    })
    payload = build_tables(tmp_path)
    curvature_row = next(r for r in payload["rows"] if r["rq"] == "RQ1" and r["metric"] == "curvature_gap")
    assert curvature_row["value"] == 0.093117


def test_rq4_authoritative_when_evidence_present(tmp_path: Path) -> None:
    _mk(tmp_path, "reports/post_audit_hardening/C15_RQ4_DR/C15_RQ4_DOMAIN_RANDOMIZATION.json", {
        "determinism_arm": {"runs": 3, "byte_sha_unique": 3, "structurally_deterministic": True,
                             "finding": "structurally deterministic, byte-varying"},
        "explicit_dr": {"module": "x.py", "apply_n_produces_distinct_variants": 5, "changes_input": True},
    })
    payload = build_tables(tmp_path)
    rq4 = [r for r in payload["rows"] if r["rq"] == "RQ4"]
    assert all(r["status"] == AUTHORITATIVE for r in rq4)
    natural_dr_row = next(r for r in rq4 if r["metric"] == "natural_dr_present")
    assert natural_dr_row["value"] is False


def test_gnn_row_is_prototype_not_authoritative(tmp_path: Path) -> None:
    _mk(tmp_path, "reports/post_audit_hardening/C18_GNN_LATENT_GAP/gnn_training_report.json", {
        "latent_gap": {
            "metrics": {"cosine_distance": 1.14},
            "encoder": {"checkpoint_md5": "deadbeef"},
        },
    })
    payload = build_tables(tmp_path)
    gnn_row = next(r for r in payload["rows"] if r["metric"] == "gnn_latent_cosine_distance")
    assert gnn_row["status"] == PROTOTYPE
    assert gnn_row["value"] == 1.14


def test_against_real_repo_root_does_not_crash_and_finds_real_evidence() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    payload = build_tables(repo_root)
    assert payload["row_count"] > 0
    curvature_row = next(r for r in payload["rows"] if r["rq"] == "RQ1" and r["metric"] == "curvature_gap")
    # Must be the corrected value (~0.093), not the stale 1.0 artifact.
    assert curvature_row["value"] is not None and curvature_row["value"] < 0.5
