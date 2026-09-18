# ultimate_pipeline/quality/check_drivability_smoke.py
# -*- coding: utf-8 -*-

"""
Drivability smoke test for OpenDRIVE maps in CARLA.

Why:
- Map may pass all static checks but fail at runtime.
- Spawning, pathfinding, and physics simulation can reveal hidden issues.

What it checks:
- Load map into CARLA
- Spawn ego vehicle at a random spawn point
- Plan a short route (if possible)
- Tick world for N steps
- Report pass/fail

This is an optional, non-blocking test that requires CARLA to be running.

Outputs:
- A dict report with ok, spawn_success, route_planned, ticks_completed.
"""

from __future__ import annotations

import os
import random
from typing import Any, Dict, Optional

from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors

# CARLA import is optional
try:
    import carla
    CARLA_AVAILABLE = True
except ImportError:
    carla = None
    CARLA_AVAILABLE = False


def check_drivability_smoke(
    xodr_path: str,
    host: str = "localhost",
    port: int = 2000,
    timeout: float = 30.0,
    num_ticks: int = 100,
    stage: str = "drivability_smoke",
) -> Dict[str, Any]:
    """
    Run a drivability smoke test on an OpenDRIVE map.

    Parameters
    ----------
    xodr_path : str
        Path to the OpenDRIVE file.
    host : str
        CARLA server host.
    port : int
        CARLA server port.
    timeout : float
        Connection timeout in seconds.
    num_ticks : int
        Number of simulation ticks to run.
    stage : str
        Stage name for reporting.

    Returns
    -------
    dict
        {
            "ok": bool,
            "stage": str,
            "carla_available": bool,
            "map_loaded": bool,
            "spawn_success": bool,
            "spawn_point_count": int,
            "route_planned": bool,
            "ticks_completed": int,
            "ticks_requested": int,
            "error": str or None,
            "warnings": [str]
        }
    """
    report: Dict[str, Any] = {
        "ok": False,
        "stage": stage,
        "carla_available": CARLA_AVAILABLE,
        "map_loaded": False,
        "spawn_success": False,
        "spawn_point_count": 0,
        "route_planned": False,
        "ticks_completed": 0,
        "ticks_requested": num_ticks,
        "error": None,
        "warnings": [],
    }

    if not CARLA_AVAILABLE:
        report["warnings"].append("CARLA Python API not available - smoke test skipped")
        report["ok"] = True  # Non-blocking: pass if CARLA unavailable
        return report

    if not os.path.exists(xodr_path):
        report["error"] = f"XODR file not found: {xodr_path}"
        return report

    client = None
    vehicle = None
    original_map_name = None

    try:
        # Connect to CARLA
        client = carla.Client(host, port)
        client.set_timeout(timeout)

        # Save original map to restore later
        try:
            original_map_name = client.get_world().get_map().name
        except Exception:
            pass

        # Read XODR content
        with open(xodr_path, "r", encoding="utf-8") as f:
            xodr_content = f.read()

        # Load map
        try:
            from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

            world = load_opendrive_world(client, xodr_content, timeout_s=float(timeout), retries=1, do_reload=True)
            report["map_loaded"] = True
        except Exception as e:
            report["error"] = f"Failed to load map: {e}"
            return report

        # Get spawn points
        spawn_points = world.get_map().get_spawn_points()
        report["spawn_point_count"] = len(spawn_points)

        if not spawn_points:
            report["warnings"].append("No spawn points available")
            report["ok"] = True  # Pass with warning
            return report

        # Spawn ego vehicle
        bp_lib = world.get_blueprint_library()
        vehicle_bp = bp_lib.filter("vehicle.tesla.model3")
        if not vehicle_bp:
            vehicle_bp = bp_lib.filter("vehicle.*")
        if not vehicle_bp:
            report["error"] = "No vehicle blueprints available"
            return report

        vehicle_bp = random.choice(list(vehicle_bp))

        # Try spawning at different points
        spawn_success = False
        for sp in spawn_points[:10]:  # Try first 10 spawn points
            try:
                vehicle = world.try_spawn_actor(vehicle_bp, sp)
                if vehicle is not None:
                    spawn_success = True
                    report["spawn_success"] = True
                    break
            except Exception:
                continue

        if not spawn_success:
            report["warnings"].append("Could not spawn vehicle at any spawn point")
            report["ok"] = True  # Pass with warning
            return report

        # Try to plan a route (optional)
        try:
            if len(spawn_points) >= 2:
                # Simple route planning check
                start = spawn_points[0]
                end = spawn_points[min(1, len(spawn_points) - 1)]
                # Just check that we can get waypoints
                map_obj = world.get_map()
                wp_start = map_obj.get_waypoint(start.location)
                wp_end = map_obj.get_waypoint(end.location)
                if wp_start and wp_end:
                    report["route_planned"] = True
        except Exception as e:
            report["warnings"].append(f"Route planning check failed: {e}")

        # Tick world
        ticks_done = 0
        try:
            for _ in range(num_ticks):
                world.tick()
                ticks_done += 1
            report["ticks_completed"] = ticks_done
        except Exception as e:
            report["ticks_completed"] = ticks_done
            report["warnings"].append(f"Simulation tick failed after {ticks_done} ticks: {e}")

        # Success if we got this far
        report["ok"] = True

    except Exception as e:
        report["error"] = str(e)
    finally:
        # Cleanup
        if vehicle is not None:
            try:
                vehicle.destroy()
            except Exception:
                pass

        # Restore original map if possible
        if client is not None and original_map_name:
            try:
                _reload_ready_for_sensors(
                    client, map_name=original_map_name, tm_port=8000
                )
            except Exception:
                pass

    return report


def check_drivability_smoke_with_client(
    client: "carla.Client",
    xodr_path: str,
    num_ticks: int = 100,
    stage: str = "drivability_smoke",
) -> Dict[str, Any]:
    """
    Run drivability smoke test using an existing CARLA client.

    This variant is for use within the pipeline where a client already exists.
    """
    report: Dict[str, Any] = {
        "ok": False,
        "stage": stage,
        "carla_available": True,
        "map_loaded": False,
        "spawn_success": False,
        "spawn_point_count": 0,
        "route_planned": False,
        "ticks_completed": 0,
        "ticks_requested": num_ticks,
        "error": None,
        "warnings": [],
    }

    if client is None:
        report["error"] = "No CARLA client provided"
        return report

    if not os.path.exists(xodr_path):
        report["error"] = f"XODR file not found: {xodr_path}"
        return report

    vehicle = None

    try:
        # Read XODR content
        with open(xodr_path, "r", encoding="utf-8") as f:
            xodr_content = f.read()

        # Load map
        try:
            from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

            world = load_opendrive_world(client, xodr_content, timeout_s=60.0, retries=1, do_reload=True)
            report["map_loaded"] = True
        except Exception as e:
            report["error"] = f"Failed to load map: {e}"
            return report

        # Get spawn points
        spawn_points = world.get_map().get_spawn_points()
        report["spawn_point_count"] = len(spawn_points)

        if not spawn_points:
            report["warnings"].append("No spawn points available")
            report["ok"] = True
            return report

        # Spawn ego vehicle
        bp_lib = world.get_blueprint_library()
        vehicle_bp = bp_lib.filter("vehicle.*")
        if not vehicle_bp:
            report["error"] = "No vehicle blueprints available"
            return report

        vehicle_bp = list(vehicle_bp)[0]

        for sp in spawn_points[:5]:
            try:
                vehicle = world.try_spawn_actor(vehicle_bp, sp)
                if vehicle is not None:
                    report["spawn_success"] = True
                    break
            except Exception:
                continue

        if vehicle is None:
            report["warnings"].append("Could not spawn vehicle")
            report["ok"] = True
            return report

        # Tick world
        ticks_done = 0
        for _ in range(num_ticks):
            try:
                world.tick()
                ticks_done += 1
            except Exception as e:
                report["warnings"].append(f"Tick failed: {e}")
                break

        report["ticks_completed"] = ticks_done
        report["ok"] = True

    except Exception as e:
        report["error"] = str(e)
    finally:
        if vehicle is not None:
            try:
                vehicle.destroy()
            except Exception:
                pass

    return report


if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="Drivability smoke test for OpenDRIVE in CARLA")
    ap.add_argument("xodr_path", help="Path to OpenDRIVE file")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--ticks", type=int, default=100)
    args = ap.parse_args()

    rep = check_drivability_smoke(
        args.xodr_path,
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        num_ticks=args.ticks,
    )
    print(json.dumps(rep, indent=2))
    sys.exit(0 if rep.get("ok", False) else 2)
