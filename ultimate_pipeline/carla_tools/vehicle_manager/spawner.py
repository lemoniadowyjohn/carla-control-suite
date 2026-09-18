import os
import carla
import random
import logging
from typing import Optional, List

from carla import Actor

from .validator import VehicleValidator

log = logging.getLogger(__name__)

_DETERMINISTIC_FLAG = os.getenv("UP_DETERMINISTIC_SPAWNS", "")
DETERMINISTIC_SPAWNS = _DETERMINISTIC_FLAG == "1"

_SEED_RAW = os.getenv("UP_SPAWNER_SEED")
SPAWNER_SEED: Optional[int] = None
if DETERMINISTIC_SPAWNS:
    if _SEED_RAW:
        try:
            SPAWNER_SEED = int(_SEED_RAW)
        except ValueError:
            log.warning("UP_SPAWNER_SEED is not an int (%s); using default seed 0", _SEED_RAW)
            SPAWNER_SEED = 0
    else:
        SPAWNER_SEED = 0
        log.info("UP_DETERMINISTIC_SPAWNS=1 but UP_SPAWNER_SEED unset; using default seed 0")

    random.seed(SPAWNER_SEED)


class VehicleSpawner:
    """Handles vehicle spawning and blueprint management"""

    def __init__(self, world: carla.World, traffic_manager, logger=None, run_metadata: Optional[dict] = None):
        self.world = world
        self.map = world.get_map()
        self.traffic_manager = traffic_manager
        self.logger = logger or log
        self.validator = VehicleValidator(logger=self.logger)
        self.run_metadata = run_metadata if isinstance(run_metadata, dict) else None

        mode = "deterministic" if DETERMINISTIC_SPAWNS else "stochastic"
        self.logger.info("VehicleSpawner initialized (mode=%s, seed=%s)", mode, SPAWNER_SEED)
        if self.run_metadata is not None:
            self.run_metadata["deterministic_spawns"] = DETERMINISTIC_SPAWNS
            if SPAWNER_SEED is not None:
                self.run_metadata["spawner_seed"] = SPAWNER_SEED

    def spawn_vehicle(self, vehicle_type: str = 'model3',
                      spawn_point: int = 0) -> Actor | None:
        """Spawn a vehicle and configure traffic manager"""
        try:
            blueprint = self._get_vehicle_blueprint(vehicle_type)
            if not blueprint:
                self.logger.error(f"Vehicle type '{vehicle_type}' not found")
                return None

            transform = self._get_spawn_transform(spawn_point)
            if not transform:
                self.logger.error(f"Invalid spawn point {spawn_point}")
                return None

            vehicle = self.world.spawn_actor(blueprint, transform)

            # Configure traffic manager
            ignore_pct = 0 if DETERMINISTIC_SPAWNS else random.randint(0, 50)
            self.traffic_manager.ignore_lights_percentage(vehicle, ignore_pct)
            self.traffic_manager.auto_lane_change(vehicle, True)
            self.traffic_manager.distance_to_leading_vehicle(vehicle, 2.0)

            self.logger.info(
                f"Spawned vehicle {vehicle.id} of type {vehicle_type}")
            return vehicle

        except Exception as e:
            self.logger.error(f"Error spawning vehicle: {e}")
            return None

    def _get_vehicle_blueprint(
            self, vehicle_type: str) -> Optional[carla.ActorBlueprint]:
        """Get vehicle blueprint from library"""
        blueprint_library = self.world.get_blueprint_library()
        blueprints = blueprint_library.filter(vehicle_type)

        if not blueprints:
            self.logger.warning(f"No blueprints found for {vehicle_type}")
            # Fallback to any vehicle
            blueprints = blueprint_library.filter('vehicle.*')

        if not blueprints:
            return None

        if DETERMINISTIC_SPAWNS:
            try:
                blueprints = sorted(blueprints, key=lambda bp: getattr(bp, "id", ""))
            except Exception:
                pass
            return blueprints[0]

        return random.choice(blueprints)

    def _get_spawn_transform(self,
                             spawn_point: int) -> Optional[carla.Transform]:
        """Get spawn point transform"""
        spawn_points = self.map.get_spawn_points()
        if not spawn_points:
            self.logger.error("No spawn points available on map")
            return None

        return spawn_points[spawn_point % len(spawn_points)]

    def get_available_spawn_points(self) -> List[carla.Transform]:
        """Get all available spawn points"""
        return self.map.get_spawn_points()

    def get_available_vehicle_types(self) -> List[str]:
        """Get list of available vehicle types"""
        blueprint_library = self.world.get_blueprint_library()
        vehicle_blueprints = blueprint_library.filter('vehicle.*')
        return list(set([bp.id for bp in vehicle_blueprints]))
