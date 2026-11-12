"""Versioned offline experiment plans. Saving a plan never starts a simulator."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA = "carla-ops-experiment-plan/v1"
EXPERIMENTS = (
    "Road grade / elevation analysis", "OpenDRIVE topology and junction continuity",
    "Sensor timestamp and frame alignment", "Traffic density and routing",
    "Camera intrinsics and extrinsics", "Weather robustness",
    "GNSS / IMU alignment", "Perception and localization evaluation",
    "Map geometric fidelity", "Operational fuzzer (offline corpus)",
)


@dataclass(frozen=True)
class ExperimentPlan:
    name: str
    experiment: str
    seed: int
    local_map: str = ""
    profile: str = ""
    notes: str = ""
    schema: str = SCHEMA
    execution_state: str = "PLAN_ONLY_NOT_EXECUTED"

    def __post_init__(self):
        if not 1 <= len(self.name.strip()) <= 120:
            raise ValueError("plan name must contain 1..120 characters")
        if self.experiment not in EXPERIMENTS:
            raise ValueError("unknown experiment family")
        if not 0 <= self.seed <= 2**32 - 1:
            raise ValueError("seed outside unsigned 32-bit range")
        if len(self.notes) > 4000:
            raise ValueError("notes exceed 4000 characters")
        if self.execution_state != "PLAN_ONLY_NOT_EXECUTED" or self.schema != SCHEMA:
            raise ValueError("plans cannot represent execution results")


def save_plan(plan: ExperimentPlan, target: str | Path) -> Path:
    """Atomic write, no unsafe implicit directory traversal or running tasks."""
    path = Path(target)
    if path.suffix.lower() != ".json":
        raise ValueError("plan must be written to a .json file")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".plan_", suffix=".tmp", delete=False) as tmp:
            temp_path = Path(tmp.name)
            json.dump(asdict(plan), tmp, sort_keys=True, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(temp_path, path)
        return path
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def read_plan(target: str | Path) -> ExperimentPlan:
    path = Path(target)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("plan exceeds maximum 1 MiB")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError("plan must be a JSON object")
    expected = set(ExperimentPlan.__dataclass_fields__)
    if set(record) != expected:
        raise ValueError("unknown or missing plan fields")
    return ExperimentPlan(**record)
