#!/bin/bash
#SBATCH --job-name=EXPERIMENT_NAME
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=logs/hpc/EXPERIMENT_NAME.out

module load python/3.10 || true
module load cuda || true

source ~/venv/bin/activate || true

cd /path/to/your/project/root

python ultimate_pipeline/hpc/train_yolo.py --exp_name EXPERIMENT_NAME ...
