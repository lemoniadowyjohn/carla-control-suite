"""GAP-034 -- RQ5(b) claim-boundary must be code-enforced, not just documented.

Rule (docs/research/THESIS_TO_CURRENT_PROGRESS.md, RQ5 row;
research/thesis_rq_contract.yaml claim_boundaries.RQ5): if RQ5(b) is ever
evaluated against real-world (non-synthetic/CARLA) data that is unlabeled,
the allowed claim vocabulary is restricted to domain-shift /
representation-shift language (entropy, confidence, feature-distribution
shift, FID-like metrics, uncertainty, CORAL/MMD) -- NOT accuracy, mIoU,
pixel accuracy, or any other metric that requires ground-truth labels.

RED (pre-fix): a synthetic RQ5(b) row tagged real-world/unlabeled carrying
an accuracy metric passes _current_rq_tables_audit with no claim-boundary
violation, and build_tables() emits RQ5 rows with no data_source /
labels_available tags at all.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.export_thesis_tables import build_tables
from ultimate_pipeline.config.thesis_rq_contract import (
    rq5_claim_boundary_ok,
    rq5_claim_boundary_violation,
)
from ultimate_pipeline.tools.audit_thesis_topic_contract import _current_rq_tables_audit


def _write_rq_tables(root: Path, rows: list) -> None:
    p = root / "reports" / "post_audit_hardening" / "C19_THESIS_ASSEMBLY" / "rq_tables.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"rows": rows, "counts_by_status": {}}), encoding="utf-8")


def _base_rows() -> list:
    """Minimal all-RQ coverage so only the RQ5(b) row under test can violate."""
    return [
        {"rq": "RQ1", "metric": "natural_dr_present", "status": "AUTHORITATIVE", "note": "measured"},
        {"rq": "RQ2", "metric": "lane_width_gap", "status": "BOUNDED", "note": "fine"},
        {"rq": "RQ3", "metric": "perceptual_gap", "status": "DEFERRED_RUNTIME", "note": "blocked on CARLA"},
        {"rq": "RQ4", "metric": "gnn_latent_cosine_distance", "status": "BOUNDED", "note": "prototype result"},
    ]


def _rq5b_row(metric: str, **extra) -> dict:
    row = {
        "rq": "RQ5",
        "metric": metric,
        "status": "AUTHORITATIVE",
        "note": "evaluated on real-world Ingolstadt images",
        "value": 0.61,
        "data_source": "real_world",
        "labels_available": False,
    }
    row.update(extra)
    return row


def test_rq5b_accuracy_on_unlabeled_real_world_is_rejected(tmp_path: Path) -> None:
    """The core GAP-034 case: labeled-only metric on real-world unlabeled
    data must fail the audit closed, not pass silently."""
    _write_rq_tables(tmp_path, _base_rows() + [
        _rq5b_row("generated_train_manual_test_accuracy"),
    ])
    result = _current_rq_tables_audit(tmp_path)
    assert result["ok"] is False
    assert any("claim-boundary" in v and "RQ5" in v for v in result["violations"]), (
        f"expected an RQ5(b) claim-boundary violation, got: {result['violations']}"
    )


def test_rq5b_generic_accuracy_names_are_rejected(tmp_path: Path) -> None:
    """Bare 'accuracy' / 'mIoU' / 'pixel_accuracy' vocabulary must also fail
    closed on real-world unlabeled data ('or similar' in the rule)."""
    for metric in ("accuracy", "mIoU", "pixel_accuracy"):
        _write_rq_tables(tmp_path, _base_rows() + [_rq5b_row(metric)])
        result = _current_rq_tables_audit(tmp_path)
        assert result["ok"] is False, f"metric {metric!r} passed when it should fail closed"
        assert any("claim-boundary" in v for v in result["violations"]), (
            f"metric {metric!r}: expected a claim-boundary violation, got: {result['violations']}"
        )


def test_rq5b_allowed_shift_metric_still_passes(tmp_path: Path) -> None:
    """Guard against over-blocking: a genuinely-allowed unlabeled-shift
    metric on the same real-world unlabeled data must still pass."""
    for metric in ("real_unlabeled_shift_metrics", "domain_adaptation_coral_mmd"):
        _write_rq_tables(tmp_path, _base_rows() + [_rq5b_row(metric)])
        result = _current_rq_tables_audit(tmp_path)
        assert not any("claim-boundary" in v for v in result["violations"]), (
            f"metric {metric!r}: wrongly flagged, violations: {result['violations']}"
        )
        assert result["ok"] is True, result["violations"]


def test_rq5b_labeled_metric_allowed_when_labels_exist(tmp_path: Path) -> None:
    """Real-world data WITH ground-truth labels may still carry accuracy --
    the rule restricts the unlabeled case only."""
    _write_rq_tables(tmp_path, _base_rows() + [
        _rq5b_row("generated_train_manual_test_accuracy", labels_available=True),
    ])
    result = _current_rq_tables_audit(tmp_path)
    assert not any("claim-boundary" in v for v in result["violations"]), result["violations"]
    assert result["ok"] is True, result["violations"]


def test_rq5a_labeled_sim_metric_still_passes(tmp_path: Path) -> None:
    """RQ5(a) [labeled, CARLA-paired] accuracy claims are unaffected."""
    _write_rq_tables(tmp_path, _base_rows() + [
        {
            "rq": "RQ5",
            "metric": "miou_auto_train_manual_eval",
            "status": "BOUNDED",
            "note": "manual Grid0828 holdout, labels available",
            "value": 0.55,
            "data_source": "sim_labeled",
            "labels_available": True,
        },
    ])
    result = _current_rq_tables_audit(tmp_path)
    assert result["ok"] is True, result["violations"]


def test_export_tags_rq5_rows_with_source_and_label_provenance(tmp_path: Path) -> None:
    """build_tables() must tag every RQ5 row with the data_source /
    labels_available provenance the audit enforces on -- otherwise the
    boundary has nothing to bite on at the reporting origin."""
    payload = build_tables(tmp_path)
    rq5 = {r["metric"]: r for r in payload["rows"] if r["rq"] == "RQ5"}
    assert rq5, "no RQ5 rows exported at all"
    for metric, row in rq5.items():
        assert "data_source" in row and row["data_source"], (
            f"RQ5/{metric}: missing data_source tag"
        )
        assert "labels_available" in row and row["labels_available"] is not None, (
            f"RQ5/{metric}: missing labels_available tag"
        )
    rq5b = rq5["real_unlabeled_shift_metrics"]
    assert rq5b["data_source"] == "real_world"
    assert rq5b["labels_available"] is False


def test_contract_unknown_metric_on_unlabeled_real_world_fails_closed() -> None:
    """Fail-closed on the metric axis: a brand-new, unrecognized metric name
    on real-world unlabeled data is rejected, not defaulted to permissive."""
    assert rq5_claim_boundary_ok(
        "some_future_accuracy_variant", data_source="real_world", labels_available=False
    ) is False
    assert rq5_claim_boundary_violation(
        "some_future_accuracy_variant", data_source="real_world", labels_available=False
    ) is not None


def test_contract_missing_labels_proof_on_real_world_fails_closed() -> None:
    """Fail-closed on the provenance axis: a real-world row that does not
    positively prove labels exist (None/missing) is treated as unlabeled."""
    assert rq5_claim_boundary_ok(
        "generated_train_manual_test_accuracy", data_source="real_world"
    ) is False
    assert rq5_claim_boundary_ok(
        "generated_train_manual_test_accuracy",
        data_source="real_world",
        labels_available=None,
    ) is False


def test_contract_matching_is_case_and_separator_insensitive() -> None:
    assert rq5_claim_boundary_ok("MIOU", data_source="Real-World", labels_available=False) is False
    assert rq5_claim_boundary_ok(
        "ENTROPY_MEAN", data_source="real_world", labels_available=False
    ) is True
    assert rq5_claim_boundary_violation(
        "real_unlabeled_shift_metrics", data_source="real_world", labels_available=False
    ) is None


def test_contract_non_real_world_rows_defer_to_base_allow_list() -> None:
    """No source claim, or a labeled/sim source, keeps the legacy behavior:
    any RQ5 allow-listed metric passes, off-list metrics fail as before."""
    assert rq5_claim_boundary_ok("generated_train_manual_test_accuracy") is True
    assert rq5_claim_boundary_ok("lane_width_gap") is False  # RQ2 metric, not RQ5
    assert rq5_claim_boundary_ok(
        "generated_train_manual_test_accuracy",
        data_source="sim_labeled",
        labels_available=True,
    ) is True
