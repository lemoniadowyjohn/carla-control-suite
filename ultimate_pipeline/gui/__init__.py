"""Phase 1 GUI support layer.

Importing this package MUST NOT import ``carla``. Every adapter in
:mod:`ultimate_pipeline.gui.adapters` keeps its simulator import lazy so that
offline tests and ``--mock`` GUI startup work without a running server.
"""

__all__ = ["cancellation", "run_status", "results", "audit", "freshness", "health"]