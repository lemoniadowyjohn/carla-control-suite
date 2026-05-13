#!/bin/bash
#SBATCH --job-name=carla_seg_ddp
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --partition=gpu
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=06:00:00

set -euo pipefail

DATASET_DIR=${1:-""}
CAMERA=${2:-"front_left_camera"}

mkdir -p logs

# Activate env here

# torchrun (single-node) DDP
torchrun --standalone --nproc_per_node=4 -m ultimate_pipeline.perception.train_launcher \
  --dataset "$DATASET_DIR" \
  --camera "$CAMERA" \
  --epochs 20 \
  --batch 8 \
  --lr 1e-4 \
  --num-workers 8 \
  --device cuda \
  --ddp
