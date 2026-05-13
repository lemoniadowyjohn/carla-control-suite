"""
Artifacts Management

Canonical artifact layout and run_id generation.
All experiment runs output to: artifacts/runs/<run_id>/
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


def get_git_sha() -> Optional[str]:
    """Get short git SHA of current commit."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).parent.parent.parent,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_pip_freeze() -> List[str]:
    """Get pip freeze output."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip().split("\n")
    except Exception:
        pass
    return []


def create_run_id(
    config_hash: str,
    experiment_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> str:
    """
    Create a canonical run_id.

    Format: {timestamp}_{git_sha}_{config_hash}[_{experiment_id}]

    Example: 20260220_143052_abc123_d4e5f6_domain_gap
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
    git_sha = get_git_sha() or "nogit"
    config_short = config_hash[:6] if config_hash else "noconf"

    parts = [ts_str, git_sha, config_short]
    if experiment_id:
        # Sanitize experiment_id for filesystem
        import re
        safe_id = re.sub(r'[^\w\-]', '_', experiment_id)[:30]
        parts.append(safe_id)

    return "_".join(parts)


class RunArtifacts(BaseModel):
    """
    Manages artifacts for a single run.

    Canonical layout:
    artifacts/runs/<run_id>/
    ├── config_resolved.yaml
    ├── logs/
    │   ├── run.log
    │   └── ...
    ├── metrics.json
    ├── run_summary.json
    ├── run_summary.md
    └── repro/
        ├── git_info.json
        ├── env_snapshot.json
        └── pip_freeze.txt
    """

    run_id: str
    artifact_root: str = "artifacts/runs"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def run_dir(self) -> Path:
        """Get the run directory path."""
        return Path(self.artifact_root) / self.run_id

    @property
    def logs_dir(self) -> Path:
        return self.run_dir / "logs"

    @property
    def repro_dir(self) -> Path:
        return self.run_dir / "repro"

    @property
    def config_path(self) -> Path:
        return self.run_dir / "config_resolved.yaml"

    @property
    def metrics_path(self) -> Path:
        return self.run_dir / "metrics.json"

    @property
    def summary_json_path(self) -> Path:
        return self.run_dir / "run_summary.json"

    @property
    def summary_md_path(self) -> Path:
        return self.run_dir / "run_summary.md"

    def ensure_directories(self) -> None:
        """Create all required directories."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
        self.repro_dir.mkdir(exist_ok=True)

    def write_config(self, config: Any) -> Path:
        """Write resolved config to artifact directory."""
        self.ensure_directories()

        if hasattr(config, "to_yaml"):
            content = config.to_yaml()
        elif hasattr(config, "model_dump"):
            try:
                import yaml
                content = yaml.dump(config.model_dump(), default_flow_style=False)
            except ImportError:
                content = json.dumps(config.model_dump(), indent=2)
        else:
            content = json.dumps(config, indent=2, default=str)

        self.config_path.write_text(content, encoding="utf-8")
        return self.config_path

    def write_repro_info(self) -> None:
        """Write reproducibility information."""
        self.ensure_directories()

        # Git info
        git_info = {
            "sha": get_git_sha(),
            "timestamp": self.created_at.isoformat(),
        }
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=Path(__file__).parent.parent.parent,
            )
            git_info["dirty"] = bool(result.stdout.strip())
            git_info["dirty_files"] = result.stdout.strip().split("\n") if result.stdout.strip() else []
        except Exception:
            git_info["dirty"] = None
            git_info["dirty_files"] = []

        (self.repro_dir / "git_info.json").write_text(
            json.dumps(git_info, indent=2), encoding="utf-8"
        )

        # Environment snapshot
        env_snapshot = {
            "python_version": sys.version,
            "platform": sys.platform,
            "cwd": str(Path.cwd()),
            "env_vars": {
                k: v for k, v in os.environ.items()
                if k.startswith("UP_") or k.startswith("CARLA_") or k == "PYTHONPATH"
            },
        }
        (self.repro_dir / "env_snapshot.json").write_text(
            json.dumps(env_snapshot, indent=2), encoding="utf-8"
        )

        # Pip freeze
        pip_freeze = get_pip_freeze()
        (self.repro_dir / "pip_freeze.txt").write_text(
            "\n".join(pip_freeze), encoding="utf-8"
        )

    def write_metrics(self, metrics: Dict[str, Any]) -> Path:
        """Write metrics to artifact directory."""
        self.ensure_directories()
        self.metrics_path.write_text(
            json.dumps(metrics, indent=2, default=str), encoding="utf-8"
        )
        return self.metrics_path

    def write_summary(
        self,
        success: bool,
        experiment_id: str,
        metrics: Dict[str, Any],
        error: Optional[str] = None,
        artifacts_produced: Optional[List[str]] = None,
        duration_s: Optional[float] = None,
    ) -> None:
        """Write run summary in both JSON and Markdown formats."""
        self.ensure_directories()

        summary = {
            "run_id": self.run_id,
            "experiment_id": experiment_id,
            "success": success,
            "created_at": self.created_at.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": duration_s,
            "metrics": metrics,
            "error": error,
            "artifacts": artifacts_produced or [],
            "paths": {
                "run_dir": str(self.run_dir),
                "config": str(self.config_path),
                "metrics": str(self.metrics_path),
                "logs": str(self.logs_dir),
            },
        }

        # Write JSON summary
        self.summary_json_path.write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8"
        )

        # Write Markdown summary
        md_lines = [
            f"# Run Summary: {self.run_id}",
            "",
            f"**Experiment:** {experiment_id}",
            f"**Status:** {'✓ SUCCESS' if success else '✗ FAILED'}",
            f"**Created:** {self.created_at.isoformat()}",
            f"**Duration:** {duration_s:.2f}s" if duration_s else "**Duration:** N/A",
            "",
            "## Metrics",
            "",
        ]

        for key, value in metrics.items():
            if isinstance(value, float):
                md_lines.append(f"- **{key}:** {value:.4f}")
            else:
                md_lines.append(f"- **{key}:** {value}")

        if error:
            md_lines.extend([
                "",
                "## Error",
                "",
                f"```\n{error}\n```",
            ])

        if artifacts_produced:
            md_lines.extend([
                "",
                "## Artifacts",
                "",
            ])
            for artifact in artifacts_produced:
                md_lines.append(f"- `{artifact}`")

        md_lines.extend([
            "",
            "## Paths",
            "",
            f"- **Run Directory:** `{self.run_dir}`",
            f"- **Config:** `{self.config_path}`",
            f"- **Logs:** `{self.logs_dir}`",
        ])

        self.summary_md_path.write_text("\n".join(md_lines), encoding="utf-8")

    def finalize(
        self,
        success: bool,
        experiment_id: str,
        metrics: Dict[str, Any],
        error: Optional[str] = None,
        duration_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Finalize the run by writing all summary artifacts.

        Returns the summary dict.
        """
        # Collect produced artifacts
        artifacts_produced = []
        for path in self.run_dir.rglob("*"):
            if path.is_file():
                artifacts_produced.append(str(path.relative_to(self.run_dir)))

        # Write metrics
        self.write_metrics(metrics)

        # Write summary
        self.write_summary(
            success=success,
            experiment_id=experiment_id,
            metrics=metrics,
            error=error,
            artifacts_produced=artifacts_produced,
            duration_s=duration_s,
        )

        return {
            "run_id": self.run_id,
            "success": success,
            "run_dir": str(self.run_dir),
            "metrics": metrics,
            "error": error,
        }


def ensure_run_directory(
    artifact_root: str = "artifacts/runs",
    run_id: Optional[str] = None,
    config_hash: Optional[str] = None,
    experiment_id: Optional[str] = None,
) -> RunArtifacts:
    """
    Create and initialize a run directory.

    Args:
        artifact_root: Base directory for artifacts
        run_id: Optional explicit run_id
        config_hash: Config hash for run_id generation
        experiment_id: Experiment ID for run_id

    Returns:
        Initialized RunArtifacts instance
    """
    if run_id is None:
        run_id = create_run_id(
            config_hash=config_hash or "manual",
            experiment_id=experiment_id,
        )

    artifacts = RunArtifacts(run_id=run_id, artifact_root=artifact_root)
    artifacts.ensure_directories()
    artifacts.write_repro_info()

    return artifacts
