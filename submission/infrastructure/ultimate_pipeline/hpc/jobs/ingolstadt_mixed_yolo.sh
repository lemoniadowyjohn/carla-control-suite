#!/usr/bin/env bash
#SBATCH --job-name=ingolstadt_mixed_yolo
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=40G
#SBATCH --time=30:00:00
#SBATCH --output=logs/hpc/ingolstadt_mixed_yolo.out
#SBATCH --error=logs/hpc/ingolstadt_mixed_yolo.err

set -euo pipefail

cd "$SLURM_SUBMIT_DIR"

echo "Host: $(hostname)"
echo "Start: $(date)"

python -m ultimate_pipeline.hpc.train_yolo \
    --dataset mixed \
    --map_version mixed \
    --model_type yolo \
    --seed 0 \
    --config ultimate_pipeline/hpc/configs/yolo_mixed.json

echo "Done: $(date)"

