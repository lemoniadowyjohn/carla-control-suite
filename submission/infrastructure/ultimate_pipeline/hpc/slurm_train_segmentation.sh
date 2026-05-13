#!/bin/bash
#SBATCH --job-name=carla_seg_train
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=06:00:00

set -euo pipefail

# Example usage:
# sbatch slurm_train_segmentation.sh /path/to/dataset front_left_camera

DATASET_DIR=${1:-""}
CAMERA=${2:-"front_left_camera"}

mkdir -p logs

# Activate your environment here
# source ~/miniconda3/etc/profile.d/conda.sh
# conda activate carla_thesis

python -m ultimate_pipeline.perception.train_launcher \
  --dataset "$DATASET_DIR" \
  --camera "$CAMERA" \
  --epochs 20 \
  --batch 8 \
  --lr 1e-4 \
  --num-workers 8 \
  --device cuda
