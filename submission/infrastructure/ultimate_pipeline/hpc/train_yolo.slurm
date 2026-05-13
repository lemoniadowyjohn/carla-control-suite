#!/bin/bash
#SBATCH --job-name=yolo_train_auto
#SBATCH --output=logs/yolo_train_auto_%j.out
#SBATCH --error=logs/yolo_train_auto_%j.err
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=48:00:00

echo "=== YOLO Training Job Started ==="
echo "SLURM Job ID: $SLURM_JOB_ID"
echo "Running on $(hostname)"
echo "CUDA_VISIBLE_DEVICES = $CUDA_VISIBLE_DEVICES"

# Activate environment
source ~/.bashrc
conda activate carla_env || source venv/bin/activate

# Move to your project directory
cd ~/carla_project

# TRAIN YOLO ON DATASET
python train_yolo.py \
    --data configs/yolo_auto.yaml \
    --epochs 100 \
    --img 640 \
    --batch 32 \
    --device 0

echo "=== Training completed successfully ==="
