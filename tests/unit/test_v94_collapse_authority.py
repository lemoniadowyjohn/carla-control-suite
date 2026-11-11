"""V94 RQ4: collapse check failures may never admit latent-gap metrics.

Offline CPU controls, including a no-model-load sentinel for both public
inference paths. torch_geometric is required by the production runner.
"""
from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torch_geometric")

from ultimate_pipeline.domain_gap_gnn import collapse_guard_wire as guard
from ultimate_pipeline.domain_gap_gnn import latent_gap_runner as runner
from ultimate_pipeline.domain_gap_gnn import run_ksweep as ks


def _checkpoint(tmp_path):
    path = tmp_path / "model.pt"
    path.write_bytes(b"synthetic-checkpoint-path-exists")
    return str(path)


def _verdict(label, noise=0.2, tile=0.3, cross=0.1):
    return {
        "verdict": label,
        "noise_self_cosine": noise,
        "tile_self_cosine": tile,
        "cross_cosine": cross,
    }


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"verdict": "NOT_RUN"},
        _verdict("UNKNOWN"),
        _verdict("NOT_COLLAPSED", noise=float("nan")),
        _verdict("NOT_COLLAPSED", noise=float("inf")),
        _verdict("NOT_COLLAPSED", noise=True),
        _verdict("NOT_COLLAPSED", noise=1.1),
        _verdict("NOT_COLLAPSED", noise=0.95),
        _verdict("COLLAPSED", noise=0.2),
        {"verdict": "NOT_COLLAPSED", "noise_self_cosine": 0.1},
    ],
)
def test_unknown_incomplete_nonfinite_and_contradictory_checks_fail_closed(
    tmp_path, monkeypatch, raw
):
    cp = _checkpoint(tmp_path)
    monkeypatch.setattr(guard, "run_collapse_check", lambda **kwargs: raw)
    verdict = guard.collapse_verdict(cp)
    assert verdict["status"] == "NOT_RUN"
    assert verdict["reason"] == "invalid_collapse_verdict"
    blocked = guard.blocked_payload(verdict)
    assert blocked["enabled"] is False and blocked["metrics"] is None


def test_collapse_check_error_is_not_a_clearance(tmp_path, monkeypatch):
    cp = _checkpoint(tmp_path)
    def fail(**kwargs):
        raise RuntimeError("tiles unavailable")
    monkeypatch.setattr(guard, "run_collapse_check", fail)
    verdict = guard.collapse_verdict(cp)
    assert verdict["status"] == "NOT_RUN"
    assert verdict["reason"] == "collapse_check_failed"


def test_only_consistent_not_collapsed_verdict_grants_clearance(tmp_path, monkeypatch):
    cp = _checkpoint(tmp_path)
    monkeypatch.setattr(
        guard, "run_collapse_check",
        lambda **kwargs: _verdict("NOT_COLLAPSED", noise=0.949),
    )
    verdict = guard.collapse_verdict(cp)
    assert verdict["status"] == "ok" and verdict["reason"] is None
    with pytest.raises(ValueError, match="requires a NOT_RUN"):
        guard.blocked_payload(verdict)


def test_consistent_collapsed_verdict_blocks(tmp_path, monkeypatch):
    cp = _checkpoint(tmp_path)
    monkeypatch.setattr(
        guard, "run_collapse_check",
        lambda **kwargs: _verdict("COLLAPSED", noise=0.95),
    )
    blocked = guard.blocked_payload(guard.collapse_verdict(cp))
    assert blocked["reason"] == "encoder_collapsed"
    assert blocked["metrics"] is None


@pytest.mark.parametrize("entrypoint", ["whole", "per_tile"])
def test_latent_runners_never_load_model_after_failed_collapse_check(
    tmp_path, monkeypatch, entrypoint
):
    monkeypatch.setattr(
        runner, "collapse_verdict",
        lambda *args, **kwargs: {
            "status": "NOT_RUN",
            "reason": "collapse_check_failed",
            "checkpoint": "dummy.pt",
            "verdict": "NOT_COLLAPSED",
        },
    )
    def must_not_load(*args, **kwargs):
        raise AssertionError("a NOT_RUN collapse check reached model loading")
    monkeypatch.setattr(runner, "_load_encoder", must_not_load)
    if entrypoint == "whole":
        out = runner.compute_whole_map_latent_gap("missing_manual.xodr", "missing_auto.xodr", "dummy.pt")
    else:
        out = runner.compute_per_tile_latent_gap(
            "missing_manual_tiles", "missing_auto_tiles", "dummy.pt",
            str(tmp_path / "not_created.json"),
        )
    assert out["enabled"] is False
    assert out["status"] == "NOT_RUN"
    assert out["reason"] == "collapse_check_failed"
    assert out["metrics"] is None


def test_missing_sidecar_disqualifies_ksweep_reuse(tmp_path):
    train = tmp_path / "train"
    train.mkdir()
    cp = train / "map_encoder_epoch5.pt"
    cp.write_bytes(b"unverified")
    manifest = {"graph_schema_sha256": "x", "training_seed": 1}
    cp.with_suffix(cp.suffix + ".manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    assert ks._try_reuse_checkpoint(
        train, 5, manifest, on_mismatch="retrain",
    ) is None
    with pytest.raises(RuntimeError, match="checkpoint bytes/manifest invalid"):
        ks._try_reuse_checkpoint(train, 5, manifest, on_mismatch="fail")


def test_legacy_checkpoint_cannot_be_used_for_latent_metrics(tmp_path):
    ckpt = tmp_path / "old.pt"
    torch.save({"model_state": {"w": torch.ones(1)}, "cfg": {"node_dim": 1}}, ckpt)
    with pytest.raises(ValueError, match="verified metadata checkpoint"):
        runner._load_encoder(str(ckpt), torch.device("cpu"))
