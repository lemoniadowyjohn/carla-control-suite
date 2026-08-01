#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Backward-compatibility shim.

Historically, some scripts imported `LocalPerceptionRunner` from
`ultimate_pipeline.carla_tools.perception_runner_local`.

The canonical implementation lives in:
    ultimate_pipeline.carla_tools.local_perception_runner

This module intentionally contains *no* CARLA imports so the repo remains
import-safe in offline environments.
"""

from ultimate_pipeline.carla_tools.local_perception_runner import LocalPerceptionRunner

__all__ = ["LocalPerceptionRunner"]
