#!/bin/bash
#SBATCH --job-name=yolo
#SBATCH --output=logs/slurm/%x_%j.out
#SBATCH --error=logs/slurm/%x_%j.err
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=6
#SBATCH --mem=32G
#SBATCH --time=12:00:00

set -euo pipefail

# ---- (1) Move to repo root (assumes you sbatch from repo root)
cd "${SLURM_SUBMIT_DIR}"

mkdir -p logs/slurm logs/hpc

# ---- (2) Load modules / activate env (adapt to your cluster)
module purge
module load python/3.10

# If you use a venv inside the repo:
source .venv/bin/activate

# ---- (3) Make sure Python can import the repo
export PYTHONPATH="${PWD}:${PYTHONPATH:-}"

# ---- (4) CLI args
EXP_NAME="${1:?Usage: sbatch train_yolo.sbatch <exp_name> [config_json]}"
CFG_PATH="${2:-ultimate_pipeline/hpc/configs/${EXP_NAME}.json}"

echo "Experiment: ${EXP_NAME}"
echo "Config: ${CFG_PATH}"
nvidia-smi || true

# ---- (5) Run as a module (best practice)
python -u -m ultimate_pipeline.hpc.train_yolo \
  --exp-name "${EXP_NAME}" \
  --config "${CFG_PATH}"