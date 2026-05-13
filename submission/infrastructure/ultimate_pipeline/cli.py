"""
Ultimate Pipeline Canonical CLI

This is the single supported entrypoint for running experiments.

Usage:
    python -m ultimate_pipeline.cli doctor
    python -m ultimate_pipeline.cli exp list
    python -m ultimate_pipeline.cli exp run <experiment_id> --config <path>
    python -m ultimate_pipeline.cli test smoke
    python -m ultimate_pipeline.cli test e2e
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click

# Bootstrap console for Unicode support
try:
    from ultimate_pipeline.utils.bootstrap import bootstrap_console
    bootstrap_console()
except ImportError:
    pass

try:
    from ultimate_pipeline.utils.timestamped_print import enable_timestamped_print
    enable_timestamped_print()
except ImportError:
    pass


# =============================================================================
# Main CLI Group
# =============================================================================

@click.group()
@click.version_option(version="2.0.0", prog_name="up")
def cli() -> None:
    """
    Ultimate Pipeline CLI (up)

    Canonical CLI for running experiments, tests, and diagnostics.

    \b
    Commands:
      doctor    Check system configuration and dependencies
      exp       Experiment management (list, run)
      test      Run tests (smoke, e2e)

    \b
    Examples:
      up doctor
      up exp list
      up exp run domain_gap_structural --config configs/example.yaml
      up test smoke
    """
    pass


# =============================================================================
# Doctor Command
# =============================================================================

@cli.command()
@click.option("--init-agent-sync", is_flag=True, help="Create agent_sync.yaml if missing")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def doctor(init_agent_sync: bool, verbose: bool) -> None:
    """
    Check system configuration and dependencies.

    Validates:
    - Python version
    - Required dependencies
    - CARLA availability (optional)
    - agent_sync.yaml schema validity
    """
    click.echo("=" * 60)
    click.echo("Ultimate Pipeline Doctor")
    click.echo("=" * 60)
    click.echo()

    all_ok = True

    # 1. Python version
    click.echo("[1/5] Python version...")
    py_version = sys.version_info
    if py_version >= (3, 10):
        click.echo(f"  ✓ Python {py_version.major}.{py_version.minor}.{py_version.micro}")
    else:
        click.echo(f"  ✗ Python {py_version.major}.{py_version.minor} (requires 3.10+)")
        all_ok = False

    # 2. Required dependencies
    click.echo("[2/5] Required dependencies...")
    required_deps = [
        ("pydantic", "pydantic"),
        ("click", "click"),
        ("numpy", "numpy"),
    ]
    optional_deps = [
        ("yaml", "PyYAML"),
        ("scipy", "scipy"),
        ("torch", "torch"),
    ]

    for module, name in required_deps:
        try:
            __import__(module)
            if verbose:
                click.echo(f"  ✓ {name}")
        except ImportError:
            click.echo(f"  ✗ {name} (required)")
            all_ok = False

    for module, name in optional_deps:
        try:
            __import__(module)
            if verbose:
                click.echo(f"  ✓ {name} (optional)")
        except ImportError:
            if verbose:
                click.echo(f"  ○ {name} (optional, not installed)")

    if all_ok:
        click.echo("  ✓ All required dependencies installed")

    # 3. CARLA availability
    click.echo("[3/5] CARLA availability...")
    carla_host = os.getenv("CARLA_HOST", "127.0.0.1")
    carla_port = int(os.getenv("CARLA_PORT", "2000"))

    try:
        import carla
        client = carla.Client(carla_host, carla_port)
        client.set_timeout(5.0)
        version = client.get_server_version()
        click.echo(f"  ✓ CARLA {version} at {carla_host}:{carla_port}")
    except ImportError:
        click.echo("  ○ CARLA Python API not installed (optional)")
    except Exception as e:
        click.echo(f"  ○ CARLA not reachable at {carla_host}:{carla_port} (optional)")
        if verbose:
            click.echo(f"    Error: {e}")

    # 4. Agent sync validation
    click.echo("[4/5] Agent sync contract...")

    if init_agent_sync:
        # Create agent_sync.yaml if missing
        yaml_path = Path("agent_sync.yaml")
        if not yaml_path.exists():
            try:
                from ultimate_pipeline.contracts.agent_sync import AgentSyncContract
                contract = AgentSyncContract()
                contract.save(yaml_path)
                click.echo(f"  ✓ Created {yaml_path}")
            except Exception as e:
                click.echo(f"  ✗ Failed to create agent_sync.yaml: {e}")
                all_ok = False
        else:
            click.echo(f"  ○ {yaml_path} already exists")

    try:
        from ultimate_pipeline.contracts.agent_sync import validate_agent_sync
        result = validate_agent_sync()

        if result["valid"]:
            click.echo(f"  ✓ agent_sync.yaml valid (v{result['version']})")
            if result["path"]:
                if verbose:
                    click.echo(f"    Path: {result['path']}")
        else:
            for error in result["errors"]:
                click.echo(f"  ✗ {error}")
                all_ok = False
            for warning in result["warnings"]:
                click.echo(f"  ⚠ {warning}")

    except Exception as e:
        click.echo(f"  ⚠ {e}")
        click.echo("    Run: up doctor --init-agent-sync")

    # 5. Artifact directory
    click.echo("[5/5] Artifact directory...")
    artifact_root = Path("artifacts/runs")
    if artifact_root.exists():
        run_count = len(list(artifact_root.iterdir())) if artifact_root.is_dir() else 0
        click.echo(f"  ✓ {artifact_root} ({run_count} runs)")
    else:
        click.echo(f"  ○ {artifact_root} (will be created on first run)")

    # Summary
    click.echo()
    click.echo("=" * 60)
    if all_ok:
        click.echo("✓ All checks passed")
        sys.exit(0)
    else:
        click.echo("✗ Some checks failed")
        sys.exit(1)


# =============================================================================
# Experiment Commands
# =============================================================================

@cli.group()
def exp() -> None:
    """Experiment management commands."""
    pass


@exp.command("list")
@click.option("--carla-only", is_flag=True, help="Show only experiments requiring CARLA")
@click.option("--offline-only", is_flag=True, help="Show only offline experiments")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def exp_list(carla_only: bool, offline_only: bool, as_json: bool) -> None:
    """List available experiments."""
    from ultimate_pipeline.experiments.registry import list_experiments

    filter_carla = None
    if carla_only:
        filter_carla = True
    elif offline_only:
        filter_carla = False

    experiments = list_experiments(filter_carla=filter_carla)

    if as_json:
        data = [
            {
                "id": e.id,
                "name": e.name,
                "description": e.description,
                "requires_carla": e.requires_carla,
                "tags": e.tags,
            }
            for e in experiments
        ]
        click.echo(json.dumps(data, indent=2))
    else:
        if not experiments:
            click.echo("No experiments found.")
            return

        click.echo(f"{'ID':<30} {'Name':<30} {'CARLA':<8} Tags")
        click.echo("-" * 80)
        for e in experiments:
            carla_icon = "✓" if e.requires_carla else "-"
            tags = ", ".join(e.tags) if e.tags else "-"
            click.echo(f"{e.id:<30} {e.name:<30} {carla_icon:<8} {tags}")


@exp.command("run")
@click.argument("experiment_id")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to config YAML")
@click.option("--backend", type=click.Choice(["local", "slurm"]), default="local", help="Execution backend")
@click.option("--output", "-o", type=click.Path(), help="Output directory override")
@click.option("--seed", "-s", type=int, help="Random seed")
@click.option("--strict", is_flag=True, help="Enable strict validation mode")
@click.option("--dry-run", is_flag=True, help="Validate config without running")
def exp_run(
    experiment_id: str,
    config: Optional[str],
    backend: str,
    output: Optional[str],
    seed: Optional[int],
    strict: bool,
    dry_run: bool,
) -> None:
    """
    Run an experiment.

    EXPERIMENT_ID is the registered experiment identifier.
    Use 'up exp list' to see available experiments.
    """
    from ultimate_pipeline.experiments.registry import get_experiment
    from ultimate_pipeline.experiments.unified_runner import run_experiment

    # Check experiment exists
    experiment = get_experiment(experiment_id)
    if experiment is None:
        click.echo(f"Error: Unknown experiment '{experiment_id}'")
        click.echo("Use 'up exp list' to see available experiments.")
        sys.exit(1)

    # Build overrides
    overrides = {}
    if output:
        overrides["outputs.artifact_root"] = output
    if seed is not None:
        overrides["seed"] = seed

    if dry_run:
        click.echo(f"[DRY RUN] Would run: {experiment_id}")
        click.echo(f"  Config: {config or 'default'}")
        click.echo(f"  Backend: {backend}")
        click.echo(f"  Strict: {strict}")
        if overrides:
            click.echo(f"  Overrides: {overrides}")
        return

    # Run experiment
    click.echo(f"Running experiment: {experiment.name}")
    click.echo(f"  ID: {experiment_id}")
    click.echo(f"  Requires CARLA: {experiment.requires_carla}")

    try:
        result = run_experiment(
            experiment_id=experiment_id,
            config_path=config,
            overrides=overrides,
            seed=seed,
            strict=strict,
        )

        if result["success"]:
            click.echo()
            click.echo(f"✓ Experiment completed successfully")
            click.echo(f"  Run ID: {result['run_id']}")
            click.echo(f"  Duration: {result.get('duration_s', 0):.2f}s")
            click.echo(f"  Output: artifacts/runs/{result['run_id']}/")
            sys.exit(0)
        else:
            click.echo()
            click.echo(f"✗ Experiment failed")
            click.echo(f"  Run ID: {result['run_id']}")
            if result.get("error"):
                click.echo(f"  Error: {result['error'][:200]}...")
            sys.exit(1)

    except Exception as e:
        click.echo(f"✗ Failed to run experiment: {e}")
        sys.exit(1)


# =============================================================================
# Test Commands
# =============================================================================

@cli.group()
def test() -> None:
    """Test commands."""
    pass


@test.command("smoke")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def test_smoke(verbose: bool) -> None:
    """
    Run fast headless smoke test.

    Does NOT require CARLA. Tests:
    - Config parsing
    - Agent sync validation
    - Core module imports
    - Artifact creation
    """
    from ultimate_pipeline.experiments.unified_runner import run_experiment

    click.echo("Running smoke test...")

    result = run_experiment(
        experiment_id="smoke_test",
        strict=False,
    )

    if result["success"]:
        click.echo()
        click.echo("✓ Smoke test passed")
        if verbose:
            for key, value in result["metrics"].items():
                click.echo(f"  {key}: {value}")
        sys.exit(0)
    else:
        click.echo()
        click.echo("✗ Smoke test failed")
        if result.get("error"):
            click.echo(f"  Error: {result['error']}")
        sys.exit(1)


@test.command("e2e")
@click.option("--timeout", default=300, help="Timeout in seconds")
def test_e2e(timeout: int) -> None:
    """
    Run end-to-end integration test.

    REQUIRES CARLA. Skipped unless UP_ENABLE_CARLA_TESTS=1.
    """
    if os.getenv("UP_ENABLE_CARLA_TESTS") != "1":
        click.echo("⊘ E2E tests skipped (set UP_ENABLE_CARLA_TESTS=1 to enable)")
        sys.exit(0)

    click.echo(f"Running E2E tests (timeout: {timeout}s)...")

    # Check CARLA first
    try:
        import carla
        client = carla.Client("127.0.0.1", 2000)
        client.set_timeout(10.0)
        client.get_server_version()
    except Exception as e:
        click.echo(f"✗ CARLA not available: {e}")
        sys.exit(1)

    # Run perception capture test
    from ultimate_pipeline.experiments.unified_runner import run_experiment

    result = run_experiment(
        experiment_id="perception_capture",
        overrides={
            "carla.timeout_s": timeout,
            "carla.scenario_timeout_s": timeout,
        },
    )

    if result["success"]:
        click.echo("✓ E2E tests passed")
        sys.exit(0)
    else:
        click.echo(f"✗ E2E tests failed: {result.get('error', 'unknown error')}")
        sys.exit(1)


# =============================================================================
# Legacy Commands (deprecated, forward to new structure)
# =============================================================================

@cli.command("build-map", hidden=True)
def build_map() -> None:
    """[DEPRECATED] Use 'up exp run pipeline_full' instead."""
    click.echo("DEPRECATED: Use 'up exp run pipeline_full' instead")
    from ultimate_pipeline.main_pipeline import main as pipeline_main
    pipeline_main()


@cli.command("generate-dataset", hidden=True)
@click.option("--dataset", default="auto_dataset")
@click.option("--frames", default=200, type=int)
@click.option("--fps", default=20, type=int)
@click.option("--calib", default=None)
@click.option("--camera", default=None)
@click.option("--all-cameras", is_flag=True)
@click.option("--no-aug", is_flag=True)
def generate_dataset(dataset, frames, fps, calib, camera, all_cameras, no_aug):
    """[DEPRECATED] Use 'up exp run perception_capture' instead."""
    click.echo("DEPRECATED: Use 'up exp run perception_capture' instead")
    # Forward to old implementation for backward compatibility
    from ultimate_pipeline.perception.perception_runner_local_aug import PerceptionRunnerLocalAug
    from ultimate_pipeline.config.settings import SETTINGS

    runner = PerceptionRunnerLocalAug(
        fps=fps,
        calib_file=(calib or getattr(SETTINGS, "SENSOR_CALIB_JSON", "calib_data.json")),
        enable_augmentation=(not no_aug),
        verbose=True,
    )
    out_dir = runner.run_capture_session(
        dataset,
        num_frames=frames,
        camera_name=camera,
        record_all_cameras=all_cameras,
    )
    click.echo(f"[OK] Dataset written to: {out_dir}")


# =============================================================================
# Entry Point
# =============================================================================

def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
