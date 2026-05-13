"""CARLA-facing helpers.

Import-safety matters: most modules here should be safe to import even when the `carla`
Python package is not installed (e.g., offline analysis on HPC). When a function truly
needs CARLA, it should import it lazily.

Re-export commonly used helpers so IDEs and `from ultimate_pipeline.carla_tools import ...`
works without "unresolved reference" noise.
"""

from __future__ import annotations

from ultimate_pipeline.carla_tools.spawn_validator import SpawnValidator

# carla_server uses lazy carla import and is safe to import
from ultimate_pipeline.carla_tools.carla_server import (  # noqa: F401
    ensure_carla_server,
    get_carla_client,
    kill_stale_carla,
)

__all__ = [
    "SpawnValidator",
    "ensure_carla_server",
    "get_carla_client",
    "kill_stale_carla",
]
