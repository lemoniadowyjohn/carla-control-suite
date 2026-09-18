import weakref
import threading
from typing import Dict, Any, Optional
import logging


class VehicleCacheManager:
    """Manages vehicle and state caching for performance optimization"""

    def __init__(self, cache_ttl: float = 0.1):
        self._vehicle_cache = weakref.WeakValueDictionary()
        self._state_cache: Dict[int, Dict[str, Any]] = {}
        self._cache_lock = threading.RLock()
        self._last_update_time = 0.0
        self._cache_ttl = cache_ttl
        self.logger = logging.getLogger(__name__)

    def get_cached_state(self, vehicle_id: int,
                         current_time: float) -> Optional[Dict[str, Any]]:
        """Get cached state if valid"""
        if current_time - self._last_update_time < self._cache_ttl:
            with self._cache_lock:
                if vehicle_id in self._state_cache:
                    return self._state_cache[vehicle_id].copy()
        return None

    def update_state_cache(self, vehicle_id: int,
                           state: Dict[str, Any], current_time: float):
        """Update state cache"""
        with self._cache_lock:
            self._state_cache[vehicle_id] = state.copy()
            self._last_update_time = current_time

    def cache_vehicle(self, vehicle):
        """Add vehicle to cache"""
        with self._cache_lock:
            self._vehicle_cache[vehicle.id] = vehicle

    def is_vehicle_cached(self, vehicle_id: int) -> bool:
        """Check if vehicle is in cache"""
        with self._cache_lock:
            return vehicle_id in self._vehicle_cache

    def remove_vehicle(self, vehicle_id: int):
        """Remove vehicle from caches"""
        with self._cache_lock:
            self._vehicle_cache.pop(vehicle_id, None)
            self._state_cache.pop(vehicle_id, None)

    def clear_all(self):
        """Clear all caches"""
        with self._cache_lock:
            self._vehicle_cache.clear()
            self._state_cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._cache_lock:
            return {
                'vehicle_cache_size': len(self._vehicle_cache),
                'state_cache_size': len(self._state_cache),
                'cache_ttl_seconds': self._cache_ttl,
                'last_update_time': self._last_update_time
            }

    def set_cache_ttl(self, ttl_seconds: float):
        """Set cache time-to-live"""
        if ttl_seconds >= 0:
            self._cache_ttl = ttl_seconds
            self.logger.info(f"Cache TTL set to {ttl_seconds} seconds")
        else:
            self.logger.warning("Cache TTL must be non-negative")
