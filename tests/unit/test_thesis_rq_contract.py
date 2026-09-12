"""ultimate_pipeline.config.thesis_rq_contract -- the metric->RQ allow-list
that closes the gap that let the 2026-09 RQ-numbering drift go undetected
(every export_thesis_tables.py row had a valid status, but the wrong RQ
number for its content, and the old audit only checked status validity)."""
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.config.thesis_rq_contract import (
    ALL_RQS,
    ALLOWED_METRICS,
    RQ_QUESTIONS,
    RQ_TITLES,
    metric_allowed_for_rq,
)


def test_yaml_contract_file_contains_immutable_rq_authority():
    repo_root = Path(__file__).resolve().parents[2]
    text = (repo_root / "research" / "thesis_rq_contract.yaml").read_text(encoding="utf-8")
    normalized_text = "\n".join(line.strip() for line in text.splitlines())
    for question in RQ_QUESTIONS.values():
        for line in question.splitlines():
            assert line in normalized_text
    for status in (
        "AUTHORITATIVE",
        "BOUNDED",
        "PROTOTYPE",
        "DEFERRED_RUNTIME",
        "DEFERRED_EXTERNAL_DATA",
        "SUPERSEDED",
        "NOT_RUN",
    ):
        assert status in text


def test_all_five_thesis_rqs_are_defined():
    assert ALL_RQS == {"RQ1", "RQ2", "RQ3", "RQ4", "RQ5"}
    assert set(RQ_TITLES) == ALL_RQS
    assert set(RQ_QUESTIONS) == ALL_RQS
    assert set(ALLOWED_METRICS) == ALL_RQS


def test_every_rq_has_at_least_one_allowed_metric():
    for rq in ALL_RQS:
        assert ALLOWED_METRICS[rq], f"{rq} has no allowed metrics"


def test_metric_allowed_for_rq_accepts_correct_pairing():
    assert metric_allowed_for_rq("RQ2", "lane_width_gap") is True
    assert metric_allowed_for_rq("RQ1", "structural_signature_repeatability") is True
    assert metric_allowed_for_rq("RQ4", "gnn_latent_cosine_distance") is True


def test_canonical_minimum_metric_names_are_mapped_to_thesis_rqs():
    expected = {
        "RQ1": {
            "raw_hash_repeatability",
            "normalized_hash_repeatability",
            "structural_signature_repeatability",
            "byte_nondeterminism_source",
        },
        "RQ2": {
            "lane_width_gap",
            "curvature_gap",
            "curvature_wasserstein_gap",
            "road_count_ratio",
            "road_length_ratio",
            "junction_ratio",
            "building_density_gap",
            "frechet_distance",
            "connectivity_gap",
            "semantic_object_gap",
        },
        "RQ3": {
            "paired_camera_distribution_shift",
            "paired_lidar_distribution_shift",
            "semantic_sensor_distribution_shift",
            "paired_sensor_domain_metrics",
        },
        "RQ4": {
            "structural_coefficient_of_variation",
            "natural_structural_variability",
            "GNN_latent_distance",
            "GNN_collapse_diagnostics",
            "k_sweep",
            "explicit_domain_randomization",
        },
        "RQ5": {
            "generated_train_generated_test_accuracy",
            "generated_train_manual_test_accuracy",
            "mIoU_transfer_degradation",
            "per_class_target_IoU",
            "real_world_model_transfer_evaluation",
        },
    }
    for rq, metrics in expected.items():
        assert metrics <= ALLOWED_METRICS[rq]


def test_metric_allowed_for_rq_rejects_the_real_2026_09_drift():
    """The actual mismatches this contract exists to catch, verbatim from
    export_thesis_tables.py before the 2026-09-06 relabel."""
    assert metric_allowed_for_rq("RQ1", "lane_width_gap") is False  # was mistagged "RQ1"
    assert metric_allowed_for_rq("RQ2", "perceptual_gap") is False  # was mistagged "RQ2"
    assert metric_allowed_for_rq("RQ3/RQ5", "gnn_latent_cosine_distance") is False  # combined tag
    assert metric_allowed_for_rq("RQ4", "natural_dr_present") is False  # determinism, belongs to RQ1


def test_metric_allowed_for_rq_rejects_unknown_rq_tag():
    assert metric_allowed_for_rq("RQ9", "anything") is False


def test_no_metric_name_is_shared_across_two_rqs():
    """Cross-RQ metric collisions would make drift detection ambiguous."""
    seen: dict[str, str] = {}
    for rq, metrics in ALLOWED_METRICS.items():
        for metric in metrics:
            assert metric not in seen, f"{metric!r} claimed by both {seen.get(metric)} and {rq}"
            seen[metric] = rq
