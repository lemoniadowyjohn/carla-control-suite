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
from ultimate_pipeline.perception.environment.traffic_manager_session import (
    VALID_WALKER_MODES,
    WALKER_CONTROLLER_BLUEPRINT,
    WALKER_MODE_CONTROLLED,
    build_controlled_walker,
)


def _default_stream_seed() -> int:
    """Resolve the governed stream seed from the NEW-327 seed tree."""
    import os

    try:
        from ultimate_pipeline.perception.environment.seed_tree import (
            seed_tree_from_environment,
        )

        return int(seed_tree_from_environment()["seeds"]["npc_spawn"])
    except Exception:
        return int(os.environ.get("UP_STREAM_SEED", "0") or 0)


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
        traffic_manager_port: int = 8000,
        walker_mode: str = WALKER_MODE_CONTROLLED,
        seed: int | None = None,
    ):
        if not _CARLA_AVAILABLE:
            raise RuntimeError(
                "CARLA PythonAPI not found on PYTHONPATH. "
                "Install/activate CARLA PythonAPI before using ActorStreamManager."
            )
        self.client = client
        self.world = client.get_world()
        self.map = self.world.get_map()

        # NEW-326/328: one explicit TM port for every governed autopilot actor.
        self.traffic_manager_port = int(traffic_manager_port)

        # NEW-327: owned RNG.  `import random` at module scope left the module
        # using (and mutating) the process-global generator.
        self.seed = (
            int(seed)
            if seed is not None
            else _default_stream_seed()
        )
        self._rng = random.Random(self.seed)

        # NEW-329: explicit walker mode.  Uncontrolled walkers are never counted
        # as pedestrian traffic.
        if walker_mode not in VALID_WALKER_MODES:
            raise ValueError(f"invalid_walker_mode:{walker_mode}")
        self.walker_mode = str(walker_mode)
        self.walker_controllers: Dict[int, int] = {}
        self.walker_controller_bp = None
        if self.walker_mode == WALKER_MODE_CONTROLLED:
            try:
                self.walker_controller_bp = self.world.get_blueprint_library().find(
                    WALKER_CONTROLLER_BLUEPRINT
                )
            except Exception:
                self.walker_controller_bp = None

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
                # NEW-327: owned RNG instance.  `random.shuffle(sps)` mutated the
                # process-global generator AND the module-level index list, so
                # spawn order depended on unrelated call history.
                order = list(sps)
                self._rng.shuffle(order)
                for sp in order:
                    # don't spawn directly on top of ego
                    if self._dist(sp.location, ego_loc) < self.spawn_distance:
                        continue

                    actor = self.world.try_spawn_actor(self._rng.choice(bp_vehicles), sp)
                    if actor:
                        # NEW-326/328: autopilot must name an explicit TM port.
                        # A bare `set_autopilot(True)` binds the DEFAULT traffic
                        # manager, which is never seeded nor configured.
                        try:
                            actor.set_autopilot(True, self.traffic_manager_port)
                        except Exception as exc:
                            print(
                                f"[ActorStreamManager] autopilot failed for actor "
                                f"{getattr(actor, 'id', '?')} on TM port "
                                f"{self.traffic_manager_port}: {exc}"
                            )
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
                order = list(sps)
                self._rng.shuffle(order)
                for sp in order:
                    if self._dist(sp.location, ego_loc) < self.spawn_distance:
                        continue

                    walker_bp = self._rng.choice(bp_walkers)
                    # NEW-329: a walker spawned WITHOUT a started
                    # `controller.ai.walker` is a static prop, not pedestrian
                    # traffic.  The mode is now explicit, controlled walkers get
                    # a controller with a deterministic destination, and the
                    # controller/actor pair is tracked for joint cleanup.
                    if self.walker_mode == WALKER_MODE_CONTROLLED and self.walker_controller_bp is not None:
                        built = build_controlled_walker(
                            self.world,
                            None,
                            walker_bp,
                            controller_bp=self.walker_controller_bp,
                            rng=self._rng,
                        )
                        actor_id = built.get("walker_actor_id")
                        controller_id = built.get("controller_actor_id")
                        if actor_id is not None:
                            self.managed_actors.add(int(actor_id))
                            if controller_id is not None:
                                self.walker_controllers[int(actor_id)] = int(controller_id)
                            current_walker_count += 1
                            print(
                                f"[ActorStreamManager] spawned CONTROLLED walker "
                                f"{actor_id} (controller {controller_id}) in {t}"
                            )
                            if current_walker_count >= self.max_walkers:
                                break
                        continue

                    actor = self.world.try_spawn_actor(walker_bp, sp)
                    if actor:
                        self.managed_actors.add(actor.id)
                        current_walker_count += 1
                        print(
                            f"[ActorStreamManager] spawned STATIC walker prop "
                            f"{actor.id} in {t} (not counted as pedestrian traffic)"
                        )
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
                # NEW-329: destroy the walker controller together with its
                # walker, otherwise an orphaned controller keeps steering a
                # destroyed actor.
                controller_id = self.walker_controllers.pop(aid, None)
                if controller_id is not None:
                    controller = self.world.get_actor(controller_id)
                    if controller is not None:
                        try:
                            controller.stop()
                        except Exception:
                            pass
                        try:
                            controller.destroy()
                        except Exception:
                            pass
                actor.destroy()
                self.managed_actors.discard(aid)

    # ---------------------------------------------------------
    # NEW-329: destroy everything this manager owns
    # ---------------------------------------------------------
    def destroy_all(self) -> Dict[str, List[int]]:
        """Destroy every managed actor and its walker controller."""
        destroyed: List[int] = []
        controllers: List[int] = []
        for aid in list(self.managed_actors):
            actor = self.world.get_actor(aid)
            if actor is not None:
                try:
                    actor.destroy()
                except Exception:
                    pass
            destroyed.append(aid)
        for aid, controller_id in list(self.walker_controllers.items()):
            controller = self.world.get_actor(controller_id)
            if controller is not None:
                try:
                    controller.stop()
                except Exception:
                    pass
                try:
                    controller.destroy()
                except Exception:
                    pass
            controllers.append(controller_id)
        self.managed_actors.clear()
        self.walker_controllers.clear()
        return {"actors": destroyed, "walker_controllers": controllers}
