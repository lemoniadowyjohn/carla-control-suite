from __future__ import annotations

import time
from typing import Sequence

import carla

from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world
from ultimate_pipeline.core.carla_utils import autostart_carla_if_needed


from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
def stream_tiles(
    tiles: Sequence[str],
    host: str = "127.0.0.1",
    port: int = 2000,
    seconds_per_tile: float = 10.0,
) -> None:
    """
    Best-effort tile streaming in CARLA using OpenDRIVE standalone generation.

    - Loads each tile (XODR) via load_opendrive_world (the single authority).
    - Runs a short simulation loop for stability testing.
    - If CARLA dies mid-stream, reconnect/restart via autostart_carla_if_needed().

    This is a *diagnostic* tool; do not use it as a semantic gate.
    """

    # NOTE: autostart_carla_if_needed() uses SETTINGS for host/port. The host/port
    # args are kept for API compatibility but are not authoritative here.
    client = autostart_carla_if_needed()

    for tile_path in tiles:
        # Lightweight liveness check; if CARLA died, recover.
        try:
            _ = client.get_world()
        except Exception:
            print("   💀 CARLA unresponsive — restarting…")
            client = autostart_carla_if_needed()

        print(f"Loading tile: {tile_path}")

        try:
            with open(tile_path, encoding="utf-8") as f:
                data = f.read()
        except Exception as e:
            print(f"   ❌ Could not read tile: {e}")
            continue

        params = carla.OpendriveGenerationParameters()
        params.map_layers = carla.MapLayer.NONE

        try:
            world = load_opendrive_world(
                client,
                data,
                params=params,
                timeout_s=180.0,
                retries=2,
                do_reload=True,
            )
        except Exception as e:
            print(f"   ❌ Tile load failed: {e}")
            client = autostart_carla_if_needed()
            continue

        print("Tile loaded; running simulation...")

        try:
            # CARLA 0.9.16: must use positional float, not keyword arg
            world.wait_for_tick(2.0)
            start = time.time()
            while time.time() - start < float(seconds_per_tile):
                world.tick()
        except Exception as e:
            print(f"   Simulation tick error: {e}")

        # Unload tile (switch to a built-in map as a cheap reset)
        try:
            print("Unloading tile (loading empty map)...")
            _reload_ready_for_sensors(client, map_name="Town01", tm_port=8000)
        except Exception:
            pass
