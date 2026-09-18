from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ExperimentConfig:
    """
    Small, stable contract used by unit tests and by SLURM script generation.

    Important test contracts:
    - ExperimentConfig MUST have to_cli_args()
    - YOLO experiments MUST raise ValueError in to_cli_args() if extra_args["config"] missing
    - experiment_orchestrator MUST export generate_slurm_script
    """
    name: str
    train_script: str
    dataset: str
    map_version: str
    model_type: str
    seed: int = 0

    # SLURM defaults
    gpus: int = 1
    cpus: int = 8
    mem_gb: int = 32
    time_hours: int = 24
    partition: str = "gpu"

    extra_args: Dict[str, str] = field(default_factory=dict)

    def _is_yolo(self) -> bool:
        ms = str(self.model_type or "").lower()
        ts = str(self.train_script or "")
        return (ms == "yolo") or ts.replace("\\", "/").endswith("train_yolo.py")

    def to_cli_args(self) -> List[str]:
        """
        Returns CLI args for the training script.
        Validation intentionally happens here (not in __init__), matching unit tests.
        """
        if self._is_yolo():
            cfg = (self.extra_args or {}).get("config")
            if not cfg:
                raise ValueError("YOLO experiments require extra_args['config'] (path to YOLO config json)")

        args: List[str] = [
            "--dataset", str(self.dataset),
            "--map_version", str(self.map_version),
            "--model_type", str(self.model_type),
            "--seed", str(int(self.seed)),
        ]

        # extra args as --key value
        for k, v in (self.extra_args or {}).items():
            if v is None:
                continue
            k = str(k).strip().lstrip("-")
            args.extend([f"--{k}", str(v)])

        return args


def _sanitize_project_root(project_root: Optional[str]) -> str:
    """
    On HPC, we should run from the submit directory. If a Windows path is passed,
    sanitize to $SLURM_SUBMIT_DIR to satisfy portability tests.
    """
    if not project_root:
        return "$SLURM_SUBMIT_DIR"

    pr = str(project_root)
    # Windows-ish path? (drive letter or backslashes)
    if (":" in pr) or ("\\" in pr):
        return "$SLURM_SUBMIT_DIR"

    return pr


def generate_slurm_script(
    exp: ExperimentConfig,
    jobs_dir: str,
    project_root: Optional[str] = None,
    logs_dir: Optional[str] = None,
) -> str:
    """
    Writes a SLURM bash script and returns its path.

    Unit-test contract:
    - script must contain: cd $SLURM_SUBMIT_DIR (or quoted)
    """
    jobs_dir_p = Path(jobs_dir)
    jobs_dir_p.mkdir(parents=True, exist_ok=True)

    logs_dir_p = Path(logs_dir) if logs_dir else (jobs_dir_p.parent / "_logs")
    logs_dir_p.mkdir(parents=True, exist_ok=True)

    job_path = jobs_dir_p / f"{exp.name}.sh"
    out_log = logs_dir_p / f"{exp.name}.out"
    err_log = logs_dir_p / f"{exp.name}.err"

    # validate here via to_cli_args() (this is where ValueError is expected)
    cli_args = exp.to_cli_args()

    run_root = _sanitize_project_root(project_root)

    script = "\n".join([
        "#!/bin/bash",
        f"#SBATCH --job-name={exp.name}",
        f"#SBATCH --partition={exp.partition}",
        f"#SBATCH --gres=gpu:{int(exp.gpus)}",
        f"#SBATCH --cpus-per-task={int(exp.cpus)}",
        f"#SBATCH --mem={int(exp.mem_gb)}G",
        f"#SBATCH --time={int(exp.time_hours)}:00:00",
        f"#SBATCH --output={out_log.as_posix()}",
        f"#SBATCH --error={err_log.as_posix()}",
        "",
        "set -euo pipefail",
        "",
        # Portability: always prefer SLURM submit dir in tests
        f'cd "{run_root}"',
        "",
        'echo "Host: $(hostname)"',
        'echo "Start: $(date)"',
        "",
        # Execute the train script as a file path
        f'python "{exp.train_script}" ' + " ".join(cli_args),
        "",
        'echo "Done: $(date)"',
        "",
    ]) + "\n"

    job_path.write_text(script, encoding="utf-8")
    print(f"[ExperimentOrchestrator] Wrote job script → {job_path}")

    return str(job_path)
