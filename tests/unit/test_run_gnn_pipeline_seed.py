"""C21: run_gnn_pipeline.py hardcoded --seed 42 in the training_command it builds,
making a seed-ensemble (needed to move the GNN latent gap from PROTOTYPE to
AUTHORITATIVE) impossible without a code change. This makes --seed a real CLI arg,
threaded through into the constructed train_map_encoder training_command.
"""
from __future__ import annotations

import json
from pathlib import Path

import ultimate_pipeline.tools.run_gnn_pipeline as run_gnn_pipeline


def _make_tiles_dir(tmp_path: Path) -> Path:
    d = tmp_path / "tiles"
    d.mkdir()
    (d / "tile_0_0.xodr").write_text("<OpenDRIVE/>", encoding="utf-8")
    return d


def test_seed_defaults_to_42(tmp_path):
    tiles_dir = _make_tiles_dir(tmp_path)
    out_dir = tmp_path / "out"
    argv = ["--tiles-dir", str(tiles_dir), "--out-dir", str(out_dir), "--dry-run"]
    run_gnn_pipeline.main(argv)
    report = json.loads((out_dir / "gnn_training_report.json").read_text(encoding="utf-8"))
    cmd = report["training_command"]
    assert "--seed" in cmd
    assert cmd[cmd.index("--seed") + 1] == "42"


def test_seed_is_configurable_and_flows_into_training_command(tmp_path):
    tiles_dir = _make_tiles_dir(tmp_path)
    out_dir = tmp_path / "out"
    argv = ["--tiles-dir", str(tiles_dir), "--out-dir", str(out_dir), "--seed", "46", "--dry-run"]
    run_gnn_pipeline.main(argv)
    report = json.loads((out_dir / "gnn_training_report.json").read_text(encoding="utf-8"))
    cmd = report["training_command"]
    assert "--seed" in cmd
    assert cmd[cmd.index("--seed") + 1] == "46"


def test_different_seeds_produce_different_out_dirs_when_caller_uses_seed_suffix(tmp_path):
    # Not a code invariant of run_gnn_pipeline itself -- documents the intended usage
    # pattern for a seed-ensemble: caller passes a distinct --out-dir per seed so
    # checkpoints/reports don't clobber each other.
    tiles_dir = _make_tiles_dir(tmp_path)
    for seed in (42, 43):
        out_dir = tmp_path / f"out_seed{seed}"
        run_gnn_pipeline.main(
            ["--tiles-dir", str(tiles_dir), "--out-dir", str(out_dir), "--seed", str(seed), "--dry-run"]
        )
        report = json.loads((out_dir / "gnn_training_report.json").read_text(encoding="utf-8"))
        cmd = report["training_command"]
        assert cmd[cmd.index("--seed") + 1] == str(seed)


# 2026-09-01: _resolve_checkpoint() sorted checkpoint paths lexicographically
# ("epoch100.pt" < "epoch90.pt" as strings), which could silently pick a
# less-trained checkpoint as "the latest" once epoch counts cross a
# digit-width boundary. Same bug class already found and fixed in
# run_ksweep.py's own _resolve_checkpoint(); fixed here too while in the area.
def test_resolve_checkpoint_picks_numerically_latest_not_lexicographically(tmp_path):
    ckpt_dir = tmp_path / "checkpoints"
    ckpt_dir.mkdir()
    for n in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
        (ckpt_dir / f"map_encoder_epoch{n}.pt").touch()

    result = run_gnn_pipeline._resolve_checkpoint(ckpt_dir)

    assert result.name == "map_encoder_epoch100.pt"


def test_resolve_checkpoint_no_candidates_returns_none(tmp_path):
    ckpt_dir = tmp_path / "empty"
    ckpt_dir.mkdir()

    assert run_gnn_pipeline._resolve_checkpoint(ckpt_dir) is None
