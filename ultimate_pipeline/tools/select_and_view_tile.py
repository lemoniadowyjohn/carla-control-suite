#!/usr/bin/env python3
import os
import time
import carla

from ultimate_pipeline.core.carla_utils import autostart_carla_if_needed
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

TILES_DIR = None  # auto-detected below


def pick_tile(tiles):
    print("\nAvailable tiles:")
    for i, t in enumerate(tiles):
        print(f"[{i}] {os.path.basename(t)}")
    idx = int(input("\nSelect tile index: "))
    return tiles[idx]


def main():
    global TILES_DIR

    # Auto-detect latest tiles directory
    from ultimate_pipeline.config.settings import SETTINGS


    out = SETTINGS.latest_output_dir()
    TILES_DIR = os.path.join(out, "tiles")

    tiles = sorted(
        os.path.join(TILES_DIR, f)
        for f in os.listdir(TILES_DIR)
        if f.endswith(".xodr")
    )

    if not tiles:
        raise RuntimeError("No tiles found")

    tile_path = pick_tile(tiles)
    print(f"\n▶ Loading tile: {tile_path}")

    client = autostart_carla_if_needed()
    client.set_timeout(180.0)

    with open(tile_path, "r", encoding="utf-8") as f:
        xodr = f.read()

    params = carla.OpendriveGenerationParameters()
    params.map_layers = carla.MapLayer.NONE

    world = load_opendrive_world(
        client,
        xodr,
        params=params,
        timeout_s=180.0,
        retries=2,
        do_reload=True,
    )

    amap = world.get_map()

    # spectator view
    spectator = world.get_spectator()
    spawn_points = amap.get_spawn_points()

    if spawn_points:
        tf = spawn_points[0]
        tf.location.z += 60
        tf.rotation.pitch = -90
        spectator.set_transform(tf)

    # spawn one vehicle
    bp = world.get_blueprint_library().filter("vehicle.tesla.model3")[0]
    vehicle = world.spawn_actor(bp, spawn_points[0])

    print("🚗 Vehicle spawned. Use WASD / mouse to inspect.")
    print("⏳ Press Ctrl+C to exit.")

    try:
        while True:
            world.tick()
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n🧹 Cleaning up...")
    finally:
        try:
            vehicle.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
