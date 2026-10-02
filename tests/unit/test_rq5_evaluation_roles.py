"""
RQ5 evaluation role authority tests (protocol v2 section 14).

Final evaluation has three roles and they must never be merged:

* ``generated_test`` / ``manual_test`` -- ground truth exists, accuracy is legal,
  but the dataset and checkpoint identities must match what was requested;
* ``real_unlabeled`` -- no ground truth, so only entropy / confidence /
  CORAL / MMD / FID-like shift measures are permitted, and never as accuracy.

These tests are about the *contract*, not about any particular dataset.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ultimate_pipeline.perception.rq5_provenance import (
    EVALUATION_ROLES,
    EvaluationRoleError,
    REAL_UNLABELED_SHIFT_METRICS,
    assert_labeled_evaluation_bound,
    assert_unlabeled_metrics_are_shift_only,
    build_model_manifest,
    evaluation_role_contract,
    protocol_identity,
    write_model_manifest,
)
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES

torch = pytest.importorskip("torch")

PROTOCOL = Path(__file__).resolve().parents[2] / "configs" / "rq5_protocol_freeze_v2.json"


def _identity(tag: str) -> dict:
    return {
        "schema": "rq5_dataset_identity_v1",
        "identity_sha256": f"{tag}-sha",
        "complete": True,
        "root": f"/datasets/{tag}",
        "camera": "front_left_camera",
        "file_count": 10,
        "digested_file_count": 10,
    }


def _run(tmp_path: Path, *, complete: bool = True) -> tuple[Path, Path]:
    from ultimate_pipeline.perception import train_launcher

    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    ckpt = run_dir / "seg_fcn_epoch003.pt"
    torch.save(
        train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES).state_dict(), ckpt
    )
    identity = _identity("generated_train")
    if not complete:
        identity["complete"] = False
        identity["digested_file_count"] = 2
    manifest = build_model_manifest(
        checkpoint=ckpt,
        train_dataset_identity=identity,
        train_roots=["/datasets/generated_train"],
        validation_identity=_identity("generated_validation"),
        test_dataset_identities={
            "generated_test": _identity("generated_test"),
            "manual_test": _identity("manual_test"),
        },
        num_classes=CARLA_SEMANTIC_NUM_CLASSES,
        seed=7,
        protocol_path=PROTOCOL,
    )
    write_model_manifest(run_dir, manifest)
    return ckpt, run_dir / "model_manifest.json"


# ---------------------------------------------------------------------------
# role contracts
# ---------------------------------------------------------------------------


def test_all_three_evaluation_roles_are_governed():
    assert EVALUATION_ROLES == ("generated_test", "manual_test", "real_unlabeled")


def test_unknown_evaluation_role_is_rejected():
    with pytest.raises(EvaluationRoleError, match="unknown evaluation role"):
        evaluation_role_contract("whatever_i_want")


def test_labeled_roles_permit_accuracy_metrics():
    for role in ("generated_test", "manual_test"):
        contract = evaluation_role_contract(role)
        assert contract["labeled"] is True
        assert contract["accuracy_claim_allowed"] is True
        assert contract["requires_dataset_identity"] is True


def test_unlabeled_role_permits_only_shift_measures():
    contract = evaluation_role_contract("real_unlabeled")
    assert contract["labeled"] is False
    assert contract["accuracy_claim_allowed"] is False
    assert contract["accuracy_metrics_allowed"] is False
    assert set(contract["allowed_metric_families"]) == set(REAL_UNLABELED_SHIFT_METRICS)
    assert not ({"mIoU", "pixel_accuracy"} & set(contract["allowed_metric_families"]))


def test_real_unlabeled_report_with_accuracy_metrics_is_rejected():
    for payload in (
        {"entropy_mean": 0.5, "mIoU": 0.42},
        {"confidence_mean": 0.3, "pixel_accuracy": 0.9},
        {"shift": {"coral": 1.2}, "iou": 0.4},
        {"entropy_mean": 0.5, "accuracy_metrics_available": True},
    ):
        with pytest.raises(EvaluationRoleError):
            assert_unlabeled_metrics_are_shift_only(payload)


def test_real_unlabeled_shift_only_report_is_accepted():
    payload = {"entropy_mean": 0.9, "confidence_mean": 0.2, "coral_distance": 1.4, "n": 42}
    report = assert_unlabeled_metrics_are_shift_only(payload)
    assert report["role"] == "real_unlabeled"
    assert report["contract"]["accuracy_claim_allowed"] is False
    assert set(payload) <= set(report["observed_keys"])


def test_unlabeled_role_cannot_be_bound_as_labeled_evaluation(tmp_path):
    ckpt, manifest = _run(tmp_path)
    with pytest.raises(EvaluationRoleError, match="unlabeled"):
        assert_labeled_evaluation_bound(
            "real_unlabeled", checkpoint=ckpt, manifest=manifest
        )


# ---------------------------------------------------------------------------
# labeled-sim binding
# ---------------------------------------------------------------------------


def test_labeled_evaluation_binds_when_identities_match(tmp_path):
    ckpt, manifest = _run(tmp_path)
    result = assert_labeled_evaluation_bound(
        "generated_test",
        checkpoint=ckpt,
        manifest=manifest,
        expected_dataset_identity_sha256="generated_test-sha",
    )
    assert result["role"] == "generated_test"
    assert result["dataset_identity_sha256"] == "generated_test-sha"


def test_labeled_evaluation_rejects_the_wrong_dataset(tmp_path):
    ckpt, manifest = _run(tmp_path)
    with pytest.raises(EvaluationRoleError, match="dataset identity mismatch"):
        assert_labeled_evaluation_bound(
            "generated_test",
            checkpoint=ckpt,
            manifest=manifest,
            expected_dataset_identity_sha256="some-other-dataset",
        )


def test_labeled_evaluation_rejects_the_wrong_checkpoint(tmp_path):
    ckpt, manifest = _run(tmp_path)
    with pytest.raises(EvaluationRoleError, match="checkpoint identity mismatch"):
        assert_labeled_evaluation_bound(
            "manual_test",
            checkpoint=ckpt,
            manifest=manifest,
            expected_checkpoint_sha256="deadbeef",
        )


def test_labeled_evaluation_rejects_an_unbound_role(tmp_path):
    """A role the manifest does not bind must not be evaluated under that name."""
    from ultimate_pipeline.perception import train_launcher

    run_dir = tmp_path / "run_partial"
    run_dir.mkdir(parents=True)
    ckpt = run_dir / "seg_fcn_epoch003.pt"
    torch.save(train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES).state_dict(), ckpt)
    # Only generated_test is bound; manual_test is deliberately absent.
    write_model_manifest(
        run_dir,
        build_model_manifest(
            checkpoint=ckpt,
            train_dataset_identity=_identity("generated_train"),
            train_roots=["/datasets/generated_train"],
            test_dataset_identities={"generated_test": _identity("generated_test")},
            num_classes=CARLA_SEMANTIC_NUM_CLASSES,
            seed=7,
            protocol_path=PROTOCOL,
        ),
    )
    manifest = run_dir / "model_manifest.json"
    with pytest.raises(EvaluationRoleError, match="checkpoint provenance is incomplete"):
        assert_labeled_evaluation_bound(
            "manual_test",
            checkpoint=ckpt,
            manifest=manifest,
            expected_dataset_identity_sha256="manual_test-sha",
        )


def test_labeled_evaluation_rejects_an_incomplete_training_identity(tmp_path):
    ckpt, manifest = _run(tmp_path, complete=False)
    with pytest.raises(EvaluationRoleError, match="incomplete or absent dataset identities"):
        assert_labeled_evaluation_bound(
            "generated_test", checkpoint=ckpt, manifest=manifest
        )


def test_evaluation_roles_are_recorded_in_the_frozen_protocol():
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    decision = payload["decisions"]["evaluation_roles"]["value"]
    for role in EVALUATION_ROLES:
        assert role in decision
    assert "never accuracy" in decision
    assert protocol_identity(PROTOCOL)["sha256"] == protocol_identity()["sha256"]