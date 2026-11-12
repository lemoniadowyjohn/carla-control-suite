"""V121: reused checkpoints cannot be counted as newly trained K-map experiments."""
from __future__ import annotations

import argparse

import pytest

from ultimate_pipeline import run_generalization_experiments as rq5


@pytest.mark.parametrize("skip_training", [True, False])
def test_checkpoint_reuse_never_emits_new_training_success(
    tmp_path, monkeypatch, skip_training
):
    eval_dir = tmp_path / "manual_eval"
    real_dir = tmp_path / "real_unlabeled"
    eval_dir.mkdir()
    real_dir.mkdir()
    model_path = tmp_path / "previous_checkpoint.pt"
    model_path.write_bytes(b"fake checkpoint, verification mocked")

    def fake_train_model(**kwargs):
        return False, None, {"ok": False, "error": "simulated training crash"}

    monkeypatch.setattr(rq5, "train_model", fake_train_model)
    monkeypatch.setattr(rq5, "_find_checkpoint", lambda folder: model_path)
    monkeypatch.setattr(
        rq5,
        "_verify_run_checkpoint",
        lambda *args, **kwargs: {
            "ok": True, "failures": [], "checkpoint_sha256": "a" * 64
        },
    )
    monkeypatch.setattr(
        rq5,
        "eval_sim_labeled",
        lambda **kwargs: {"ok": True, "status": "ok", "mIoU": 0.88},
    )
    monkeypatch.setattr(
        rq5,
        "eval_real_unlabeled",
        lambda **kwargs: {"ok": True, "status": "ok", "claim_scope": "domain_shift_indicators_only"},
    )
    args = argparse.Namespace(
        seed=42,
        skip_training=skip_training,
        allow_checkpoint_reuse=True,
        require_manifest=True,
        device="cpu",
        epochs=1,
        batch_size=1,
    )
    result = rq5._run_condition(
        condition="generated_k_k001",
        k=1,
        dataset_roots=[tmp_path / "gen_a"],
        camera="front_left_camera",
        out_dir=tmp_path / "out",
        args=args,
        log_dir=tmp_path / "logs",
        run_id="run_test",
        splits={"eval_path": eval_dir, "eval_identity": {"identity_sha256": "a" * 64}},
        real_u_dir=real_dir,
        real_u_min_images=1,
        eval_min_frames=1,
        sim_reference_dataset=eval_dir,
    )
    assert result["sim"]["ok"] is True
    assert result["real"]["ok"] is True
    assert result["evaluation_completed"] is True
    assert result["trained_this_run"] is False
    assert result["checkpoint_reused"] is True
    assert result["status"] == rq5.STATUS_CHECKPOINT_REUSED
    assert result["ok"] is False
    assert result["status"] != rq5.STATUS_TRAINED_AND_EVALUATED


def test_fresh_training_retains_success_status(tmp_path, monkeypatch):
    eval_dir = tmp_path / "manual_eval"
    real_dir = tmp_path / "real"
    eval_dir.mkdir()
    real_dir.mkdir()
    model_path = tmp_path / "new_checkpoint.pt"
    model_path.write_bytes(b"fake newly trained checkpoint")

    monkeypatch.setattr(
        rq5, "train_model",
        lambda **kwargs: (True, model_path, {"ok": True}),
    )
    monkeypatch.setattr(
        rq5, "_verify_run_checkpoint",
        lambda *args, **kwargs: {
            "ok": True, "failures": [], "checkpoint_sha256": "b" * 64
        },
    )
    monkeypatch.setattr(
        rq5, "eval_sim_labeled",
        lambda **kwargs: {"ok": True, "status": "ok"},
    )
    monkeypatch.setattr(
        rq5, "eval_real_unlabeled",
        lambda **kwargs: {"ok": True, "status": "ok"},
    )
    args = argparse.Namespace(
        seed=42, skip_training=False, allow_checkpoint_reuse=False,
        require_manifest=True, device="cpu", epochs=1, batch_size=1,
    )
    result = rq5._run_condition(
        condition="generated_k_k001", k=1,
        dataset_roots=[tmp_path / "gen_a"],
        camera="front_left_camera", out_dir=tmp_path / "out",
        args=args, log_dir=tmp_path / "logs", run_id="run_test_fresh",
        splits={"eval_path": eval_dir, "eval_identity": {"identity_sha256": "a" * 64}},
        real_u_dir=real_dir, real_u_min_images=1,
        eval_min_frames=1, sim_reference_dataset=eval_dir,
    )
    assert result["ok"] is True
    assert result["status"] == rq5.STATUS_TRAINED_AND_EVALUATED
    assert result["trained_this_run"] is True
    assert result["checkpoint_reused"] is False
    assert result["evaluation_completed"] is True
