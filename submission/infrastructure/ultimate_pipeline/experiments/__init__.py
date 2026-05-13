"""
Experiments Module

Provides experiment registration, discovery, and execution.

Usage:
    from ultimate_pipeline.experiments import get_experiment, list_experiments, run_experiment

    # List available experiments
    for exp in list_experiments():
        print(f"{exp.id}: {exp.name}")

    # Run an experiment
    result = run_experiment("smoke_test")
"""

from ultimate_pipeline.experiments.registry import (
    ExperimentDefinition,
    ExperimentResult,
    EXPERIMENTS,
    get_experiment,
    list_experiments,
    register_experiment,
)

from ultimate_pipeline.experiments.unified_runner import (
    UnifiedRunner,
    run_experiment,
)

__all__ = [
    # Registry
    "ExperimentDefinition",
    "ExperimentResult",
    "EXPERIMENTS",
    "get_experiment",
    "list_experiments",
    "register_experiment",
    # Runner
    "UnifiedRunner",
    "run_experiment",
]
