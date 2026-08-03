# ultimate_pipeline/domain_gap/structural_gap.py

from __future__ import annotations

import time
from typing import Dict, Any

import carla

from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world


class StructuralGapAnalyzer:
    """
    Structural CARLA-level domain gap analyzer.

    Measures:
      - spawn point count
      - waypoint density
      - topology complexity

    This reflects *simulator usability*, not pure geometry correctness.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: float | None = None,
    ):
        self.host = host or SETTINGS.CARLA_HOST
        self.port = port or SETTINGS.CARLA_PORT
        self.timeout = timeout or getattr(SETTINGS, "CARLA_TIMEOUT", 20.0)

        self.client = carla.Client(self.host, self.port)
        self.client.set_timeout(self.timeout)

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------

    def analyze_builtin(self, map_name: str) -> Dict[str, Any]:
        """
        Analyze a built-in CARLA map (e.g., Town10HD).
        """
        world = _reload_ready_for_sensors(
            self.client, map_name=map_name, tm_port=8000
        )
        return self._analyze(world, source=map_name)

    def analyze_xodr(self, xodr_path: str) -> Dict[str, Any]:
        """
        Analyze an OpenDRIVE map provided as XODR.
        """
        with open(xodr_path, "r", encoding="utf-8") as f:
            xodr = f.read()

        world = load_opendrive_world(self.client, xodr, timeout_s=180.0, retries=2, do_reload=True)
        return self._analyze(world, source=xodr_path)

    # ------------------------------------------------------------
    # Core measurement
    # ------------------------------------------------------------

    def _analyze(self, world: carla.World, source: str) -> Dict[str, Any]:
        """
        Extract structural metrics from a CARLA world.
        """
        t0 = time.perf_counter()

        m = world.get_map()

        spawn_points = m.get_spawn_points()
        waypoints = m.generate_waypoints(
            getattr(SETTINGS, "WAYPOINT_SAMPLE_DIST", 2.0)
        )
        topology = m.get_topology()

        runtime = time.perf_counter() - t0

        # Normalizations
        road_length_km = max(
            getattr(SETTINGS, "REFERENCE_ROAD_LENGTH_KM", 1.0), 1e-6
        )

        return {
            "source": source,
            "spawn_points": len(spawn_points),
            "waypoints": len(waypoints),
            "topology_edges": len(topology),

            # Normalized metrics (scale invariant)
            "spawn_density": len(spawn_points) / road_length_km,
            "waypoint_density": len(waypoints) / road_length_km,
            "topology_density": len(topology) / road_length_km,

            "meta": {
                "waypoint_sampling_m": getattr(
                    SETTINGS, "WAYPOINT_SAMPLE_DIST", 2.0
                ),
                "runtime_sec": round(runtime, 3),
                "carla_host": self.host,
                "carla_port": self.port,
            },
        }

    def analyze_world(self, world: carla.World, source: str) -> Dict[str, Any]:
        """Public wrapper for already-loaded worlds."""
        return self._analyze(world, source=source)
