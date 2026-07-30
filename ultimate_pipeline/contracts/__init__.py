"""
Contracts module - Pydantic models for configuration and validation.

This module provides structured validation for:
- Experiment configurations
- Agent sync contracts
- Artifact schemas
"""

from ultimate_pipeline.contracts.experiment_config import (
    ExperimentConfigModel,
    CarlaConfig,
    DeterminismConfig,
    InputsConfig,
    OutputsConfig,
    AgentSyncRef,
    MetricConfig,
)
from ultimate_pipeline.contracts.agent_sync import (
    AgentSyncContract,
    SensorRigContract,
    BboxContract,
    load_agent_sync,
    validate_agent_sync,
)
from ultimate_pipeline.contracts.coordinate_contract import (
    C44V01Verification,
    build_c44v01_verification,
    write_c44v01_reports,
)
from ultimate_pipeline.contracts.artifacts import (
    RunArtifacts,
    create_run_id,
    ensure_run_directory,
)

__all__ = [
    "ExperimentConfigModel",
    "CarlaConfig",
    "DeterminismConfig",
    "InputsConfig",
    "OutputsConfig",
    "AgentSyncRef",
    "MetricConfig",
    "AgentSyncContract",
    "SensorRigContract",
    "BboxContract",
    "load_agent_sync",
    "validate_agent_sync",
    "C44V01Verification",
    "build_c44v01_verification",
    "write_c44v01_reports",
    "RunArtifacts",
    "create_run_id",
    "ensure_run_directory",
]
