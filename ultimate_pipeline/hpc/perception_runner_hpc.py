"""Compatibility shim.

Historically this project had two copies of HPCPerceptionRunner:
- ultimate_pipeline.carla_tools.perception_runner_hpc
- ultimate_pipeline.hpc.perception_runner_hpc

The duplicate caused drift and confusion. Keep this file as a thin re-export so
imports keep working while the canonical implementation lives in carla_tools.
"""

from ultimate_pipeline.carla_tools.perception_runner_hpc import *  # noqa: F401,F403
