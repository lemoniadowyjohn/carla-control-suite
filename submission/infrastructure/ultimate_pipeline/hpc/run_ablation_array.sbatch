#!/bin/bash
#SBATCH --job-name=dg_ablation
#SBATCH --array=0-4
#SBATCH --output=logs/ablation_%A_%a.out
#SBATCH --error=logs/ablation_%A_%a.err
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G

SEED=$SLURM_ARRAY_TASK_ID

module load python/3.10
cd $HOME/carla_-main/ultimate_pipeline
source venv/bin/activate

python domain_gap/run_domain_gap_ablation.py --seed $SEED
