"""
Experiment Schema

Defines the canonical structure of an experiment in the pipeline.
Used for reproducibility, tracking, and HPC execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class ExperimentConfig:
    """
    Canonical experiment description.
    """

    name: str
    map_id: str
    perception_model: str
    seed: int = 0

    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "map_id": self.map_id,
            "perception_model": self.perception_model,
            "seed": self.seed,
            "parameters": self.parameters,
        }
