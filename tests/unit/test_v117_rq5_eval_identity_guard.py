"""RQ5: subprocess success must not conceal evaluation identity mismatch."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ultimate_pipeline import run_generalization_experiments as experiments


@pytest.mark.parametrize(
    ("returned_dataset", "returned_model", "expected_errors"),
    [
        ("wrong_dataset", "expected_model", ["dataset identity"]),
        ("expected_dataset", "wrong_model", ["checkpoint identity"]),
        ("wrong_dataset", "wrong_model", ["dataset identity", "checkpoint identity"]),
        ("", "expected_model", ["dataset identity"]),
        ("expected_dataset", "", ["checkpoint identity"]),
    ],
)
def test_sim_eval_rejects_identity_mismatch_even_after_successful_subprocess(
    tmp_path, monkeypatch, returned_dataset, returned_model, expected_errors
):
    def fake_subprocess(cmd, log_file=None, env=None):
        out = Path(cmd[cmd.index("--out-json") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({
                "status": "ok",
                "mIoU": 0.99,
                "pixel_accuracy": 0.99,
                "frames_count": 10,
                "model_sha256": returned_model,
                "dataset_identity_sha256": returned_dataset,
            }), encoding="utf-8"
        )
        return 0

    monkeypatch.setattr(experiments, "_run_subprocess", fake_subprocess)
    result = experiments.eval_sim_labeled(
        condition_name="generated_k_k001",
        model_path=tmp_path / "model_last.pt",
        eval_dataset=tmp_path / "eval_data",
        camera="front_left_camera",
        out_dir=tmp_path / "out",
        device="cpu",
        log_dir=tmp_path / "logs",
        eval_dataset_identity={"identity_sha256": "expected_dataset"},
        model_identity={"sha256": "expected_model"},
    )
    assert result["ok"] is False
    assert result["status"] == "identity_mismatch"
    for err in expected_errors:
        assert any(err in explanation for explanation in result["errors"])


def test_sim_eval_matching_identities_pass_with_successful_subprocess(tmp_path, monkeypatch):
    def fake_subprocess(cmd, log_file=None, env=None):
        out = Path(cmd[cmd.index("--out-json") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({
                "status": "ok",
                "frames_count": 10,
                "model_sha256": "expected_model",
                "dataset_identity_sha256": "expected_dataset",
            }), encoding="utf-8"
        )
        return 0

    monkeypatch.setattr(experiments, "_run_subprocess", fake_subprocess)
    result = experiments.eval_sim_labeled(
        condition_name="generated_k_k003",
        model_path=tmp_path / "model_last.pt",
        eval_dataset=tmp_path / "eval_data",
        camera="front_left_camera",
        out_dir=tmp_path / "out",
        device="cpu",
        log_dir=tmp_path / "logs",
        eval_dataset_identity={"identity_sha256": "expected_dataset"},
        model_identity={"sha256": "expected_model"},
    )
    assert result["ok"] is True, result["errors"]
    assert result["status"] == "ok"
