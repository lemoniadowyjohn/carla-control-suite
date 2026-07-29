"""
Unified Experiment Runner

Orchestrates experiment execution with standardized:
- Configuration resolution
- Artifact management
- Logging
- Error handling
"""

from __future__ import annotations

import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Union

from ultimate_pipeline.contracts.experiment_config import ExperimentConfigModel
from ultimate_pipeline.contracts.artifacts import RunArtifacts, ensure_run_directory
from ultimate_pipeline.contracts.agent_sync import load_agent_sync, validate_agent_sync
from ultimate_pipeline.experiments.registry import (
    ExperimentResult,
    get_experiment,
    list_experiments,
)


class UnifiedRunner:
    """
    Unified experiment runner.

    Handles:
    - Config loading and resolution
    - CARLA availability checking
    - Artifact directory setup
    - Experiment execution with timeouts
    - Result summarization
    """

    def __init__(
        self,
        config: Union[ExperimentConfigModel, str, Path, Dict[str, Any]],
        overrides: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize runner with configuration.

        Args:
            config: ExperimentConfigModel, path to config file, or dict
            overrides: CLI overrides to apply
        """
        self.logger = logging.getLogger(__name__)

        # Load/resolve config
        if isinstance(config, ExperimentConfigModel):
            self.config = config
        elif isinstance(config, (str, Path)):
            self.config = ExperimentConfigModel.load(config)
        elif isinstance(config, dict):
            self.config = ExperimentConfigModel.model_validate(config)
        else:
            raise TypeError(f"Invalid config type: {type(config)}")

        # Apply overrides
        if overrides:
            self.config = self.config.apply_overrides(overrides)

        # Initialize artifacts
        self.artifacts: Optional[RunArtifacts] = None

    def check_carla(self) -> bool:
        """Check if CARLA is available and reachable."""
        if not self.config.carla.required:
            return True

        try:
            import carla
            client = carla.Client(
                self.config.carla.host,
                self.config.carla.port,
            )
            client.set_timeout(self.config.carla.timeout_s)
            version = client.get_server_version()
            self.logger.info(f"CARLA server version: {version}")
            return True
        except ImportError:
            self.logger.error("CARLA Python API not installed")
            return False
        except Exception as e:
            self.logger.error(f"Cannot reach CARLA at {self.config.carla.host}:{self.config.carla.port}: {e}")
            return False

    def validate_agent_sync(self) -> bool:
        """Validate agent_sync contract."""
        result = validate_agent_sync(
            path=self.config.agent_sync.path if self.config.agent_sync.path != "agent_sync.yaml" else None,
            required_version=self.config.agent_sync.required_version,
            strict=self.config.agent_sync.strict_validation,
        )

        if result["warnings"]:
            for warning in result["warnings"]:
                self.logger.warning(f"Agent sync: {warning}")

        if not result["valid"]:
            for error in result["errors"]:
                self.logger.error(f"Agent sync: {error}")
            return False

        return True

    def setup_artifacts(self) -> RunArtifacts:
        """Set up artifact directory for this run."""
        self.artifacts = ensure_run_directory(
            artifact_root=self.config.outputs.artifact_root,
            run_id=self.config.outputs.run_id,
            config_hash=self.config.config_hash(),
            experiment_id=self.config.experiment_id,
        )

        # Write resolved config
        self.artifacts.write_config(self.config)

        return self.artifacts

    def run(self) -> Dict[str, Any]:
        """
        Execute the experiment.

        Returns:
            Dict with run results including:
            - run_id
            - success
            - metrics
            - artifacts
            - error (if failed)
        """
        start_time = time.time()

        # Setup artifacts
        self.setup_artifacts()

        # Setup logging to file
        log_file = self.artifacts.logs_dir / "run.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))
        logging.getLogger().addHandler(file_handler)

        self.logger.info(f"Starting experiment: {self.config.experiment_id}")
        self.logger.info(f"Run ID: {self.artifacts.run_id}")
        self.logger.info(f"Output: {self.artifacts.run_dir}")

        result: Dict[str, Any] = {
            "run_id": self.artifacts.run_id,
            "experiment_id": self.config.experiment_id,
            "success": False,
            "metrics": {},
            "artifacts": [],
            "error": None,
            "warnings": [],
        }

        try:
            # Validate agent_sync (non-blocking warning for now)
            if not self.validate_agent_sync():
                result["warnings"].append("Agent sync validation failed")
                if self.config.agent_sync.strict_validation:
                    raise RuntimeError("Agent sync validation failed in strict mode")

            # Check CARLA if required
            experiment = get_experiment(self.config.experiment_id)
            if experiment and experiment.requires_carla:
                if not self.check_carla():
                    raise RuntimeError(
                        f"CARLA required but not available at "
                        f"{self.config.carla.host}:{self.config.carla.port}"
                    )

            # Get experiment from registry
            if experiment is None:
                raise ValueError(f"Unknown experiment: {self.config.experiment_id}")

            # Run the experiment
            self.logger.info(f"Executing: {experiment.name}")
            exp_result = experiment.entrypoint(self.config, self.artifacts)

            result["success"] = exp_result.success
            result["metrics"] = exp_result.metrics
            result["artifacts"] = exp_result.artifacts
            result["error"] = exp_result.error
            result["warnings"].extend(exp_result.warnings)

        except Exception as e:
            self.logger.exception("Experiment failed")
            result["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

        finally:
            # Calculate duration
            duration = time.time() - start_time
            result["duration_s"] = duration

            # Finalize artifacts
            if self.artifacts:
                self.artifacts.finalize(
                    success=result["success"],
                    experiment_id=self.config.experiment_id,
                    metrics=result["metrics"],
                    error=result["error"],
                    duration_s=duration,
                )

            # Remove file handler
            logging.getLogger().removeHandler(file_handler)
            file_handler.close()

        self.logger.info(
            f"Experiment {'succeeded' if result['success'] else 'failed'} "
            f"in {duration:.2f}s"
        )

        return result


def run_experiment(
    experiment_id: str,
    config_path: Optional[Union[str, Path]] = None,
    overrides: Optional[Dict[str, Any]] = None,
    artifact_root: str = "artifacts/runs",
    seed: Optional[int] = None,
    strict: bool = False,
) -> Dict[str, Any]:
    """
    Convenience function to run an experiment.

    Args:
        experiment_id: ID of experiment to run
        config_path: Path to config file (optional)
        overrides: CLI overrides
        artifact_root: Base directory for artifacts
        seed: Random seed
        strict: Enable strict validation

    Returns:
        Run result dict
    """
    # Build config
    if config_path:
        config = ExperimentConfigModel.load(config_path)
    else:
        config = ExperimentConfigModel(experiment_id=experiment_id)

    # Apply basic overrides
    all_overrides = {
        "experiment_id": experiment_id,
        "outputs.artifact_root": artifact_root,
    }
    if seed is not None:
        all_overrides["seed"] = seed
    if strict:
        all_overrides["agent_sync.strict_validation"] = True

    if overrides:
        all_overrides.update(overrides)

    # Run
    runner = UnifiedRunner(config, overrides=all_overrides)
    return runner.run()
