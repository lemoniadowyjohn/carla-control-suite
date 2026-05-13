#!/bin/bash
#SBATCH --job-name=yolo_exp
#SBATCH --output=logs/slurm/%x_%j.out
#SBATCH --error=logs/slurm/%x_%j.err
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=6
#SBATCH --mem=32G
#SBATCH --time=12:00:00

module load python/3.10

echo "Starting experiment: $1"

python -u ultimate_pipeline/hpc/train_yolo.py \
    --exp-name $1 \
    --config configs/$1.json
