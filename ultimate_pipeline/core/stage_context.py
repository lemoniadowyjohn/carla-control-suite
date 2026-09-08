"""Explicit state shared by pipeline stages.

This is introduced beside the legacy ``MainPipeline.semantic_state`` mapping.
Stages are migrated incrementally so each change can be compared independently.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StageContext:
    has_geometry: bool = False
    has_elevation: bool = False
    has_planview: bool = False
    has_lanes: bool = False
