#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""One-button training launcher for *local PC* or *HPC*.

This wraps `ultimate_pipeline.perception.train_launcher` and adds a backend switch:
 - SETTINGS.TRAINING_BACKEND = "local" | "hpc" | "auto"

"hpc" backend writes an sbatch script (and submits it if `sbatch` is available).
"local" backend runs training directly.

It is intentionally conservative: it will never attempt to submit SLURM jobs on
Windows; it will just write the script and print the command.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES


def _detect_backend() -> str:
    env = os.getenv("UP_TRAINING_BACKEND", "").strip().lower()
    if env:
        return env
    backend = getattr(SETTINGS, "TRAINING_BACKEND", "local").strip().lower()
    if backend == "auto":
        if os.getenv("SLURM_JOB_ID") or os.getenv("SLURM_CLUSTER_NAME"):
            return "hpc"
        return "local"
    return backend


def _render_sbatch(dataset: str, camera: str, out_dir: str) -> str:
    # Minimal SLURM script; users can extend memory/partition/time as needed.
    # We keep it tiny so it's portable across clusters.
    return """#!/bin/bash
#SBATCH --job-name=up_train
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=08:00:00

set -euo pipefail

echo "[SLURM] host=$(hostname)"
echo "[SLURM] job=$SLURM_JOB_ID"

# Activate your environment here (example):
# source ~/miniconda3/etc/profile.d/conda.sh
# conda activate carla

python -m ultimate_pipeline.perception.train_launcher \
  --dataset "{dataset}" \
  --camera "{camera}" \
  --out-dir "{out_dir}" \
  --epochs {epochs} \
  --batch {batch} \
  --lr {lr} \
  --num-classes {classes} \
  --limit {limit} \
  --device cuda
""".format(
        dataset=dataset,
        camera=camera,
        out_dir=out_dir,
        epochs=int(getattr(SETTINGS, "TRAIN_EPOCHS", 3)),
        batch=int(getattr(SETTINGS, "TRAIN_BATCH", 4)),
        lr=float(getattr(SETTINGS, "TRAIN_LR", 1e-4)),
        classes=int(getattr(SETTINGS, "TRAIN_NUM_CLASSES", CARLA_SEMANTIC_NUM_CLASSES)),
        limit=int(getattr(SETTINGS, "TRAIN_LIMIT", 0)),
    )


def main() -> None:
    backend = _detect_backend()

    dataset = getattr(SETTINGS, "TRAINING_DATASET_DIR", "")
    camera = getattr(SETTINGS, "TRAINING_CAMERA", "front_left_camera")
    out_dir = getattr(SETTINGS, "TRAINING_OUT_DIR", "runs/train")

    if backend not in {"local", "hpc"}:
        raise ValueError(f"Unknown TRAINING_BACKEND: {backend!r} (use local|hpc|auto)")

    if backend == "local":
        # Run directly.
        from ultimate_pipeline.perception.train_launcher import main as train_main
        train_main()
        return

    # HPC backend: write sbatch and optionally submit.
    runs_dir = Path(getattr(SETTINGS, "BASE_OUTPUT_DIR", str(Path.cwd()))) / "hpc_jobs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    job_file = runs_dir / "train_segmentation.sbatch"
    job_file.write_text(_render_sbatch(dataset, camera, out_dir), encoding="utf-8")

    print(f"🧾 Wrote SLURM job script → {job_file}")

    # Never auto-submit on Windows.
    if platform.system().lower().startswith("win"):
        print("⚠ Detected Windows: not submitting SLURM job automatically.")
        print(f"Submit on the cluster with: sbatch {job_file}")
        return

    if shutil.which("sbatch"):
        p = subprocess.run(["sbatch", str(job_file)], capture_output=True, text=True)
        print(p.stdout.strip() or p.stderr.strip())
    else:
        print("⚠ sbatch not found in PATH. Submit manually on the cluster:")
        print(f"sbatch {job_file}")


if __name__ == "__main__":
    main()
