"""ultimate_pipeline.config.thesis_rq_contract -- the metric->RQ allow-list
that closes the gap that let the 2026-09 RQ-numbering drift go undetected
(every export_thesis_tables.py row had a valid status, but the wrong RQ
number for its content, and the old audit only checked status validity)."""
from __future__ import annotations

from ultimate_pipeline.config.thesis_rq_contract import (
    ALL_RQS,
    ALLOWED_METRICS,
    RQ_TITLES,
    metric_allowed_for_rq,
)


def test_all_five_thesis_rqs_are_defined():
    assert ALL_RQS == {"RQ1", "RQ2", "RQ3", "RQ4", "RQ5"}
    assert set(RQ_TITLES) == ALL_RQS
    assert set(ALLOWED_METRICS) == ALL_RQS


def test_every_rq_has_at_least_one_allowed_metric():
    for rq in ALL_RQS:
        assert ALLOWED_METRICS[rq], f"{rq} has no allowed metrics"


def test_metric_allowed_for_rq_accepts_correct_pairing():
    assert metric_allowed_for_rq("RQ2", "lane_width_gap") is True
    assert metric_allowed_for_rq("RQ1", "structurally_deterministic") is True
    assert metric_allowed_for_rq("RQ4", "gnn_latent_cosine_distance") is True


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
