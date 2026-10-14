"""Authoritative thesis RQ definitions and per-RQ allowed metric names.

Source of truth: submission/thesis_source/Chapter1/chap1.tex, lines 24-28.
    RQ1 -- Determinism: OSM->OpenDRIVE pipeline structural/topological
           stability and the origin of byte-level nondeterminism.
    RQ2 -- Structural domain gap: automatic OSM map vs. a manually modeled
           CARLA map of the same region.
    RQ3 -- Perceptual domain gap: how structural differences shift
           perception outputs under an identical sensor rig/route protocol.
    RQ4 -- Structural variability and latent representation: does repeated
           generation introduce measurable structural variability, and can
           a latent representation support robustness analysis.
    RQ5 -- Generalization and transfer: do perception models trained on
           generated maps generalize to (a) the manual simulated map and
           (b) unlabeled real-world data.

Why this exists: tools/export_thesis_tables.py's row-generation functions
used a DRIFTED numbering until 2026-09-06 (structural gap tagged "RQ1",
perceptual gap tagged "RQ2", GNN latent work tagged "RQ3/RQ5") -- a full
one-number shift for RQ1-3 plus a mislabeled RQ4/RQ5. The drift went
undetected because ultimate_pipeline/tools/audit_thesis_topic_contract.py's
_current_rq_tables_audit() only checked that each row had *some* valid
status, never that its metric was semantically the right one for its
claimed RQ number. This module is the missing piece: an explicit
metric->RQ allow-list that audit_thesis_topic_contract.py validates rows
against, so a future relabeling drift fails the audit instead of silently
matching the review's own manual-inspection standard again.
"""
from __future__ import annotations

from typing import Dict, FrozenSet

RQ1 = "RQ1"
RQ2 = "RQ2"
RQ3 = "RQ3"
RQ4 = "RQ4"
RQ5 = "RQ5"

RQ_TITLES: Dict[str, str] = {
    RQ1: "Determinism",
    RQ2: "Structural domain gap",
    RQ3: "Perceptual domain gap",
    RQ4: "Structural variability and latent representation",
    RQ5: "Generalization and transfer",
}

RQ_QUESTIONS: Dict[str, str] = {
    RQ1: "Does the OSM→OpenDRIVE pipeline preserve stable structural and topological signatures under fixed inputs, and where does byte-level nondeterminism arise?",
    RQ2: "How do automatically generated OSM-based CARLA maps differ structurally from a manually modeled CARLA map of the same region?",
    RQ3: "How do those structural differences shift perception outputs when an identical sensor rig and route protocol are used?",
    RQ4: "Does repeated automatic generation from the same pinned inputs introduce measurable structural variability, and can a latent representation of that variability support robustness analysis?",
    RQ5: (
        "To what extent do perception models trained on automatically generated maps generalize to:\n"
        "(a) a manually simulated map, and\n"
        "(b) unlabeled real-world data?"
    ),
}

ALL_RQS: FrozenSet[str] = frozenset(RQ_TITLES)

# Canonical thesis metrics plus explicitly mapped repository-local aliases emitted
# by tools/export_thesis_tables.py. Aliases are kept only when their semantic RQ is
# unambiguous; wrong-RQ pairings still fail closed.
ALLOWED_METRICS: Dict[str, FrozenSet[str]] = {
    RQ1: frozenset({
        "raw_hash_repeatability",
        "normalized_hash_repeatability",
        "structural_signature_repeatability",
        "byte_nondeterminism_source",
        "natural_dr_present",
        "structurally_deterministic",
    }),
    RQ2: frozenset({
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
        "structural_gap_composite",
        "road_length_gap",
        "traffic_light_density_gap",
        "road_type_coverage_gap",
        "local_lane_width_gap",
        "local_curvature_gap",
        "local_curvature_wasserstein_gap",
        "local_road_length_ratio_auto_over_manual",
        "local_junction_ratio_auto_over_manual",
        "local_road_count_ratio_auto_over_manual",
        "local_auto_footprint_kept_fraction",
        "whole_map_construction_layers_excluded_from_local_gap",
        "whole_map_road_type_coverage_gap_context",
        "local_building_density_gap",
        "local_frechet_distance_median_m",
    }),
    RQ3: frozenset({
        "paired_camera_distribution_shift",
        "paired_lidar_distribution_shift",
        "semantic_sensor_distribution_shift",
        "paired_sensor_domain_metrics",
        "perceptual_gap",
    }),
    RQ4: frozenset({
        "structural_coefficient_of_variation",
        "natural_structural_variability",
        "GNN_latent_distance",
        "GNN_collapse_diagnostics",
        "k_sweep",
        "explicit_domain_randomization",
        "gnn_latent_cosine_distance",
        "explicit_dr_wired",
    }),
    RQ5: frozenset({
        "generated_train_generated_test_accuracy",
        "generated_train_manual_test_accuracy",
        "mIoU_transfer_degradation",
        "per_class_target_IoU",
        "real_world_model_transfer_evaluation",
        "miou_auto_train_manual_eval",
        "domain_adaptation_coral_mmd",
        "real_unlabeled_shift_metrics",
    }),
}


def metric_allowed_for_rq(rq: str, metric: str) -> bool:
    """True if `metric` is a recognized, contract-allowed metric for `rq`.

    Unknown RQ tags (e.g. a stale combined "RQ3/RQ5", or a typo) are never
    allowed -- this must fail closed, not default to permissive.
    """
    return metric in ALLOWED_METRICS.get(rq, frozenset())


# ---------------------------------------------------------------------------
# RQ5(b) claim-boundary (GAP-034).
#
# Rule (docs/research/THESIS_TO_CURRENT_PROGRESS.md, RQ5 row;
# research/thesis_rq_contract.yaml claim_boundaries.RQ5): RQ5 splits into
#   (a) labeled, CARLA-paired manual-sim evaluation, and
#   (b) potentially-unlabeled real-world evaluation.
# If RQ5(b) is ever evaluated against real-world data that is UNLABELED,
# the allowed claim vocabulary is restricted to domain-shift /
# representation-shift language -- NOT accuracy, mIoU, pixel accuracy, or
# any other metric that requires ground-truth labels.
#
# ALLOWED_METRICS[RQ5] above deliberately still lists both families side by
# side (it answers "is this metric an RQ5 metric at all", i.e. the RQ-label
# drift check). The partition below answers the stricter question "may this
# metric be claimed on real-world data WITHOUT ground-truth labels", and
# audit_thesis_topic_contract.py enforces it fail-closed on every exported
# RQ5 row that declares a real-world, unlabeled provenance.
# ---------------------------------------------------------------------------

#: RQ5 metrics that require ground-truth labels (accuracy / IoU family).
#: Claiming any of these on unlabeled data is a claim-boundary violation.
#: Includes the bare vocabulary names emitted by the eval entrypoints
#: (eval_sim_labeled emits "mIoU"/"pixel_accuracy"/"per_class_iou") so the
#: check bites on raw pipeline vocabulary, not just contract aliases.
RQ5_LABELED_ONLY_METRICS: FrozenSet[str] = frozenset({
    "generated_train_generated_test_accuracy",
    "generated_train_manual_test_accuracy",
    "mIoU_transfer_degradation",
    "per_class_target_IoU",
    "real_world_model_transfer_evaluation",
    "miou_auto_train_manual_eval",
    "accuracy",
    "mIoU",
    "mean_iou",
    "pixel_accuracy",
    "per_class_iou",
})

#: RQ5 metrics expressible WITHOUT ground-truth labels: prediction
#: uncertainty / confidence and sim-vs-real feature-distribution shift
#: (entropy, confidence, CORAL/MMD alignment, FID-like Frechet distances).
#: This is the complete allow-list for RQ5(b)-unlabeled claims -- anything
#: not on it (including brand-new, unrecognized metric names) is rejected
#: on real-world unlabeled data. Fail closed, not fail open.
RQ5_UNLABELED_SHIFT_METRICS: FrozenSet[str] = frozenset({
    "real_unlabeled_shift_metrics",
    "domain_adaptation_coral_mmd",
    "entropy_mean",
    "entropy_std",
    "confidence_mean",
    "confidence_std",
    "frechet_pooled_logits",
    "coral",
    "mmd",
})

#: Normalized data_source tags that count as "real-world (non-synthetic,
#: non-CARLA)" for the boundary. Comparison is case-insensitive with
#: "-", "_", and whitespace ignored.
RQ5_REAL_WORLD_SOURCES: FrozenSet[str] = frozenset({
    "realworld",
    "real",
    "real_world_data",
    "realworlddingolstadt",
})


def _normalize_claim_token(token: object) -> str:
    return "".join(ch for ch in str(token).lower() if ch.isalnum())


def _is_real_world_source(data_source: object) -> bool:
    normalized = _normalize_claim_token(data_source or "")
    if not normalized:
        return False
    if normalized in RQ5_REAL_WORLD_SOURCES:
        return True
    # Fail-closed on the source axis too: any source tag that *mentions*
    # real-world counts as real-world even if it is not in the known set
    # (e.g. "real_world_holdout_v2").
    return "realworld" in normalized


def rq5_claim_boundary_ok(
    metric: str,
    *,
    data_source: object = "",
    labels_available: object = None,
) -> bool:
    """Fail-closed RQ5(b) claim-boundary check (GAP-034).

    - Rows NOT sourced from real-world data (RQ5(a) CARLA-paired, synthetic,
      or no source claim at all) defer to the base metric->RQ allow-list.
    - Rows sourced from real-world data WITH ground-truth labels
      (labels_available is True) likewise defer to the base allow-list.
    - Rows sourced from real-world data WITHOUT ground-truth labels
      (labels_available False, None, or any non-True value -- an unlabeled
      claim must positively prove labels exist) may only carry metrics in
      RQ5_UNLABELED_SHIFT_METRICS. Unknown metric names are rejected.
    """
    if not _is_real_world_source(data_source):
        return metric_allowed_for_rq(RQ5, metric)
    if labels_available is True:
        return metric_allowed_for_rq(RQ5, metric)
    return _normalize_claim_token(metric) in {
        _normalize_claim_token(m) for m in RQ5_UNLABELED_SHIFT_METRICS
    }


def rq5_claim_boundary_violation(
    metric: str,
    *,
    data_source: object = "",
    labels_available: object = None,
) -> str | None:
    """Human-readable violation, or None when the claim is allowed."""
    if rq5_claim_boundary_ok(
        metric, data_source=data_source, labels_available=labels_available
    ):
        return None
    return (
        f"RQ5(b) claim-boundary violation: metric {metric!r} requires "
        "ground-truth labels but the result is sourced from real-world data "
        f"(data_source={data_source!r}) with labels_available={labels_available!r}. "
        "On unlabeled real-world data only domain-shift/representation-shift "
        "metrics are allowed "
        f"({sorted(RQ5_UNLABELED_SHIFT_METRICS)}); accuracy, mIoU, "
        "pixel_accuracy, and per-class IoU must not be reported."
    )
