#!/bin/bash
#SBATCH --job-name=auto_to_manual_yolo
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=logs/hpc/%x.out

module load python/3.10 || true
module load cuda || true

source ~/venv/bin/activate || true

set -euo pipefail

EXP_NAME=auto_to_manual_yolo
TRAIN_CFG=ultimate_pipeline/hpc/configs/yolo_auto.json
EVAL_CFG=ultimate_pipeline/hpc/configs/yolo_manual.json

echo "Running experiment: ${EXP_NAME}"
echo "Training on: ${TRAIN_CFG}"
echo "Evaluating on: ${EVAL_CFG}"
echo "Host: $(hostname)"
echo "Time: $(date)"

cd "$SLURM_SUBMIT_DIR"

python ultimate_pipeline/hpc/train_yolo.py \
  --exp-name "${EXP_NAME}" \
  --config "${TRAIN_CFG}" \
  --eval-config "${EVAL_CFG}" \
  --notes "Train on auto dataset, evaluate on manual dataset."

echo "Done: $(date)"
