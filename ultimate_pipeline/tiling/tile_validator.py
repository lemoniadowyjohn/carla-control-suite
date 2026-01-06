# ultimate_pipeline/tiling/tile_validator.py

from __future__ import annotations

import os
from time import sleep
from typing import Dict, Any

import carla
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world


class TileValidator:
    """
    CARLA tile diagnostics (NOT a semantic gate).

    IMPORTANT:
    - This validator does NOT decide tile usability.
    - Waypoints and spawning are treated as diagnostics only.
    - Structural validity is decided via tile_metadata.json.

    This validator is intentionally "best effort": it should not crash the pipeline.
    """

    @staticmethod
    def validate(
        carla_host: str,
        carla_port: int,
        tile_path: str,
        *,
        allow_zero_waypoints: bool = True,
        waypoint_distance: float = 2.0,
        timeout_s: float = 30.0,
    ) -> Dict[str, Any]:

        report: Dict[str, Any] = {
            "map_loaded": False,
            "waypoints": 0,
            "vehicle_spawned": False,
            "diagnostics_only": True,
        }

        try:
            client = carla.Client(carla_host, carla_port)
            client.set_timeout(float(timeout_s))
        except Exception as e:
            report["error"] = f"Client error: {e}"
            return report

        # ------------------------------------------------------------
        # Load tile (OpenDRIVE standalone)
        # ------------------------------------------------------------
        try:
            world = None

            # Prefer XODR file content (correct for OpenDRIVE workflow)
            if os.path.isfile(tile_path):
                with open(tile_path, "r", encoding="utf-8") as f:
                    xodr = f.read()

                params = carla.OpendriveGenerationParameters()
                params.map_layers = carla.MapLayer.NONE
                world = load_opendrive_world(
                    client,
                    xodr,
                    params=params,
                    timeout_s=max(180.0, float(timeout_s)),
                    retries=2,
                    do_reload=True,
                )
            else:
                # Fallback: treat tile_path as a CARLA map name.
                world = client.load_world(tile_path)

            sleep(0.5)
        except Exception as e:
            report["error"] = f"Load error: {e}"
            return report

        report["map_loaded"] = True

        # ------------------------------------------------------------
        # Waypoint diagnostics (non-fatal)
        # ------------------------------------------------------------
        try:
            waypoints = world.get_map().generate_waypoints(float(waypoint_distance))
            report["waypoints"] = len(waypoints)
        except Exception as e:
            report["waypoints_error"] = str(e)
            report["waypoints"] = 0

        # IMPORTANT:
        # ❌ DO NOT early-return if waypoints == 0 unless explicitly requested
        if report["waypoints"] == 0 and not allow_zero_waypoints:
            report["note"] = "Zero waypoints (CARLA-routability failure)"
            return report

        # ------------------------------------------------------------
        # Spawn diagnostics (best effort)
        # ------------------------------------------------------------
        try:
            spawn_points = world.get_map().get_spawn_points()
            if spawn_points:
                bp_lib = world.get_blueprint_library()
                # Use a common default; if missing, fall back to any vehicle.
                veh_bp = None
                try:
                    veh_bp = bp_lib.find("vehicle.tesla.model3")
                except Exception:
                    veh_bp = None

                if veh_bp is None:
                    vehicles = bp_lib.filter("vehicle.*")
                    if vehicles:
                        veh_bp = vehicles[0]

                if veh_bp is not None:
                    vehicle = world.try_spawn_actor(veh_bp, spawn_points[0])
                    if vehicle:
                        report["vehicle_spawned"] = True
                        vehicle.destroy()
        except Exception as e:
            report["spawn_error"] = str(e)

        return report
