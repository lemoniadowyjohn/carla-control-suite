from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class Entrypoint:
    key: str
    module: str     # python module path
    description: str


ENTRYPOINTS: Dict[str, Entrypoint] = {
    "pipeline": Entrypoint(
        key="pipeline",
        module="ultimate_pipeline.run_pipeline",
        description="Run the full OSM→XODR→CARLA pipeline",
    ),
    "domain_gap": Entrypoint(
        key="domain_gap",
        module="ultimate_pipeline.domain_gap_cli",
        description="Run full domain-gap evaluation (classical + optional GNN)",
    ),
    "debug": Entrypoint(
        key="debug",
        module="ultimate_pipeline.tools.run_debug_pipeline",
        description="Run pipeline with aggressive debug captures",
    ),
    "carla_server": Entrypoint(
        key="carla_server",
        module="ultimate_pipeline.start_carla_server_with_tile_streaming",
        description="Start CARLA server configured for tile streaming",
    ),
    "roadrunner_probe": Entrypoint(
        key="roadrunner_probe",
        module="ultimate_pipeline.roadrunner.capability_probe",
        description="Probe RoadRunner installation capabilities (opt-in, disabled by default)",
    ),
    "roadrunner_gate": Entrypoint(
        key="roadrunner_gate",
        module="ultimate_pipeline.roadrunner.gate_matrix",
        description="Evaluate RoadRunner release gate matrix (opt-in, disabled by default)",
    ),
}
