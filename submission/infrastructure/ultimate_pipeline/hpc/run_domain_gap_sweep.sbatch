#!/bin/bash
#SBATCH --job-name=domain_gap_sweep
#SBATCH --output=logs/dg_sweep_%j.out
#SBATCH --error=logs/dg_sweep_%j.err
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G

module load python/3.10

cd $HOME/carla_-main/ultimate_pipeline

source venv/bin/activate

python domain_gap/run_domain_gap_sweep.py
