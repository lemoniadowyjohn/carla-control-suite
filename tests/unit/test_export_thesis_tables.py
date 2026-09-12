"""C19 step 1 — export_thesis_tables.py: honesty-gate row assembly.

Core invariant this protects: every RQ metric this tool knows about must
get an explicit status (never silently omitted), and when both a stale and
a corrected evidence file exist for the same metric (structural gap's
curvature gap), the corrected value must win.

RQ numbering here follows the actual submitted thesis (submission/
thesis_source/Chapter1/chap1.tex): RQ1=determinism, RQ2=structural domain
gap, RQ3=perceptual domain gap, RQ4=structural variability/latent
representation, RQ5=generalization/transfer. A semantic drift (structural
gap tagged "RQ1", perceptual gap tagged "RQ2", GNN work tagged "RQ3/RQ5")
was corrected 2026-09-06 -- see export_thesis_tables.py's per-function
docstrings for which thesis RQ each one covers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.export_thesis_tables import (
    AUTHORITATIVE,
    BOUNDED,
    DEFERRED_EXTERNAL_DATA,
    DEFERRED_RUNTIME,
    MISSING,
    PROTOTYPE,
    VALID_STATUSES,
    build_tables,
)


def _mk(tmp_path: Path, rel: str, payload: dict) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def test_missing_evidence_reports_missing_not_omitted(tmp_path: Path) -> None:
    payload = build_tables(tmp_path)
    # RQ1 = determinism, sourced from the same (here: absent) C15 evidence file.
    statuses1 = {r["status"] for r in payload["rows"] if r["rq"] == "RQ1"}
    assert statuses1 == {MISSING}
    # RQ2 = structural gap, sourced from the (here: absent) C14 evidence file.
    statuses2 = {r["status"] for r in payload["rows"] if r["rq"] == "RQ2"}
    assert statuses2 == {MISSING}
    # RQ4 = GNN latent + explicit-DR wiring, both unresolvable with no evidence at all.
    statuses4 = {r["status"] for r in payload["rows"] if r["rq"] == "RQ4"}
    assert statuses4 == {MISSING}


def test_rq3_perceptual_gap_always_deferred_with_reason(tmp_path: Path) -> None:
    payload = build_tables(tmp_path)
    rq3 = [r for r in payload["rows"] if r["rq"] == "RQ3"]
    assert len(rq3) == 1
    assert rq3[0]["status"] == DEFERRED_RUNTIME
    assert rq3[0]["note"]  # must state why, never a bare DEFERRED


def test_every_row_has_explicit_status_and_rich_provenance_schema(tmp_path: Path) -> None:
    payload = build_tables(tmp_path)
    required_fields = {
        "rq",
        "metric",
        "status",
        "thesis_baseline",
        "current_value",
        "unit",
        "absolute_delta",
        "relative_delta",
        "comparability",
        "method",
        "producer_commit",
        "evidence_path",
        "evidence_sha256",
        "input_auto_sha256",
        "input_manual_sha256",
        "software_versions",
        "sample_size",
        "random_seeds",
        "confidence_interval",
        "claim_boundary",
        "remaining_blocker",
    }
    for row in payload["rows"]:
        assert row["status"] in VALID_STATUSES
        assert row["rq"] and row["metric"]
        assert required_fields <= set(row)
    assert payload["schema_version"] == 2


def test_rq2_prefers_corrected_curvature_over_stale_main_json(tmp_path: Path) -> None:
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
    curvature_row = next(r for r in payload["rows"] if r["rq"] == "RQ2" and r["metric"] == "curvature_gap")
    assert curvature_row["value"] == 0.093117


def _local_structural_summary_payload():
    return {
        "road_network_structural": {
            "lane_width_gap": 0.0415,
            "curvature_gap": 0.2192,
            "road_length_ratio_auto_over_manual": 2.692,
            "junction_ratio_auto_over_manual": 3.782,
            "road_count_ratio_auto_over_manual": 3.565,
        },
        "building_density_comparison": {
            "building_density_gap": 0.4139,
            "cropped_auto_buildings": 3779,
            "manual_buildings": 993,
        },
        "construction_differences_excluded": {
            "reason": "traffic lights excluded from local gap",
            "cropped_auto_traffic_lights": 2194,
            "manual_traffic_lights": 0,
        },
        "footprint": {
            "auto_roads_kept": 3539,
            "auto_roads_total": 32297,
            "kept_fraction": 0.1096,
        },
    }


def test_rq2_uses_local_registration_when_present(tmp_path: Path) -> None:
    """C26 schema: local_registration.json has top-level hull/bbox blocks, each with its own
    local_structural_summary. hull (tighter, default) must be preferred over bbox."""
    _mk(tmp_path, "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/C14_RQ1_STRUCTURAL_GAP.json", {
        "auto_map": {"path": "auto.xodr", "sha256": "aa" * 32},
        "manual_map": {"path": "manual.xodr", "sha256": "bb" * 32},
        "scores": {"lane_width_gap": 0.04, "curvature_gap": 0.093, "road_length_gap": 1.0,
                   "traffic_light_density_gap": 1.0, "building_density_gap": 0.8, "road_type_coverage_gap": 0.0},
    })
    _mk(tmp_path, "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/local_registration.json", {
        "hull": {"local_structural_summary": _local_structural_summary_payload()},
        "bbox": {"local_structural_summary": {
            "road_network_structural": {
                "lane_width_gap": 0.0415,
                "curvature_gap": 0.2239,
                "road_length_ratio_auto_over_manual": 4.5,
                "junction_ratio_auto_over_manual": 6.05,
                "road_count_ratio_auto_over_manual": 6.122,
            },
            "construction_differences_excluded": {
                "reason": "construction layers excluded from local gap",
                "cropped_auto_traffic_lights": 3920,
            },
            "footprint": {"auto_roads_kept": 6079, "auto_roads_total": 32297, "kept_fraction": 0.1882},
        }},
    })
    payload = build_tables(tmp_path)
    rq2 = {r["metric"]: r for r in payload["rows"] if r["rq"] == "RQ2"}
    # hull values win (tighter/preferred), not the bbox ones present in the same file
    assert rq2["local_curvature_gap"]["value"] == 0.2192
    assert rq2["local_road_length_ratio_auto_over_manual"]["value"] == 2.692
    assert rq2["local_auto_footprint_kept_fraction"]["value"] == 0.1096
    assert rq2["whole_map_construction_layers_excluded_from_local_gap"]["value"] is True
    assert rq2["local_building_density_gap"]["value"] == 0.4139
    assert "road_length_gap" not in rq2


def test_rq2_includes_frechet_row_when_evidence_present(tmp_path: Path) -> None:
    """Thesis future-work #14 (discrete Frechet distance, recomputed 2026-08-27 against the
    current local-registration methodology): frechet_distance_local.json, when present,
    contributes a BOUNDED local_frechet_distance_median_m row citing mean/p90/matched-pair
    count in its note."""
    _mk(tmp_path, "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/C14_RQ1_STRUCTURAL_GAP.json", {
        "auto_map": {"path": "auto.xodr", "sha256": "aa" * 32},
        "manual_map": {"path": "manual.xodr", "sha256": "bb" * 32},
        "scores": {"lane_width_gap": 0.04, "curvature_gap": 0.093, "road_length_gap": 1.0,
                   "traffic_light_density_gap": 1.0, "building_density_gap": 0.8, "road_type_coverage_gap": 0.0},
    })
    _mk(tmp_path, "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/local_registration.json", {
        "hull": {"local_structural_summary": _local_structural_summary_payload()},
    })
    _mk(tmp_path, "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/frechet_distance_local.json", {
        "matched_pair_count": 895, "mean_m": 55.28, "median_m": 35.26, "p90_m": 128.01,
        "spacing_m": 5.0, "match_threshold_m": 50.0, "footprint": "hull",
    })
    payload = build_tables(tmp_path)
    rq2 = {r["metric"]: r for r in payload["rows"] if r["rq"] == "RQ2"}
    row = rq2["local_frechet_distance_median_m"]
    assert row["value"] == 35.26
    assert row["status"] == BOUNDED
    assert "55.28" in row["note"] or "55.28" in str(row["note"])  # mean cited
    assert "895" in row["note"]  # matched-pair count cited


def test_rq2_omits_frechet_row_when_evidence_absent(tmp_path: Path) -> None:
    """No frechet_distance_local.json -- row is simply absent (like local_building_density_gap
    when buildings weren't recovered), not forced into an explicit MISSING placeholder; the
    other RQ1 local rows are unaffected."""
    _mk(tmp_path, "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/C14_RQ1_STRUCTURAL_GAP.json", {
        "auto_map": {"path": "auto.xodr", "sha256": "aa" * 32},
        "manual_map": {"path": "manual.xodr", "sha256": "bb" * 32},
        "scores": {},
    })
    _mk(tmp_path, "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/local_registration.json", {
        "hull": {"local_structural_summary": _local_structural_summary_payload()},
    })
    payload = build_tables(tmp_path)
    rq2 = {r["metric"]: r for r in payload["rows"] if r["rq"] == "RQ2"}
    assert "local_frechet_distance_median_m" not in rq2
    assert "local_curvature_gap" in rq2  # unaffected


def test_rq2_falls_back_to_legacy_flat_local_registration_schema(tmp_path: Path) -> None:
    """Pre-C26 local_registration.json had a flat top-level local_structural_summary (no
    hull/bbox nesting) -- must still be read, not silently treated as MISSING."""
    _mk(tmp_path, "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/C14_RQ1_STRUCTURAL_GAP.json", {
        "auto_map": {"path": "auto.xodr", "sha256": "aa" * 32},
        "manual_map": {"path": "manual.xodr", "sha256": "bb" * 32},
        "scores": {"lane_width_gap": 0.04, "curvature_gap": 0.093, "road_length_gap": 1.0,
                   "traffic_light_density_gap": 1.0, "building_density_gap": 0.8, "road_type_coverage_gap": 0.0},
    })
    _mk(tmp_path, "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/local_registration.json", {
        "local_structural_summary": {
            "road_network_structural": {
                "lane_width_gap": 0.0415,
                "curvature_gap": 0.2239,
                "curvature_wasserstein_gap": 0.0642,
                "road_length_ratio_auto_over_manual": 4.5,
                "junction_ratio_auto_over_manual": 6.05,
                "road_count_ratio_auto_over_manual": 6.122,
            },
            "construction_differences_excluded": {
                "reason": "construction layers excluded from local gap",
                "cropped_auto_traffic_lights": 3920,
                "manual_buildings": 993,
            },
            "footprint": {
                "auto_roads_kept": 6079,
                "auto_roads_total": 32297,
                "kept_fraction": 0.1882,
            },
        },
    })
    payload = build_tables(tmp_path)
    rq2 = {r["metric"]: r for r in payload["rows"] if r["rq"] == "RQ2"}
    assert rq2["local_curvature_gap"]["value"] == 0.2239
    assert rq2["local_curvature_wasserstein_gap"]["value"] == 0.0642
    assert rq2["local_road_length_ratio_auto_over_manual"]["value"] == 4.5
    assert rq2["local_auto_footprint_kept_fraction"]["value"] == 0.1882
    assert rq2["whole_map_construction_layers_excluded_from_local_gap"]["value"] is True
    assert "road_length_gap" not in rq2


def test_rq1_determinism_authoritative_when_evidence_present(tmp_path: Path) -> None:
    _mk(tmp_path, "reports/post_audit_hardening/C15_RQ4_DR/C15_RQ4_DOMAIN_RANDOMIZATION.json", {
        "determinism_arm": {"runs": 3, "byte_sha_unique": 3, "structurally_deterministic": True,
                             "finding": "structurally deterministic, byte-varying"},
        "explicit_dr": {"module": "x.py", "apply_n_produces_distinct_variants": 5, "changes_input": True},
    })
    payload = build_tables(tmp_path)
    rq1 = {r["metric"]: r for r in payload["rows"] if r["rq"] == "RQ1"}
    assert rq1["raw_hash_repeatability"]["status"] == AUTHORITATIVE
    assert rq1["structural_signature_repeatability"]["status"] == AUTHORITATIVE
    assert rq1["normalized_hash_repeatability"]["status"] == BOUNDED
    assert rq1["byte_nondeterminism_source"]["status"] == BOUNDED
    assert rq1["raw_hash_repeatability"]["value"] is False
    assert rq1["structural_signature_repeatability"]["value"] is True


def test_rq4_explicit_dr_authoritative_when_evidence_present(tmp_path: Path) -> None:
    """RQ4's explicit_dr_wired row is independent of the GNN row's own
    evidence (which this fixture doesn't provide, so it reports MISSING --
    the two RQ4 metrics have separate evidence sources and separate
    statuses)."""
    _mk(tmp_path, "reports/post_audit_hardening/C15_RQ4_DR/C15_RQ4_DOMAIN_RANDOMIZATION.json", {
        "determinism_arm": {"runs": 3, "byte_sha_unique": 3, "structurally_deterministic": True,
                             "finding": "structurally deterministic, byte-varying"},
        "explicit_dr": {"module": "x.py", "apply_n_produces_distinct_variants": 5, "changes_input": True},
    })
    payload = build_tables(tmp_path)
    rq4 = [r for r in payload["rows"] if r["rq"] == "RQ4"]
    dr_row = next(r for r in rq4 if r["metric"] == "explicit_dr_wired")
    assert dr_row["status"] == AUTHORITATIVE
    assert dr_row["value"] is True
    gnn_row = next(r for r in rq4 if r["metric"] == "gnn_latent_cosine_distance")
    assert gnn_row["status"] == MISSING  # no C18/C21 evidence in this fixture


def test_rq5_deferrals_distinguish_runtime_from_external_data(tmp_path: Path) -> None:
    payload = build_tables(tmp_path)
    rq5 = {r["metric"]: r for r in payload["rows"] if r["rq"] == "RQ5"}
    assert rq5["miou_auto_train_manual_eval"]["status"] == DEFERRED_RUNTIME
    assert rq5["domain_adaptation_coral_mmd"]["status"] == DEFERRED_RUNTIME
    assert rq5["real_unlabeled_shift_metrics"]["status"] == DEFERRED_EXTERNAL_DATA


def test_gnn_row_is_prototype_not_authoritative(tmp_path: Path) -> None:
    _mk(tmp_path, "reports/post_audit_hardening/C18_GNN_LATENT_GAP/gnn_training_report.json", {
        "latent_gap": {
            "metrics": {"cosine_distance": 1.14},
            "encoder": {"checkpoint_md5": "deadbeef"},
        },
    })
    payload = build_tables(tmp_path)
    gnn_row = next(r for r in payload["rows"] if r["metric"] == "gnn_latent_cosine_distance")
    assert gnn_row["rq"] == "RQ4"
    assert gnn_row["status"] == PROTOTYPE
    assert gnn_row["value"] == 1.14


def test_gnn_row_is_authoritative_when_c21_ensemble_ci_excludes_zero(tmp_path: Path) -> None:
    # C21: union-training (both maps' tiles) + 5-seed ensemble supersedes the C18
    # single-run PROTOTYPE result when its CI excludes zero (no-gap).
    _mk(tmp_path, "reports/post_audit_hardening/C18_GNN_LATENT_GAP/gnn_training_report.json", {
        "latent_gap": {"metrics": {"cosine_distance": 1.14}, "encoder": {"checkpoint_md5": "deadbeef"}},
    })
    _mk(tmp_path, "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/aggregate_stats.json", {
        "seeds": [42, 43, 44, 45, 46],
        "cosine_distance": {"values": [1.13, 1.33, 1.17, 1.11, 1.04], "mean": 1.1537, "std": 0.1083,
                             "ci95_bootstrap": [1.0803, 1.2476]},
        "cosine_similarity": {"values": [-0.13, -0.33, -0.17, -0.11, -0.04], "mean": -0.1537, "std": 0.1083,
                               "ci95_bootstrap": [-0.2445, -0.0803]},
        "ci_excludes_zero_similarity": True,
    })
    payload = build_tables(tmp_path)
    gnn_rows = [r for r in payload["rows"] if r["metric"] == "gnn_latent_cosine_distance"]
    assert len(gnn_rows) == 1  # supersedes, does not duplicate, the C18 row
    gnn_row = gnn_rows[0]
    assert gnn_row["status"] == AUTHORITATIVE
    assert gnn_row["value"] == 1.1537
    assert "5" in gnn_row["note"] and "union" in gnn_row["note"].lower()
    # provenance: sha256 must be the REAL hash of the cited artifact (independently
    # re-verifiable by validate_thesis_claim_provenance.py), not left UNPINNED.
    import hashlib
    expected = hashlib.sha256(
        (tmp_path / "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/aggregate_stats.json")
        .read_bytes()
    ).hexdigest()
    assert gnn_row["sha256"] == expected


def test_gnn_row_stays_bounded_when_c21_ensemble_ci_includes_zero(tmp_path: Path) -> None:
    _mk(tmp_path, "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/aggregate_stats.json", {
        "seeds": [42, 43, 44, 45, 46],
        "cosine_distance": {"values": [1.0, 1.0, 1.0, 1.0, 1.0], "mean": 1.0, "std": 0.5,
                             "ci95_bootstrap": [0.5, 1.5]},
        "cosine_similarity": {"values": [0.0] * 5, "mean": 0.0, "std": 0.3, "ci95_bootstrap": [-0.3, 0.3]},
        "ci_excludes_zero_similarity": False,
    })
    payload = build_tables(tmp_path)
    gnn_row = next(r for r in payload["rows"] if r["metric"] == "gnn_latent_cosine_distance")
    assert gnn_row["status"] == BOUNDED


def test_against_real_repo_root_does_not_crash_and_finds_real_evidence() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    payload = build_tables(repo_root)
    assert payload["row_count"] > 0
    curvature_row = next(
        r for r in payload["rows"]
        if r["rq"] == "RQ2" and r["metric"] in {
            "local_curvature_wasserstein_gap",
            "curvature_wasserstein_gap",
            "local_curvature_gap",
            "curvature_gap",
        }
    )
    # Must be a corrected/local value, not the stale 1.0 artifact.
    assert curvature_row["value"] is not None and curvature_row["value"] < 0.5
