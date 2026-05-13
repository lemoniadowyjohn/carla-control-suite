"""
Experiment Configuration Models

Pydantic models for experiment configuration validation and resolution.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class DeterminismConfig(BaseModel):
    """Configuration for determinism/reproducibility."""

    enabled: bool = True
    strict: bool = False
    seed: Optional[int] = None

    @field_validator("seed")
    @classmethod
    def validate_seed(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Seed must be non-negative")
        return v


class InputsConfig(BaseModel):
    """Input configuration for experiments."""

    map: Optional[str] = None
    scenario: Optional[str] = None
    dataset: Optional[str] = None
    manual_xodr: Optional[str] = None
    auto_xodr: Optional[str] = None
    tiles_dir: Optional[str] = None
    real_u_dir: Optional[str] = None

    @field_validator("map", "scenario", "dataset", "manual_xodr", "auto_xodr", "tiles_dir", "real_u_dir")
    @classmethod
    def resolve_path(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        # Expand environment variables
        import os
        return os.path.expandvars(v)


class CarlaConfig(BaseModel):
    """CARLA server configuration."""

    required: bool = False
    host: str = "127.0.0.1"
    port: int = 2000
    timeout_s: float = 30.0
    startup_timeout_s: float = 60.0
    scenario_timeout_s: float = 300.0

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("timeout_s", "startup_timeout_s", "scenario_timeout_s")
    @classmethod
    def validate_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Timeout must be positive")
        return v


class OutputsConfig(BaseModel):
    """Output configuration."""

    artifact_root: str = "artifacts/runs"
    run_id: Optional[str] = None

    @field_validator("artifact_root")
    @classmethod
    def expand_path(cls, v: str) -> str:
        import os
        return os.path.expandvars(v)


class AgentSyncRef(BaseModel):
    """Reference to agent_sync contract."""

    path: str = "agent_sync.yaml"
    required_version: int = 1
    strict_validation: bool = True


class MetricConfig(BaseModel):
    """Configuration for a single metric."""

    name: str
    enabled: bool = True
    threshold: Optional[float] = None
    params: Dict[str, Any] = Field(default_factory=dict)


class ExperimentConfigModel(BaseModel):
    """
    Canonical experiment configuration model.

    Used for all experiment runs. Supports YAML config files with CLI overrides.
    """

    experiment_id: str
    description: Optional[str] = None
    seed: int = 0

    determinism: DeterminismConfig = Field(default_factory=DeterminismConfig)
    inputs: InputsConfig = Field(default_factory=InputsConfig)
    carla: CarlaConfig = Field(default_factory=CarlaConfig)
    outputs: OutputsConfig = Field(default_factory=OutputsConfig)
    agent_sync: AgentSyncRef = Field(default_factory=AgentSyncRef)
    metrics: List[MetricConfig] = Field(default_factory=list)

    # Additional parameters for experiment-specific configuration
    parameters: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("experiment_id")
    @classmethod
    def validate_experiment_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("experiment_id cannot be empty")
        # Sanitize for filesystem
        import re
        sanitized = re.sub(r'[^\w\-_.]', '_', v.strip())
        return sanitized

    @field_validator("seed")
    @classmethod
    def validate_seed(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Seed must be non-negative")
        return v

    @model_validator(mode="after")
    def sync_seeds(self) -> "ExperimentConfigModel":
        """Ensure determinism seed is synced with top-level seed if not set."""
        if self.determinism.seed is None:
            self.determinism.seed = self.seed
        return self

    def config_hash(self) -> str:
        """Generate a stable hash of the configuration for run_id."""
        # Serialize to JSON with sorted keys for stability
        config_json = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(config_json.encode()).hexdigest()[:8]

    def to_yaml(self) -> str:
        """Export configuration to YAML string."""
        try:
            import yaml
            return yaml.dump(self.model_dump(), default_flow_style=False, sort_keys=False)
        except ImportError:
            # Fallback to JSON if YAML not available
            return json.dumps(self.model_dump(), indent=2, default=str)

    def save(self, path: Union[str, Path]) -> None:
        """Save resolved configuration to file."""
        path = Path(path)
        content = self.to_yaml()
        path.write_text(content, encoding="utf-8")

    @classmethod
    def load(cls, path: Union[str, Path]) -> "ExperimentConfigModel":
        """Load configuration from YAML or JSON file."""
        path = Path(path)
        content = path.read_text(encoding="utf-8")

        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml
                data = yaml.safe_load(content)
            except ImportError:
                raise ImportError("PyYAML required for YAML config files")
        else:
            data = json.loads(content)

        return cls.model_validate(data)

    def apply_overrides(self, overrides: Dict[str, Any]) -> "ExperimentConfigModel":
        """Apply CLI overrides to configuration."""
        data = self.model_dump()

        for key, value in overrides.items():
            if value is None:
                continue

            # Handle nested keys (e.g., "carla.host")
            parts = key.split(".")
            target = data
            for part in parts[:-1]:
                if part not in target:
                    target[part] = {}
                target = target[part]
            target[parts[-1]] = value

        return ExperimentConfigModel.model_validate(data)
