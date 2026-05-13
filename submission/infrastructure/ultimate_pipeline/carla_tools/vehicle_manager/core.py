import carla
import logging
import threading
from typing import Optional, List, Dict, Any
from .cache import VehicleCacheManager
from .spawner import VehicleSpawner
from .validator import VehicleValidator


class VehicleManager:
    """Main vehicle management class with performance optimizations"""

    def __init__(
            self,
            client: carla.Client,
            world: carla.World,
            traffic_manager_port: int = 8000):
        self.client = client
        self.world = world
        self.map = world.get_map()
        self.vehicles: List[carla.Vehicle] = []
        self._vehicles_lock = threading.RLock()

        # Initialize components
        self.traffic_manager = client.get_trafficmanager(traffic_manager_port)
        self.cache_manager = VehicleCacheManager()
        self.spawner = VehicleSpawner(world, self.traffic_manager)
        self.validator = VehicleValidator()

        self.logger = logging.getLogger(__name__)
        self.logger.info(
            "VehicleManager initialized with modular architecture")

    def spawn_vehicle(self, vehicle_type: str = 'model3',
                      spawn_point: int = 0) -> Optional[carla.Vehicle]:
        """Spawn a vehicle and add to management"""
        vehicle = self.spawner.spawn_vehicle(vehicle_type, spawn_point)

        if vehicle:
            with self._vehicles_lock:
                self.vehicles.append(vehicle)
            self.cache_manager.cache_vehicle(vehicle)

        return vehicle

    def get_vehicle_state(self, vehicle: carla.Vehicle,
                          use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """Get vehicle state with optional caching"""
        if not self.validator.validate_vehicle(vehicle, self.vehicles):
            self.logger.error("Invalid vehicle for state query")
            return None

        # Try cache first
        current_time = self.world.get_snapshot().timestamp.elapsed_seconds
        if use_cache:
            cached_state = self.cache_manager.get_cached_state(
                vehicle.id, current_time)
            if cached_state:
                return cached_state

        # Fallback to live data
        try:
            transform = vehicle.get_transform()
            velocity = vehicle.get_velocity()
            acceleration = vehicle.get_acceleration()
            angular_velocity = vehicle.get_angular_velocity()

            speed_kmh = 3.6 * (velocity.x ** 2 + velocity.y **
                               2 + velocity.z ** 2) ** 0.5

            state = {
                'id': vehicle.id,
                'location': {
                    'x': transform.location.x,
                    'y': transform.location.y,
                    'z': transform.location.z},
                'rotation': {
                    'pitch': transform.rotation.pitch,
                    'yaw': transform.rotation.yaw,
                    'roll': transform.rotation.roll},
                'velocity': {
                    'x': velocity.x,
                    'y': velocity.y,
                    'z': velocity.z},
                'acceleration': {
                    'x': acceleration.x,
                    'y': acceleration.y,
                    'z': acceleration.z},
                'angular_velocity': {
                    'x': angular_velocity.x,
                    'y': angular_velocity.y,
                    'z': angular_velocity.z},
                'speed_kmh': speed_kmh,
                'is_alive': vehicle.is_alive}

            # Update cache
            self.cache_manager.update_state_cache(
                vehicle.id, state, current_time)
            return state

        except Exception as e:
            self.logger.error(f"Error getting vehicle state: {e}")
            return None

    def get_all_vehicle_states(
            self, use_cache: bool = True) -> Dict[int, Dict[str, Any]]:
        """Get states for all managed vehicles with cache optimization"""
        states = {}
        current_time = self.world.get_snapshot().timestamp.elapsed_seconds

        # Try bulk cache retrieval
        if use_cache:
            cache_stats = self.cache_manager.get_stats()
            if current_time - \
                    cache_stats['last_update_time'] < self.cache_manager._cache_ttl:
                with self._vehicles_lock:
                    for vehicle in self.vehicles:
                        cached_state = self.cache_manager.get_cached_state(
                            vehicle.id, current_time)
                        if cached_state:
                            states[vehicle.id] = cached_state

                if len(states) == len(self.vehicles):
                    return states

        # Fallback to individual collection
        with self._vehicles_lock:
            for vehicle in self.vehicles:
                state = self.get_vehicle_state(vehicle, use_cache=use_cache)
                if state:
                    states[vehicle.id] = state

        return states

    def destroy_vehicle(self, vehicle: carla.Vehicle) -> bool:
        """Destroy specific vehicle"""
        try:
            with self._vehicles_lock:
                if vehicle in self.vehicles:
                    vehicle.destroy()
                    self.vehicles.remove(vehicle)
                    self.cache_manager.remove_vehicle(vehicle.id)
                    self.logger.info(f"Destroyed vehicle {vehicle.id}")
                    return True
            return False
        except Exception as e:
            self.logger.error(f"Error destroying vehicle {vehicle.id}: {e}")
            return False

    def cleanup_all_vehicles(self) -> int:
        """Destroy all vehicles"""
        destroyed_count = 0
        with self._vehicles_lock:
            for vehicle in self.vehicles[:]:
                try:
                    vehicle.destroy()
                    destroyed_count += 1
                except Exception as e:
                    self.logger.error(f"Error destroying vehicle {vehicle.id}: {e}")

            self.vehicles.clear()
            self.cache_manager.clear_all()

        self.logger.info(f"Destroyed {destroyed_count} vehicles")
        return destroyed_count

    # Cache management delegation
    def clear_cache(self):
        """Clear all caches"""
        self.cache_manager.clear_all()
        self.logger.info("All caches cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        stats = self.cache_manager.get_stats()
        stats['total_vehicles_managed'] = len(self.vehicles)
        return stats

    def set_cache_ttl(self, ttl_seconds: float):
        """Set cache time-to-live"""
        self.cache_manager.set_cache_ttl(ttl_seconds)

    # Utility methods
    def get_vehicle_count(self) -> int:
        """Get current vehicle count"""
        return len(self.vehicles)

    def get_available_vehicle_types(self) -> List[str]:
        """Get available vehicle types"""
        return self.spawner.get_available_vehicle_types()

    def get_available_spawn_points(self) -> List[carla.Transform]:
        """Get available spawn points"""
        return self.spawner.get_available_spawn_points()
