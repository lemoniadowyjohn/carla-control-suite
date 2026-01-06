# ultimate_pipeline/hpc/experiment_orchestrator.py

from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional


# ---------------------------------------------------------------------
#  Experiment configuration
# ---------------------------------------------------------------------

@dataclass
class ExperimentConfig:
    """
    Description of a single HPC experiment.

    You can extend fields as needed. These fields are injected into the
    SLURM script as variables and CLI args.
    """
    name: str                  # e.g. "ingolstadt_manual_yolo_seed0"
    train_script: str          # e.g. "ultimate_pipeline/hpc/train_yolo.py"
    dataset: str               # "manual" | "auto" | "mixed"
    map_version: str           # e.g. "manual_full" | "auto_tiles"
    model_type: str            # e.g. "yolo" | "segmentation"
    seed: int                  # random seed
    gpus: int = 1
    cpus: int = 8
    mem_gb: int = 32
    time_hours: int = 24
    partition: str = "gpu"
    extra_args: Optional[Dict[str, str]] = None  # extra CLI args

    def to_cli_args(self) -> str:
        """
        Build a string of CLI arguments to pass to the train script.

        Example:
          --exp_name ingolstadt_manual_yolo_seed0
          --dataset manual
          --map_version manual_full
          --model_type yolo
          --seed 0
          --extra key=value ...
        """
        args = [
            f"--exp_name {self.name}",
            f"--dataset {self.dataset}",
            f"--map_version {self.map_version}",
            f"--model_type {self.model_type}",
            f"--seed {self.seed}",
        ]

        if self.extra_args:
            for k, v in self.extra_args.items():
                args.append(f"--{k} {v}")

        return " ".join(args)


# ---------------------------------------------------------------------
#  SLURM script generation
# ---------------------------------------------------------------------

SLURM_HEADER_TEMPLATE = """#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --partition={partition}
#SBATCH --gres=gpu:{gpus}
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={mem_gb}G
#SBATCH --time={time_hours}:00:00
#SBATCH --output={log_path}

# >>> EDIT THESE MODULES/ENV COMMANDS FOR YOUR CLUSTER <<<
module load python/3.10 || true
module load cuda || true

# Activate your virtualenv or conda env
source ~/venv/bin/activate || true

echo "Running experiment: {job_name}"
echo "On host: $(hostname)"
echo "Using train script: {train_script}"
echo "CLI args: {cli_args}"
echo "Time: $(date)"

cd {project_root}

python {train_script} {cli_args}

echo "Done: $(date)"
"""


def generate_slurm_script(
    exp: ExperimentConfig,
    jobs_dir: str,
    project_root: str,
    logs_dir: str = "logs/hpc",
) -> str:
    """
    Create a SLURM job script for the given experiment.
    Returns: path to the .sh file.
    """
    os.makedirs(jobs_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    job_basename = f"{exp.name}.sh"
    job_path = os.path.join(jobs_dir, job_basename)
    log_path = os.path.join(logs_dir, f"{exp.name}.out")

    cli_args = exp.to_cli_args()

    script = SLURM_HEADER_TEMPLATE.format(
        job_name=exp.name,
        partition=exp.partition,
        gpus=exp.gpus,
        cpus=exp.cpus,
        mem_gb=exp.mem_gb,
        time_hours=exp.time_hours,
        log_path=log_path,
        train_script=exp.train_script,
        cli_args=cli_args,
        project_root=project_root,
    )

    with open(job_path, "w", encoding="utf-8") as f:
        f.write(script)

    print(f"[ExperimentOrchestrator] Wrote job script → {job_path}")
    return job_path


# ---------------------------------------------------------------------
#  Experiment suite definition
# ---------------------------------------------------------------------

def build_default_experiments() -> List[ExperimentConfig]:
    """
    Define a small set of default experiments.
    Extend this to match your thesis experiments.
    """
    exps: List[ExperimentConfig] = []

    # Example: YOLO on manual-only data
    exps.append(
        ExperimentConfig(
            name="ingolstadt_manual_yolo_seed0",
            train_script="ultimate_pipeline/hpc/train_yolo.py",
            dataset="manual",
            map_version="manual_full",
            model_type="yolo",
            seed=0,
            gpus=1,
            cpus=8,
            mem_gb=32,
            time_hours=24,
            partition="gpu",
            extra_args={
                "epochs": "50",
                "batch_size": "8",
            },
        )
    )

    # YOLO on auto-generated-only data
    exps.append(
        ExperimentConfig(
            name="ingolstadt_auto_yolo_seed0",
            train_script="ultimate_pipeline/hpc/train_yolo.py",
            dataset="auto",
            map_version="auto_full",
            model_type="yolo",
            seed=0,
            gpus=1,
            cpus=8,
            mem_gb=32,
            time_hours=24,
            partition="gpu",
            extra_args={
                "epochs": "50",
                "batch_size": "8",
            },
        )
    )

    # YOLO on mixed (manual + auto) data
    exps.append(
        ExperimentConfig(
            name="ingolstadt_mixed_yolo_seed0",
            train_script="ultimate_pipeline/hpc/train_yolo.py",
            dataset="mixed",
            map_version="mixed",
            model_type="yolo",
            seed=0,
            gpus=1,
            cpus=8,
            mem_gb=32,
            time_hours=24,
            partition="gpu",
            extra_args={
                "epochs": "50",
                "batch_size": "8",
            },
        )
    )

    # You can add segmentation experiments similarly if you want
    # exps.append(...)

    return exps


# ---------------------------------------------------------------------
#  Main entry point
# ---------------------------------------------------------------------

def main():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    jobs_dir = os.path.join(project_root, "hpc", "jobs")
    logs_dir = os.path.join(project_root, "logs", "hpc")

    experiments = build_default_experiments()
    print(f"🧪 Building SLURM scripts for {len(experiments)} experiments")

    job_paths = []

    for exp in experiments:
        job_path = generate_slurm_script(
            exp,
            jobs_dir=jobs_dir,
            project_root=project_root,
            logs_dir=logs_dir,
        )
        job_paths.append(job_path)

    print("\n✅ All job scripts generated.")
    print("To submit them, run:")
    for jp in job_paths:
        print(f"  sbatch {jp}")


if __name__ == "__main__":
    main()
