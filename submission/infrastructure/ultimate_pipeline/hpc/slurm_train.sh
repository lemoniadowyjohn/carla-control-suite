#!/bin/bash
#SBATCH --job-name=perception_train
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=6
#SBATCH --mem=32G
#SBATCH --time=48:00:00
#SBATCH --output=logs/slurm_%j.out

module load python/3.10 cuda/11.8

source ~/venv/bin/activate

echo "Starting training..."
python ultimate_pipeline/hpc/train_yolo.py --config configs/exp.yaml

echo "Job done."
