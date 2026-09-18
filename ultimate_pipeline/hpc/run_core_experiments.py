# ultimate_pipeline/hpc/run_core_experiments.py

from __future__ import annotations
import os

from ultimate_pipeline.hpc.experiment_orchestrator import (
    ExperimentConfig,
    generate_slurm_script,
)

def main():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    jobs_dir = os.path.join(project_root, "hpc", "jobs")
    logs_dir = os.path.join(project_root, "logs", "hpc")

    exps = [
        ExperimentConfig(
            name="ingolstadt_manual_yolo",
            train_script="ultimate_pipeline/hpc/train_yolo.py",
            dataset="manual",
            map_version="manual_full",
            model_type="yolo",
            seed=0,
            gpus=1, cpus=8, mem_gb=32, time_hours=24,
            extra_args={"config": "configs/yolo_manual.json"},
        ),
        ExperimentConfig(
            name="ingolstadt_auto_yolo",
            train_script="ultimate_pipeline/hpc/train_yolo.py",
            dataset="auto",
            map_version="auto_full",
            model_type="yolo",
            seed=0,
            gpus=1, cpus=8, mem_gb=32, time_hours=24,
            extra_args={"config": "configs/yolo_auto.json"},
        ),
        ExperimentConfig(
            name="ingolstadt_mixed_yolo",
            train_script="ultimate_pipeline/hpc/train_yolo.py",
            dataset="mixed",
            map_version="mixed",
            model_type="yolo",
            seed=0,
            gpus=1, cpus=8, mem_gb=40, time_hours=30,
            extra_args={"config": "configs/yolo_mixed.json"},
        ),
    ]

    job_paths = []
    for exp in exps:
        jp = generate_slurm_script(exp, jobs_dir=jobs_dir, project_root=project_root, logs_dir=logs_dir)
        job_paths.append(jp)

    print("\n✅ Core experiment jobs created. Submit with:")
    for jp in job_paths:
        print(f"  sbatch {jp}")


if __name__ == "__main__":
    main()
