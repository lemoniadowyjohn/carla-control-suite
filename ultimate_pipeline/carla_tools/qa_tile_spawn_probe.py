#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tile spawn probe QA.

For each selected tile:
- Load the tile as an OpenDRIVE world
- Iterate over spawn points (limited by settings)
- Try to spawn a vehicle with a forward offset
- If spawn fails → mark as "blocked spawn"
- Capture a top-down camera snapshot for broken spawnpoints
- Save all results into spawn_probe/ as JSON + PNGs
"""

import os
import json
import math
from typing import List, Dict, Any

import carla
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.carla_utils import autostart_carla_if_needed


class TileSpawnProbe:
    def __init__(
        self,
        client: carla.Client,
        tiles_dir: str,
        tile_names: List[str],
        out_dir: str,
        max_spawns_per_tile: int | None = None,
        offset_m: float | None = None,
    ):
        """
        tiles_dir: directory containing tile_*.xodr
        tile_names: list of filenames
        out_dir: pipeline output dir
        max_spawns_per_tile: override SETTINGS if provided
        offset_m: forward spawn shift (vehicle length offset)
        """
        self.client = client
        self.tiles_dir = tiles_dir
        self.tile_names = tile_names

        self.max_spawns_per_tile = (
            max_spawns_per_tile
            if max_spawns_per_tile is not None
            else getattr(SETTINGS, "TILE_SPAWN_PROBE_MAX_SPAWNS_PER_TILE", 20)
        )

        self.offset_m = (
            offset_m
            if offset_m is not None
            else getattr(SETTINGS, "TILE_SPAWN_PROBE_OFFSET_M", 1.3)
        )

        # Output directories
        self.out_dir = os.path.join(out_dir, "spawn_probe")
        os.makedirs(self.out_dir, exist_ok=True)

        self.broken_dir = os.path.join(self.out_dir, "broken_spawns")
        os.makedirs(self.broken_dir, exist_ok=True)

        self.results: Dict[str, List[Dict[str, Any]]] = {}

    # ------------------------------------------------------------
    # Core public API
    # ------------------------------------------------------------

    def run(self) -> None:
        """
        Run spawn probe over all tiles in tile_names.
        Populates self.results and writes summary JSON.
        """
        summary: Dict[str, Dict[str, int]] = {}

        for tile_name in self.tile_names:
            tile_path = os.path.join(self.tiles_dir, tile_name)
            if not os.path.isfile(tile_path):
                print(f"⚠ TileSpawnProbe: missing tile file: {tile_path}")
                continue

            print(f"\n🔎 Spawn probe for tile: {tile_name}")

            try:
                broken_spawns = self._probe_single_tile(tile_name, tile_path)
                self.results[tile_name] = broken_spawns
                summary[tile_name] = {
                    "broken_spawns": len(broken_spawns),
                }
                print(f"   → {len(broken_spawns)} broken/blocked spawns.")

            except RuntimeError as e:
                # IMPORTANT: TileSpawnProbe never restarts CARLA
                print(f"❌ CARLA runtime error during spawn probe: {e}")
                print("   ⚠ Skipping this tile (CARLA authority handles recovery).")
                continue

            except Exception as e:
                print(f"⚠ Spawn probe for tile {tile_name} failed: {e}")

        # Save results
        summary_path = os.path.join(self.out_dir, "spawn_probe_summary.json")
        details_path = os.path.join(self.out_dir, "spawn_probe_details.json")

        try:
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
            with open(details_path, "w", encoding="utf-8") as f:
                json.dump(self.results, f, indent=2)

            print(f"\n📄 Spawn probe summary → {summary_path}")
            print(f"📄 Spawn probe details → {details_path}")

        except Exception as e:
            print(f"⚠ Failed to write spawn probe JSON: {e}")

    # ------------------------------------------------------------
    # Per-tile probe
    # ------------------------------------------------------------

    def _probe_single_tile(self, tile_name: str, tile_path: str) -> List[Dict[str, Any]]:
        """
        Load tile as a world, test spawns, return list of broken spawn dicts.
        """
        broken: List[Dict[str, Any]] = []

        with open(tile_path, "r", encoding="utf-8") as f:
            xodr_data = f.read()

        params = carla.OpendriveGenerationParameters()
        params.map_layers = carla.MapLayer.NONE

        world = load_opendrive_world(
            self.client,
            xodr_data,
            params=params,
            timeout_s=180.0,
            retries=2,
            do_reload=True,
        )
        world.set_pedestrians_cross_factor(0.0)
        world.set_weather(carla.WeatherParameters.ClearNoon)

        amap = world.get_map()
        vehicle_bps = world.get_blueprint_library().filter("vehicle.*")
        if not vehicle_bps:
            print("⚠ No vehicle blueprints available.")
            return broken

        spawn_points = amap.get_spawn_points()
        if not spawn_points:
            print("⚠ No spawn points in this tile.")
            return broken

        vehicle_bp = vehicle_bps[0]
        tested = 0

        for idx, sp in enumerate(spawn_points):
            if tested >= self.max_spawns_per_tile:
                break
            tested += 1

            shifted = self._shift_transform_forward(sp, self.offset_m)
            vehicle = world.try_spawn_actor(vehicle_bp, shifted)

            if vehicle is None:
                broken.append(
                    self._log_broken_spawn(world, amap, shifted, tile_name, idx)
                )
            else:
                vehicle.destroy()

        # Cleanup all actors spawned in this tile world
        try:
            for actor in world.get_actors():
                try:
                    actor.destroy()
                except Exception:
                    pass
        except Exception:
            pass

        return broken

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    @staticmethod
    def _shift_transform_forward(
        transform: carla.Transform, offset_m: float
    ) -> carla.Transform:
        yaw_rad = math.radians(transform.rotation.yaw)
        dx = math.cos(yaw_rad) * offset_m
        dy = math.sin(yaw_rad) * offset_m

        new_loc = carla.Location(
            x=transform.location.x + dx,
            y=transform.location.y + dy,
            z=transform.location.z,
        )
        return carla.Transform(new_loc, transform.rotation)

    def _log_broken_spawn(
        self,
        world: carla.World,
        amap: carla.Map,
        transform: carla.Transform,
        tile_name: str,
        idx: int,
    ) -> Dict[str, Any]:
        loc = transform.location
        wp = amap.get_waypoint(
            loc, project_to_road=False, lane_type=carla.LaneType.Any
        )

        road_id = wp.road_id if wp else None
        s = wp.s if wp else None

        base_name = f"{tile_name.replace('.xodr', '')}_spawn_{idx:03d}"
        img_path = os.path.join(self.broken_dir, base_name + ".png")

        try:
            self._capture_topdown(world, loc, img_path)
        except Exception as e:
            print(f"⚠ Screenshot failed for {base_name}: {e}")
            img_path = None

        print(
            f"   ✖ Broken spawn @ {loc.x:.2f}, {loc.y:.2f}, road_id={road_id}, s={s}"
        )

        return {
            "tile": tile_name,
            "spawn_index": idx,
            "x": loc.x,
            "y": loc.y,
            "z": loc.z,
            "road_id": road_id,
            "s": s,
            "screenshot": img_path,
            "reason": "try_spawn_actor_failed",
        }

    def _capture_topdown(
        self, world: carla.World, loc: carla.Location, out_path: str
    ) -> None:
        bp = world.get_blueprint_library().find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", "800")
        bp.set_attribute("image_size_y", "600")
        bp.set_attribute("fov", "90")

        tf = carla.Transform(
            carla.Location(x=loc.x, y=loc.y, z=loc.z + 25.0),
            carla.Rotation(pitch=-90.0),
        )

        camera = world.spawn_actor(bp, tf)
        saved = {"done": False}

        def _cb(image: carla.Image):
            if not saved["done"]:
                image.save_to_disk(out_path)
                saved["done"] = True

        camera.listen(_cb)

        for _ in range(20):
            world.wait_for_tick()
            if saved["done"]:
                break

        camera.stop()
        camera.destroy()
