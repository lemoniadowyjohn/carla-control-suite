#!/usr/bin/env bash
#SBATCH --job-name=ingolstadt_auto_yolo
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=logs/hpc/ingolstadt_auto_yolo.out
#SBATCH --error=logs/hpc/ingolstadt_auto_yolo.err

set -euo pipefail

cd "$SLURM_SUBMIT_DIR"

echo "Host: $(hostname)"
echo "Start: $(date)"

python -m ultimate_pipeline.hpc.train_yolo \
    --dataset auto \
    --map_version auto_full \
    --model_type yolo \
    --seed 0 \
    --config ultimate_pipeline/hpc/configs/yolo_auto.json

echo "Done: $(date)"

