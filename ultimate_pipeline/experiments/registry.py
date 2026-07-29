"""
Experiment Registry

Central registry of all available experiments.
Each experiment has a stable ID and a callable entrypoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ultimate_pipeline.contracts.experiment_config import ExperimentConfigModel
    from ultimate_pipeline.contracts.artifacts import RunArtifacts


@dataclass
class ExperimentResult:
    """Result of an experiment run."""

    success: bool
    metrics: Dict[str, Any]
    artifacts: List[str]
    error: Optional[str] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


@dataclass
class ExperimentDefinition:
    """Definition of a registered experiment."""

    id: str
    name: str
    description: str
    entrypoint: Callable[["ExperimentConfigModel", "RunArtifacts"], ExperimentResult]
    requires_carla: bool = False
    tags: List[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


# Global experiment registry
EXPERIMENTS: Dict[str, ExperimentDefinition] = {}


def register_experiment(
    id: str,
    name: str,
    description: str,
    requires_carla: bool = False,
    tags: Optional[List[str]] = None,
):
    """
    Decorator to register an experiment.

    Usage:
        @register_experiment(
            id="domain_gap_structural",
            name="Structural Domain Gap",
            description="Compute structural domain gap between manual and auto maps",
        )
        def run_domain_gap(config: ExperimentConfigModel, artifacts: RunArtifacts) -> ExperimentResult:
            ...
    """
    def decorator(func: Callable) -> Callable:
        EXPERIMENTS[id] = ExperimentDefinition(
            id=id,
            name=name,
            description=description,
            entrypoint=func,
            requires_carla=requires_carla,
            tags=tags or [],
        )
        return func
    return decorator


def get_experiment(experiment_id: str) -> Optional[ExperimentDefinition]:
    """Get experiment definition by ID."""
    return EXPERIMENTS.get(experiment_id)


def list_experiments(
    filter_carla: Optional[bool] = None,
    filter_tags: Optional[List[str]] = None,
) -> List[ExperimentDefinition]:
    """
    List registered experiments with optional filtering.

    Args:
        filter_carla: If True, only return CARLA experiments. If False, only non-CARLA.
        filter_tags: If provided, only return experiments with at least one matching tag.
    """
    results = list(EXPERIMENTS.values())

    if filter_carla is not None:
        results = [e for e in results if e.requires_carla == filter_carla]

    if filter_tags:
        tag_set = set(filter_tags)
        results = [e for e in results if tag_set & set(e.tags)]

    return results


# =============================================================================
# Built-in experiment implementations
# =============================================================================


@register_experiment(
    id="pipeline_full",
    name="Full Map Pipeline",
    description="Run the complete OSM→OpenDRIVE→CARLA pipeline",
    requires_carla=False,
    tags=["pipeline", "map-generation"],
)
def exp_pipeline_full(config: "ExperimentConfigModel", artifacts: "RunArtifacts") -> ExperimentResult:
    """Run the full map generation pipeline."""
    try:
        from ultimate_pipeline.main_pipeline import main as pipeline_main

        # Run pipeline (it uses its own output handling)
        pipeline_main()

        return ExperimentResult(
            success=True,
            metrics={"status": "completed"},
            artifacts=["08_final.xodr", "tiles/", "logs/"],
        )
    except Exception as e:
        return ExperimentResult(
            success=False,
            metrics={},
            artifacts=[],
            error=str(e),
        )


@register_experiment(
    id="domain_gap_structural",
    name="Structural Domain Gap",
    description="Compute structural domain gap between manual and auto-generated maps",
    requires_carla=False,
    tags=["domain-gap", "structural", "offline"],
)
def exp_domain_gap_structural(config: "ExperimentConfigModel", artifacts: "RunArtifacts") -> ExperimentResult:
    """Run structural domain gap analysis."""
    try:
        import sys

        # Build args from config
        args = []
        if config.inputs.auto_xodr:
            args.extend(["--auto_xodr", config.inputs.auto_xodr])
        if config.inputs.manual_xodr:
            args.extend(["--manual_xodr", config.inputs.manual_xodr])
        # Set output directory to artifacts location
        args.extend(["--output_dir", str(artifacts.run_dir)])

        # Import and run via CLI entry point
        from ultimate_pipeline.run_full_domain_gap import _cli_main

        # Temporarily modify sys.argv
        old_argv = sys.argv
        sys.argv = ["run_full_domain_gap"] + args

        try:
            exit_code = _cli_main()
        finally:
            sys.argv = old_argv

        success = exit_code == 0

        return ExperimentResult(
            success=success,
            metrics={"status": "completed" if success else "failed", "exit_code": exit_code},
            artifacts=[
                "domain_gap/full_report.json",
                "domain_gap/summary.csv",
                "domain_gap/tile_pairing_report.json",
            ],
            error=None if success else f"Domain gap analysis exited with code {exit_code}",
        )
    except Exception as e:
        return ExperimentResult(
            success=False,
            metrics={},
            artifacts=[],
            error=str(e),
        )


@register_experiment(
    id="determinism_audit",
    name="Determinism Audit",
    description="Run K pipeline executions to assess determinism",
    requires_carla=False,
    tags=["determinism", "reproducibility", "offline"],
)
def exp_determinism_audit(config: "ExperimentConfigModel", artifacts: "RunArtifacts") -> ExperimentResult:
    """Run determinism audit."""
    try:
        from ultimate_pipeline.run_determinism_audit import main as audit_main
        import sys

        # Get K from config
        k = config.parameters.get("k", config.parameters.get("runs", 5))

        old_argv = sys.argv
        sys.argv = [
            "run_determinism_audit",
            "--runs", str(k),
            "--out", str(artifacts.run_dir / "determinism_audit"),
        ]

        try:
            audit_main()
        finally:
            sys.argv = old_argv

        return ExperimentResult(
            success=True,
            metrics={"runs_requested": k},
            artifacts=[
                "determinism_audit/determinism_report.json",
                "determinism_audit/determinism_hashes.csv",
            ],
        )
    except Exception as e:
        return ExperimentResult(
            success=False,
            metrics={},
            artifacts=[],
            error=str(e),
        )


@register_experiment(
    id="perception_capture",
    name="Perception Capture",
    description="Capture perception data from CARLA with calibrated sensors",
    requires_carla=True,
    tags=["perception", "carla", "capture"],
)
def exp_perception_capture(config: "ExperimentConfigModel", artifacts: "RunArtifacts") -> ExperimentResult:
    """Run perception capture in CARLA."""
    try:
        from ultimate_pipeline.tools.run_perception_safe import main as perception_main
        import sys

        old_argv = sys.argv
        sys.argv = [
            "run_perception_safe",
            "--out", str(artifacts.run_dir / "perception"),
            "--spawn-qa-objects",
            "--lidar-overlay",
        ]

        try:
            perception_main()
        finally:
            sys.argv = old_argv

        return ExperimentResult(
            success=True,
            metrics={"status": "completed"},
            artifacts=[
                "perception/perception_status.json",
                "perception/rig_verification.json",
            ],
        )
    except Exception as e:
        return ExperimentResult(
            success=False,
            metrics={},
            artifacts=[],
            error=str(e),
        )


@register_experiment(
    id="generalization_sweep",
    name="Generalization K-Sweep",
    description="Train and evaluate models across K values for generalization analysis",
    requires_carla=False,
    tags=["generalization", "training", "evaluation"],
)
def exp_generalization_sweep(config: "ExperimentConfigModel", artifacts: "RunArtifacts") -> ExperimentResult:
    """Run generalization experiments."""
    try:
        from ultimate_pipeline.run_generalization_experiments import main as gen_main
        import sys

        k_values = config.parameters.get("k_values", [1, 3, 5])

        old_argv = sys.argv
        sys.argv = [
            "run_generalization_experiments",
            "--k_values", *[str(k) for k in k_values],
            "--out_dir", str(artifacts.run_dir / "generalization"),
        ]

        # Add dataset paths from config
        if config.inputs.dataset:
            sys.argv.extend(["--train_gen_datasets", config.inputs.dataset])
        if config.inputs.real_u_dir:
            sys.argv.extend(["--real_u_dir", config.inputs.real_u_dir])

        try:
            gen_main()
        finally:
            sys.argv = old_argv

        return ExperimentResult(
            success=True,
            metrics={"k_values": k_values},
            artifacts=[
                "generalization/generalization_results.csv",
                "generalization/gen_many_curve.csv",
            ],
        )
    except Exception as e:
        return ExperimentResult(
            success=False,
            metrics={},
            artifacts=[],
            error=str(e),
        )


@register_experiment(
    id="smoke_test",
    name="Smoke Test",
    description="Fast headless smoke test for CI/CD",
    requires_carla=False,
    tags=["test", "smoke", "ci"],
)
def exp_smoke_test(config: "ExperimentConfigModel", artifacts: "RunArtifacts") -> ExperimentResult:
    """Run smoke test."""
    errors = []
    warnings = []
    metrics = {}

    # Test 1: Config parsing
    try:
        from ultimate_pipeline.contracts.experiment_config import ExperimentConfigModel
        test_config = ExperimentConfigModel(experiment_id="test")
        metrics["config_parsing"] = "pass"
    except Exception as e:
        errors.append(f"Config parsing failed: {e}")
        metrics["config_parsing"] = "fail"

    # Test 2: Agent sync validation
    try:
        from ultimate_pipeline.contracts.agent_sync import validate_agent_sync
        result = validate_agent_sync()
        if result["valid"]:
            metrics["agent_sync"] = "pass"
        else:
            warnings.extend(result["warnings"])
            if result["errors"]:
                metrics["agent_sync"] = "warn"
            else:
                metrics["agent_sync"] = "pass"
    except Exception as e:
        warnings.append(f"Agent sync not configured: {e}")
        metrics["agent_sync"] = "skip"

    # Test 3: Import core modules
    try:
        from ultimate_pipeline.main_pipeline import main
        from ultimate_pipeline.run_full_domain_gap import run_full_domain_gap
        metrics["imports"] = "pass"
    except Exception as e:
        errors.append(f"Core imports failed: {e}")
        metrics["imports"] = "fail"

    # Test 4: Artifact creation
    try:
        test_file = artifacts.run_dir / "smoke_test_marker.txt"
        test_file.write_text("smoke test", encoding="utf-8")
        assert test_file.exists()
        metrics["artifacts"] = "pass"
    except Exception as e:
        errors.append(f"Artifact creation failed: {e}")
        metrics["artifacts"] = "fail"

    success = len(errors) == 0

    return ExperimentResult(
        success=success,
        metrics=metrics,
        artifacts=["smoke_test_marker.txt"],
        error="\n".join(errors) if errors else None,
        warnings=warnings,
    )


def discover_experiments() -> None:
    """
    Discover and import experiment modules to trigger registration.

    This function imports modules that contain @register_experiment decorators.
    """
    import importlib
    from pathlib import Path

    # Get the experiments directory
    experiments_dir = Path(__file__).parent

    # Look for thesis subpackage
    thesis_dir = experiments_dir / "thesis"
    if thesis_dir.is_dir():
        # Check for __init__.py to confirm it's a package
        if (thesis_dir / "__init__.py").exists():
            try:
                # Import thesis modules
                for py_file in thesis_dir.glob("*.py"):
                    if py_file.name.startswith("_"):
                        continue
                    module_name = f"ultimate_pipeline.experiments.thesis.{py_file.stem}"
                    try:
                        importlib.import_module(module_name)
                    except Exception:
                        pass  # Skip modules that fail to import
            except Exception:
                pass


# Run discovery on module load (wrapped in try/except for robustness)
try:
    discover_experiments()
except Exception:
    pass  # Discovery is optional; built-in experiments are always available
