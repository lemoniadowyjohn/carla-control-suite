#!/bin/bash

echo "=== Preparing HPC upload ==="

# 1. Create clean environment folder
mkdir -p hpc_upload
rsync -av --exclude='.venv' --exclude='__pycache__' carla_-main/ hpc_upload/

# 2. Upload to HPC
rsync -avz hpc_upload/ hpc:~/carla_project/

# 3. Upload datasets
rsync -avz datasets/ hpc:/scratch/$USER/datasets/

# 4. Submit SLURM job
ssh hpc "cd ~/carla_project && sbatch train_yolo.slurm"

echo "=== HPC training job submitted ==="
