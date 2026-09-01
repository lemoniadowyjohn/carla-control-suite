#!/usr/bin/env python3
"""Retrain the C21 GNN 5-seed ensemble with the fixed graph_builder.py
(commit 92cf6178), matching the original C21_GNN_AUTHORITATIVE methodology
exactly: same 562 union_tiles, 50 epochs, batch 16, lr 1e-4, CPU,
torch_deterministic=true, seeds 42-46.

Auto-map substitution: the original auto_full_aligned.xodr is not present in
this worktree/git history (never committed). Substituted with the pinned
candidate map (reports/ingolstadt_map_quality_v2/work_package_02_connectivity/
candidate_connectivity_repaired.xodr) per explicit user decision 2026-09-01.
This only affects the whole-map latent-gap comparison step, not the
per-tile-trained checkpoints themselves.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_ROOT = Path(__file__).resolve().parent
TILES_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / "C21_GNN_AUTHORITATIVE" / "union_tiles"
MANUAL_XODR = REPO_ROOT / "cities" / "ingolstadt" / "manual_grid0821.xodr"
AUTO_XODR = (
    REPO_ROOT
    / "reports"
    / "ingolstadt_map_quality_v2"
    / "work_package_02_connectivity"
    / "candidate_connectivity_repaired.xodr"
)
SEEDS = [42, 43, 44, 45, 46]

log_path = OUT_ROOT / "seed_ensemble_run.log"


def _log(line: str) -> None:
    print(line)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    assert TILES_DIR.is_dir(), f"tiles dir missing: {TILES_DIR}"
    assert MANUAL_XODR.is_file(), f"manual xodr missing: {MANUAL_XODR}"
    assert AUTO_XODR.is_file(), f"auto xodr missing: {AUTO_XODR}"

    for seed in SEEDS:
        seed_out = OUT_ROOT / f"seed_{seed}"
        _log(f"=== SEED {seed} starting {datetime.now(timezone.utc).isoformat()} ===")
        cmd = [
            sys.executable,
            "-m",
            "ultimate_pipeline.tools.run_gnn_pipeline",
            "--tiles-dir",
            str(TILES_DIR),
            "--manual-xodr",
            str(MANUAL_XODR),
            "--auto-xodr",
            str(AUTO_XODR),
            "--epochs",
            "50",
            "--batch-size",
            "16",
            "--lr",
            "1e-4",
            "--out-dir",
            str(seed_out),
            "--seed",
            str(seed),
        ]
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, capture_output=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(result.stdout or "")
            f.write(result.stderr or "")
        _log(f"=== SEED {seed} done {datetime.now(timezone.utc).isoformat()} exit={result.returncode} ===")
        if result.returncode != 0:
            _log(f"!!! SEED {seed} FAILED, aborting ensemble !!!")
            return 1

    _log("=== ALL SEEDS COMPLETE ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
