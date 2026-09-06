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

ALL_RQS: FrozenSet[str] = frozenset(RQ_TITLES)

# Metric names as emitted by tools/export_thesis_tables.py's row builders.
ALLOWED_METRICS: Dict[str, FrozenSet[str]] = {
    RQ1: frozenset({
        "natural_dr",
        "natural_dr_present",
        "structurally_deterministic",
    }),
    RQ2: frozenset({
        "structural_gap_composite",
        "lane_width_gap",
        "curvature_gap",
        "curvature_wasserstein_gap",
        "road_length_gap",
        "traffic_light_density_gap",
        "building_density_gap",
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
        "perceptual_gap",
    }),
    RQ4: frozenset({
        "gnn_latent_cosine_distance",
        "explicit_dr_wired",
    }),
    RQ5: frozenset({
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
