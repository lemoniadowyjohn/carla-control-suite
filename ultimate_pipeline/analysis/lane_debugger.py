"""Compatibility shim.

Some tooling historically imported LaneDebugger from `ultimate_pipeline.analysis`.
The implementation lives in `ultimate_pipeline.diagnostics.lane_debugger`.
"""

from __future__ import annotations

from ultimate_pipeline.diagnostics.lane_debugger import LaneDebugger

__all__ = ["LaneDebugger"]
