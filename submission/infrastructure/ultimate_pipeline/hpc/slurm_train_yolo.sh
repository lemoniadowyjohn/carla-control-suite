#!/bin/bash
#SBATCH --job-name=yolo_synth
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=logs/hpc/yolo_synth_%j.out
#SBATCH --error=logs/hpc/yolo_synth_%j.err

# Load modules if needed
# module load cuda/11.8
# module load anaconda

# Activate environment
source ~/.bashrc
conda activate carla_env

# Navigate to project root
cd /path/to/your/project

# Arguments
EXP_NAME="$1"         # e.g. "real_only" / "synthetic_only" / "mixed"
CONFIG="$2"           # e.g. "configs/yolo_real_only.yaml"

python hpc/train_yolo.py \
  --exp-name "$EXP_NAME" \
  --config "$CONFIG"



