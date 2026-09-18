#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Dict, List, Set
import random
import math

# Import-safety: this module may be imported without CARLA PythonAPI.
try:  # pragma: no cover
    import carla  # type: ignore
    _CARLA_AVAILABLE = True
except Exception:  # pragma: no cover
    carla = None  # type: ignore
    _CARLA_AVAILABLE = False

from ultimate_pipeline.config.settings import SETTINGS


class ActorStreamManager:
    """
    Spawns and manages NPC traffic only inside currently loaded tiles.

    - Uses TileStreamer.get_tile_for_location(...)
    - Only spawns in tiles that are currently loaded
    - Despawns actors that leave the loaded tiles
    - Compatible with CarlaSimulation: update(self, ego_vehicle)
    """

    def __init__(
        self,
        client: carla.Client,
        tile_streamer,
        max_vehicles: int | None = None,
        max_walkers: int | None = None,
        spawn_distance: float | None = None,
        despawn_distance: float | None = None,
    ):
        if not _CARLA_AVAILABLE:
            raise RuntimeError(
                "CARLA PythonAPI not found on PYTHONPATH. "
                "Install/activate CARLA PythonAPI before using ActorStreamManager."
            )
        self.client = client
        self.world = client.get_world()
        self.map = self.world.get_map()

        self.tile_streamer = tile_streamer

        # Limits: use explicit values or fall back to SETTINGS
        self.max_vehicles = (
            max_vehicles
            if max_vehicles is not None
            else getattr(SETTINGS, "STREAM_MAX_VEHICLES", 25)
        )
        self.max_walkers = (
            max_walkers
            if max_walkers is not None
            else getattr(SETTINGS, "STREAM_MAX_WALKERS", 10)
        )

        # Spawn / despawn distances around ego
        self.spawn_distance = (
            spawn_distance
            if spawn_distance is not None
            else getattr(SETTINGS, "STREAM_SPAWN_DISTANCE", 80.0)
        )
        self.despawn_distance = (
            despawn_distance
            if despawn_distance is not None
            else getattr(SETTINGS, "STREAM_DESPAWN_DISTANCE", 150.0)
        )

        # tile → list of spawn transforms
        self.tile_spawn_points: Dict[str, List[carla.Transform]] = {}
        # actor ids we manage
        self.managed_actors: Set[int] = set()

        self.blueprints = self.world.get_blueprint_library()

        # Build spawn index AFTER tile_streamer is ready
        self.build_spawn_point_index()

    # ---------------------------------------------------------
    # Spawn points registration
    # ---------------------------------------------------------
    def build_spawn_point_index(self) -> None:
        """
        Take all map spawn points and group them by tile using TileStreamer.
        Call once after tile_streamer is initialized and world is loaded.
        """
        all_points = self.map.get_spawn_points()
        print(f"[ActorStreamManager] Indexing {len(all_points)} spawn points into tiles...")

        for sp in all_points:
            # Only keep spawn points that are actually on a drivable lane
            wp = self.map.get_waypoint(sp.location, project_to_road=False, lane_type=carla.LaneType.Driving)
            if wp is None:
                # Off-road, sidewalk, or invalid → skip
                continue

            tile_name = self.tile_streamer.get_tile_for_location(sp.location)
            if tile_name is None:
                continue

            self.tile_spawn_points.setdefault(tile_name, []).append(sp)

        for t, sps in self.tile_spawn_points.items():
            print(f"[ActorStreamManager] tile={t} has {len(sps)} spawn points")

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------
    @staticmethod
    def _dist(a: carla.Location, b: carla.Location) -> float:
        return math.hypot(a.x - b.x, a.y - b.y)

    # ---------------------------------------------------------
    # MAIN UPDATE — Called once per tick
    # ---------------------------------------------------------
    def update(self, ego_vehicle: carla.Vehicle) -> None:
        """
        Called once per frame by CarlaSimulation.
        Uses current ego position + loaded tiles.
        """
        loaded_tiles = getattr(self.tile_streamer, "loaded_tiles", set())
        if not loaded_tiles:
            return

        self._spawn_new_actors(loaded_tiles, ego_vehicle)
        self._cleanup_out_of_range(loaded_tiles, ego_vehicle)

    # ---------------------------------------------------------
    # Spawn actors only inside loaded tiles
    # ---------------------------------------------------------
    def _spawn_new_actors(self, loaded_tiles: Set[str], ego_vehicle: carla.Vehicle) -> None:
        bp_vehicles = self.blueprints.filter("vehicle.*")
        bp_walkers = self.blueprints.filter("walker.pedestrian.*")

        if not bp_vehicles:
            return

        ego_loc = ego_vehicle.get_location()

        current_vehicle_count = 0
        current_walker_count = 0

        # Count existing managed actors and prune dead ones
        for aid in list(self.managed_actors):
            actor = self.world.get_actor(aid)
            if actor is None:
                self.managed_actors.discard(aid)
                continue
            if actor.type_id.startswith("vehicle."):
                current_vehicle_count += 1
            elif actor.type_id.startswith("walker."):
                current_walker_count += 1

        # vehicles
        if current_vehicle_count < self.max_vehicles:
            for t in loaded_tiles:
                sps = self.tile_spawn_points.get(t, [])
                random.shuffle(sps)
                for sp in sps:
                    # don't spawn directly on top of ego
                    if self._dist(sp.location, ego_loc) < self.spawn_distance:
                        continue

                    actor = self.world.try_spawn_actor(random.choice(bp_vehicles), sp)
                    if actor:
                        actor.set_autopilot(True)
                        self.managed_actors.add(actor.id)
                        current_vehicle_count += 1
                        print(f"[ActorStreamManager] spawned vehicle {actor.id} in {t}")
                        if current_vehicle_count >= self.max_vehicles:
                            break
                if current_vehicle_count >= self.max_vehicles:
                    break

        # walkers
        if bp_walkers and current_walker_count < self.max_walkers:
            for t in loaded_tiles:
                sps = self.tile_spawn_points.get(t, [])
                random.shuffle(sps)
                for sp in sps:
                    if self._dist(sp.location, ego_loc) < self.spawn_distance:
                        continue

                    actor = self.world.try_spawn_actor(random.choice(bp_walkers), sp)
                    if actor:
                        self.managed_actors.add(actor.id)
                        current_walker_count += 1
                        print(f"[ActorStreamManager] spawned walker {actor.id} in {t}")
                        if current_walker_count >= self.max_walkers:
                            break
                if current_walker_count >= self.max_walkers:
                    break

    # ---------------------------------------------------------
    # Remove actors that wandered outside loaded tiles / too far
    # ---------------------------------------------------------
    def _cleanup_out_of_range(self, loaded_tiles: Set[str], ego_vehicle: carla.Vehicle) -> None:
        ego_loc = ego_vehicle.get_location()

        for aid in list(self.managed_actors):
            actor = self.world.get_actor(aid)
            if actor is None:
                self.managed_actors.discard(aid)
                continue

            loc = actor.get_location()
            tile = self.tile_streamer.get_tile_for_location(loc)

            too_far = self._dist(loc, ego_loc) > self.despawn_distance

            if tile not in loaded_tiles or too_far:
                print(f"[ActorStreamManager] destroying actor {aid} (tile={tile}, too_far={too_far})")
                actor.destroy()
                self.managed_actors.discard(aid)
