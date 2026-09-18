# ultimate_pipeline/carla_tools/map_loader.py
"""
Named entry point for CARLA map-loading and grid-map resolution utilities.

Re-exports the map-probing and XODR-path-resolution helpers from
tools/run_perception_safe so that reviewers have a stable, importable
reference to the map-loading boundary.

Full extraction deferred (T-MODULARIZE-RUN-PERCEPTION-SAFE-001).
"""

from __future__ import annotations

from ultimate_pipeline.tools.run_perception_safe import (  # noqa: F401 — public re-export
    _is_grid_map as is_grid_map,
    _resolve_xodr_path_for_grid as resolve_xodr_path_for_grid,
    _resolve_stream_port as resolve_stream_port,
    _wait_for_port_open as wait_for_port_open,
    _run_map_only_probe_subprocess as run_map_only_probe_subprocess,
)

__all__ = [
    "is_grid_map",
    "resolve_xodr_path_for_grid",
    "resolve_stream_port",
    "wait_for_port_open",
    "run_map_only_probe_subprocess",
]
