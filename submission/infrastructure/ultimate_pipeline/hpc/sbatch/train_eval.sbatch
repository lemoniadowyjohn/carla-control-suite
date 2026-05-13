#!/bin/bash
#SBATCH --job-name=dg_train
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=24:00:00

module load python
source ~/.venv/bin/activate

CONFIG=$1
python -u hpc/run_experiment.py --config "$CONFIG"
