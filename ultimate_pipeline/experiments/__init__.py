"""Experiment registration, discovery, and execution helpers.

Usage:
    from ultimate_pipeline.experiments import get_experiment, list_experiments, run_experiment

Importing this package is intentionally lightweight. Runner objects are
resolved lazily so a wheel smoke test can verify package discovery without
requiring the full experiment/runtime dependency stack at package import time.
"""

from __future__ import annotations

from typing import Any

from ultimate_pipeline.experiments.registry import (
    ExperimentDefinition,
    ExperimentResult,
    EXPERIMENTS,
    get_experiment,
    list_experiments,
    register_experiment,
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


def __getattr__(name: str) -> Any:
    if name in {"UnifiedRunner", "run_experiment"}:
        from ultimate_pipeline.experiments.unified_runner import (
            UnifiedRunner,
            run_experiment,
        )

        globals()["UnifiedRunner"] = UnifiedRunner
        globals()["run_experiment"] = run_experiment
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
