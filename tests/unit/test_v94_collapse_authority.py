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


@pytest.mark.parametrize("entrypoint", ["whole", "per_tile"])
def test_checkpoint_width_mode_used_for_actual_map_graphs(
    tmp_path, monkeypatch, entrypoint
):
    from torch_geometric.data import Data

    monkeypatch.setattr(
        runner, "collapse_verdict",
        lambda *args, **kwargs: {"status": "ok", "verdict": "NOT_COLLAPSED"},
    )
    seen = []

    class Encoder:
        _v94_graph_width_mode = "polynomial"
        _v94_graph_strict = True

        def __call__(self, batch):
            return torch.ones((batch.num_graphs, 4), dtype=torch.float32)

    monkeypatch.setattr(runner, "_load_encoder", lambda *args: Encoder())
    monkeypatch.setattr(
        runner, "checkpoint_provenance_label",
        lambda *args: "VERIFIED_CRYPTOGRAPHIC_PROVENANCE",
    )

    def build(path, **kwargs):
        seen.append((str(path), kwargs))
        return Data(
            x=torch.ones((2, 12), dtype=torch.float32),
            edge_index=torch.tensor([[0], [1]], dtype=torch.long),
        )

    monkeypatch.setattr(runner.MapGraphBuilder, "build_from_xodr", build)
    ckpt = tmp_path / "model.pt"
    ckpt.write_bytes(b"synthetic-not-a-real-checkpoint")
    if entrypoint == "whole":
        out = runner.compute_whole_map_latent_gap(
            "manual.xodr", "auto.xodr", str(ckpt)
        )
    else:
        manual_dir = tmp_path / "manual"
        auto_dir = tmp_path / "auto"
        manual_dir.mkdir()
        auto_dir.mkdir()
        for folder in (manual_dir, auto_dir):
            (folder / "tile.xodr").write_text("<OpenDRIVE/>", encoding="utf-8")
        out = runner.compute_per_tile_latent_gap(
            str(manual_dir), str(auto_dir), str(ckpt), str(tmp_path / "metrics.json")
        )
    assert out["enabled"] is True
    assert len(seen) == 2
    assert all(
        kwargs == {"width_mode": "polynomial", "strict": True}
        for _, kwargs in seen
    )


def test_collapse_screening_uses_exact_training_width_and_strictness(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from torch_geometric.data import Data
    from ultimate_pipeline.domain_gap_gnn import collapse_check

    class Encoder:
        cfg = SimpleNamespace(node_dim=12)
        _v94_graph_width_mode = "polynomial"
        _v94_graph_strict = True

        def __call__(self, batch):
            return torch.eye(batch.num_graphs, dtype=torch.float32)

    seen = []

    class Dataset:
        def __init__(self, tiles_dir, **kwargs):
            seen.append(kwargs)

        def __len__(self):
            return 5

        def __getitem__(self, item):
            return Data(
                x=torch.ones((2, 12), dtype=torch.float32),
                edge_index=torch.tensor([[0], [1]], dtype=torch.long),
            )

    monkeypatch.setattr(collapse_check, "_load_model", lambda *args: Encoder())
    monkeypatch.setattr(collapse_check, "MapTileDataset", Dataset)
    ckpt = tmp_path / "model.pt"
    ckpt.write_bytes(b"synthetic")
    tiles_dir = tmp_path / "tiles"
    tiles_dir.mkdir()
    out = collapse_check.run_collapse_check(
        checkpoint=ckpt, tiles_dir=tiles_dir, out_path=tmp_path / "collapse.json"
    )
    assert out["verdict"] == "NOT_COLLAPSED"
    assert seen == [{"width_mode": "polynomial", "strict": True}]


def test_v95_passed_collapse_helper_does_not_raise_or_fabricate_metrics(tmp_path, monkeypatch):
    cp = _checkpoint(tmp_path)
    monkeypatch.setattr(
        guard, "run_collapse_check",
        lambda **kwargs: _verdict("NOT_COLLAPSED", noise=0.30),
    )
    receipt = guard.collapsed_payload(cp)
    assert receipt["status"] == "ok"
    assert receipt["enabled"] is False and receipt["metrics"] is None
    assert receipt["encoder"]["verdict"] == "NOT_COLLAPSED"


@pytest.mark.parametrize("verdict,exit_code", [
    ("COLLAPSED", 2), ("INDETERMINATE", 2), ("NOT_COLLAPSED", 0),
])
def test_v95_collapse_check_cli_status_matches_verdict(monkeypatch, verdict, exit_code):
    from ultimate_pipeline.domain_gap_gnn import collapse_check
    monkeypatch.setattr(collapse_check, "run_collapse_check", lambda: {"verdict": verdict})
    assert collapse_check.main() == exit_code


def test_v95_collapse_nan_cannot_be_not_collapsed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from torch_geometric.data import Data
    from ultimate_pipeline.domain_gap_gnn import collapse_check as cc

    class FakeEncoder:
        cfg = SimpleNamespace(node_dim=4)
        _v94_graph_width_mode = "legacy"
        _v94_graph_strict = False
        def __call__(self, batch):
            return torch.ones((batch.num_graphs, 4))

    class FakeDataset:
        def __init__(self, *args, **kwargs):
            pass
        def __len__(self):
            return 5
        def __getitem__(self, idx):
            return Data(x=torch.ones((2, 4)), edge_index=torch.tensor([[0], [1]]))

    monkeypatch.setattr(cc, "_load_model", lambda *_: FakeEncoder())
    monkeypatch.setattr(cc, "MapTileDataset", FakeDataset)
    monkeypatch.setattr(cc, "_pairwise_mean_cosine", lambda *_: float("nan"))
    monkeypatch.setattr(cc, "_cross_mean_cosine", lambda *_: 0.2)
    ckpt = tmp_path / "checkpoint.pt"
    ckpt.write_bytes(b"placeholder")
    tiles = tmp_path / "tiles"
    tiles.mkdir()
    receipt = cc.run_collapse_check(ckpt, tiles, tmp_path / "receipt.json")
    assert receipt["verdict"] == "INDETERMINATE"
    assert receipt["noise_self_cosine"] is None
    assert json.loads((tmp_path / "receipt.json").read_text())["noise_self_cosine"] is None
