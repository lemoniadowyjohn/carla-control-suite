"""
RQ5 training convergence gate tests (protocol v2, batch 12).

The gate's job is narrow: decide whether a run *technically* executed and its
artifacts are internally consistent. These tests assert that it fails on a NaN
loss, a short epoch count, a swapped checkpoint, a partial dataset identity, a
single-class-collapsed model and a checkpoint with missing parameters -- and
that it never claims a scientific verdict either way.

All fixtures are synthetic and carry ``claim_scope = TEST_FIXTURE_ONLY``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ultimate_pipeline.perception.rq5_provenance import (
    build_model_manifest,
    load_model_manifest,
    write_model_manifest,
)
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES
from ultimate_pipeline.perception.training_convergence_gate import (
    CONVERGENCE_SCHEMA,
    PROTOCOL_UNDERPOWERED,
    SCIENTIFIC_NOT_ASSESSED,
    TECHNICAL_FAIL,
    TECHNICAL_INCOMPLETE,
    TECHNICAL_PASS,
    load_convergence_report,
    run_convergence_gate,
    write_convergence_report,
)

torch = pytest.importorskip("torch")

NUM_CLASSES = CARLA_SEMANTIC_NUM_CLASSES


def _model():
    from ultimate_pipeline.perception import train_launcher

    return train_launcher._build_model(NUM_CLASSES)


def _complete_identity(tag: str) -> dict:
    return {
        "schema": "rq5_dataset_identity_v1",
        "identity_sha256": f"{tag}-sha",
        "complete": True,
        "root": f"/datasets/{tag}",
        "camera": "front_left_camera",
        "file_count": 100,
        "digested_file_count": 100,
    }


def _partial_identity(tag: str) -> dict:
    identity = _complete_identity(tag)
    identity["complete"] = False
    identity["digested_file_count"] = 10
    return identity


def _build_run(
    tmp_path: Path,
    *,
    epochs: int = 3,
    train_loss: float = 1.5,
    validation_loss: float = 1.4,
    partial_train_identity: bool = False,
    partial_validation_identity: bool = False,
) -> dict:
    """Materialise a self-consistent (or deliberately defective) run directory."""
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    ckpt = run_dir / "seg_fcn_epoch003.pt"
    torch.save(_model().state_dict(), ckpt)

    manifest = build_model_manifest(
        checkpoint=ckpt,
        train_dataset_identity=(
            _partial_identity("generated_train")
            if partial_train_identity
            else _complete_identity("generated_train")
        ),
        train_roots=["/datasets/generated_train"],
        validation_identity=(
            _partial_identity("generated_validation")
            if partial_validation_identity
            else _complete_identity("generated_validation")
        ),
        test_dataset_identities={
            "generated_test": _complete_identity("generated_test"),
            "manual_test": _complete_identity("manual_test"),
        },
        num_classes=NUM_CLASSES,
        seed=7,
        protocol_path=Path(__file__).resolve().parents[2]
        / "configs"
        / "rq5_protocol_freeze_v2.json",
        class_weighting_policy={"scheme": "median_frequency", "source": "train_split_manifest"},
        determinism={"status": "DETERMINISM_ENFORCED", "strict_determinism_blockers": []},
    )
    write_model_manifest(run_dir, manifest)

    history = {
        "schema": "rq5_training_history_v1",
        "epochs_requested": epochs,
        "epochs_completed": epochs,
        "epochs": [
            {
                "epoch": i + 1,
                "train_loss": train_loss,
                "validation_loss": validation_loss,
                "validation_miou": 0.05,
            }
            for i in range(epochs)
        ],
    }
    (run_dir / "TRAINING_HISTORY.json").write_text(json.dumps(history), encoding="utf-8")
    return {"run_dir": run_dir, "checkpoint": ckpt, "manifest": run_dir / "model_manifest.json"}


def _codes(report) -> set[str]:
    return {c.code for c in report.checks if not c.ok}


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_self_consistent_run_passes_technical_convergence(tmp_path):
    run = _build_run(tmp_path)
    report = run_convergence_gate(
        run_dir=run["run_dir"], expected_epochs=3, expected_seed=7, model_factory=_model
    )
    assert report.technical_status == TECHNICAL_PASS, report.failures
    assert report.scientific_status == SCIENTIFIC_NOT_ASSESSED
    assert report.ok


def test_gate_never_assesses_scientific_performance(tmp_path):
    run = _build_run(tmp_path)
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model)
    payload = report.to_dict()
    assert payload["scientific_performance"]["assessed"] is False
    assert payload["scientific_performance"]["status"] == SCIENTIFIC_NOT_ASSESSED
    blob = json.dumps(payload)
    assert "miou_target" not in blob.lower()


def test_underpowered_outcome_is_named_but_not_auto_escalated(tmp_path):
    run = _build_run(tmp_path)
    report = run_convergence_gate(
        run_dir=run["run_dir"], expected_epochs=3, model_factory=_model
    )
    assert PROTOCOL_UNDERPOWERED in report.observations["note"]
    assert report.technical_status == TECHNICAL_PASS


def test_report_is_serializable_and_schema_checked(tmp_path):
    run = _build_run(tmp_path)
    report = run_convergence_gate(
        run_dir=run["run_dir"], expected_epochs=3, model_factory=_model
    )
    assert report.technical_status == TECHNICAL_PASS, report.failures
    path = write_convergence_report(tmp_path / "evidence", report)
    loaded = load_convergence_report(path)
    assert loaded["schema"] == CONVERGENCE_SCHEMA
    assert loaded["technical_convergence"]["status"] == TECHNICAL_PASS
    bad = path.with_name("bad_schema.json")
    bad.write_text(json.dumps({"schema": "something_else"}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported training convergence schema"):
        load_convergence_report(bad)
    with pytest.raises(FileNotFoundError):
        load_convergence_report(path.with_name("absent.json"))


# ---------------------------------------------------------------------------
# negative controls
# ---------------------------------------------------------------------------


def test_missing_manifest_is_incomplete_never_pass(tmp_path):
    run_dir = tmp_path / "empty"
    run_dir.mkdir()
    report = run_convergence_gate(run_dir=run_dir)
    assert report.technical_status == TECHNICAL_INCOMPLETE
    assert "manifest_present" in _codes(report)
    assert not report.ok


def test_missing_checkpoint_is_incomplete(tmp_path):
    run = _build_run(tmp_path)
    run["checkpoint"].unlink()
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model)
    assert report.technical_status == TECHNICAL_INCOMPLETE
    assert "checkpoint_exists" in _codes(report)


def test_wrong_checkpoint_sha_is_rejected(tmp_path):
    run = _build_run(tmp_path)
    torch.save(_model().state_dict(), run["checkpoint"])  # same bytes budget, different weights
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model)
    assert report.technical_status == TECHNICAL_FAIL
    assert "checkpoint_manifest_binding" in _codes(report)


def test_wrong_dataset_sha_is_rejected(tmp_path):
    run = _build_run(tmp_path)
    report = run_convergence_gate(
        run_dir=run["run_dir"],
        expected_dataset_identities={"generated_train": "not-the-training-split"},
        model_factory=_model,
    )
    assert report.technical_status == TECHNICAL_FAIL
    assert "dataset_identity_match" in _codes(report)


def test_partial_dataset_identity_is_rejected(tmp_path):
    run = _build_run(tmp_path, partial_train_identity=True)
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model)
    assert report.technical_status == TECHNICAL_FAIL
    assert "checkpoint_manifest_binding" in _codes(report)


def test_partial_validation_identity_is_rejected(tmp_path):
    run = _build_run(tmp_path, partial_validation_identity=True)
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model)
    assert report.technical_status == TECHNICAL_FAIL
    assert "checkpoint_manifest_binding" in _codes(report)


def test_nan_training_loss_is_rejected(tmp_path):
    run = _build_run(tmp_path, train_loss=float("nan"))
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model)
    assert report.technical_status == TECHNICAL_FAIL
    assert "train_loss_finite" in _codes(report)


def test_nan_validation_loss_is_rejected(tmp_path):
    run = _build_run(tmp_path, validation_loss=float("inf"))
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model)
    assert report.technical_status == TECHNICAL_FAIL
    assert "validation_loss_finite" in _codes(report)


def test_missing_validation_pass_is_rejected(tmp_path):
    run = _build_run(tmp_path)
    history = json.loads((run["run_dir"] / "TRAINING_HISTORY.json").read_text(encoding="utf-8"))
    for row in history["epochs"]:
        row.pop("validation_loss", None)
    (run["run_dir"] / "TRAINING_HISTORY.json").write_text(json.dumps(history), encoding="utf-8")
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model)
    assert report.technical_status == TECHNICAL_FAIL
    assert "validation_loss_finite" in _codes(report)


def test_short_epoch_count_is_rejected(tmp_path):
    run = _build_run(tmp_path, epochs=2)
    report = run_convergence_gate(
        run_dir=run["run_dir"], expected_epochs=3, model_factory=_model
    )
    assert report.technical_status == TECHNICAL_FAIL
    assert "epochs_completed" in _codes(report)


def test_missing_seed_is_rejected(tmp_path):
    run = _build_run(tmp_path)
    manifest = load_model_manifest(run["manifest"])
    manifest["seed"]["seed"] = None
    (run["manifest"]).write_text(json.dumps(manifest), encoding="utf-8")
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model)
    assert report.technical_status == TECHNICAL_FAIL
    assert {"seed_contract", "checkpoint_manifest_binding"} & _codes(report)


def test_wrong_seed_is_rejected(tmp_path):
    run = _build_run(tmp_path)
    report = run_convergence_gate(
        run_dir=run["run_dir"], expected_seed=17, model_factory=_model
    )
    assert report.technical_status == TECHNICAL_FAIL
    assert "seed_contract" in _codes(report)


def test_checkpoint_with_missing_parameters_is_rejected(tmp_path):
    run = _build_run(tmp_path)
    state = dict(torch.load(run["checkpoint"], map_location="cpu", weights_only=True))
    victim = sorted(state)[0]
    del state[victim]
    torch.save(state, run["checkpoint"])
    # Re-bind the manifest so the *only* remaining defect is the missing tensor.
    manifest = build_model_manifest(
        checkpoint=run["checkpoint"],
        train_dataset_identity=_complete_identity("generated_train"),
        train_roots=["/datasets/generated_train"],
        validation_identity=_complete_identity("generated_validation"),
        num_classes=NUM_CLASSES,
        seed=7,
    )
    write_model_manifest(run["run_dir"], manifest)

    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model)
    assert report.technical_status == TECHNICAL_FAIL
    assert "model_loads_completely" in _codes(report)


def test_single_class_collapsed_model_fixture_is_rejected(tmp_path):
    run = _build_run(tmp_path)

    def _collapsed(_model_obj):
        return np.full(64, 4, dtype=np.int64)

    report = run_convergence_gate(
        run_dir=run["run_dir"], model_factory=_model, prediction_probe=_collapsed
    )
    assert report.technical_status == TECHNICAL_FAIL
    assert "prediction_not_single_class" in _codes(report)


def test_model_load_and_collapse_checks_cannot_silently_pass(tmp_path):
    run = _build_run(tmp_path)
    report = run_convergence_gate(run_dir=run["run_dir"])
    assert report.technical_status == TECHNICAL_FAIL
    assert {"model_loads_completely", "prediction_not_single_class"} <= _codes(report)


def test_validation_selecting_checkpoint_policy_is_rejected(tmp_path):
    run = _build_run(tmp_path)
    manifest = load_model_manifest(run["manifest"])
    manifest["checkpoint"]["policy"]["validation_selects_epoch"] = True
    (run["manifest"]).write_text(json.dumps(manifest), encoding="utf-8")
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model)
    assert report.technical_status == TECHNICAL_FAIL
    assert "checkpoint_policy_final_epoch" in _codes(report)


def test_manifest_without_protocol_binding_is_rejected(tmp_path):
    run = _build_run(tmp_path)
    manifest = load_model_manifest(run["manifest"])
    manifest["protocol"] = {}
    (run["manifest"]).write_text(json.dumps(manifest), encoding="utf-8")
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model)
    assert report.technical_status == TECHNICAL_FAIL
    assert "checkpoint_manifest_binding" in _codes(report)