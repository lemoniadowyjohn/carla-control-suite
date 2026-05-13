import carla
import logging
from typing import List, Optional


class VehicleValidator:
    """Validates vehicle states and operations"""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

    @staticmethod
    def validate_vehicle(vehicle: carla.Vehicle,
                         managed_vehicles: List[carla.Vehicle]) -> bool:
        """Check if vehicle is valid and still exists"""
        if vehicle is None:
            return False

        # Check if vehicle is in managed list
        if vehicle.id not in [v.id for v in managed_vehicles]:
            return False

        # Try to access vehicle properties
        try:
            vehicle.get_transform()
            return True
        except RuntimeError:
            return False

    @staticmethod
    def validate_spawn_point(
            spawn_point: int,
            total_spawn_points: int) -> bool:
        """Validate spawn point index"""
        return 0 <= spawn_point < total_spawn_points

    def filter_alive_vehicles(
            self, vehicles: List[carla.Vehicle]) -> List[carla.Vehicle]:
        """Filter out destroyed vehicles"""
        alive_vehicles = []
        for vehicle in vehicles:
            if self.validate_vehicle(vehicle, vehicles):
                alive_vehicles.append(vehicle)
            else:
                self.logger.warning(f"Vehicle {vehicle.id} is no longer alive")
        return alive_vehicles
