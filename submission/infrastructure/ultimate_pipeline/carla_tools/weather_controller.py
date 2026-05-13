#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WeatherController for CARLA.

Features:
- Set fixed weather presets (clear, rain, fog, etc.)
- Randomized weather cycles over time
- Compatible with CARLA 0.9.16
"""

import random
import time
import threading
import carla


class WeatherController:
    """
    Simple weather manager that can:
    - set specific presets
    - run a background weather cycle thread
    """

    def __init__(self, world: carla.World):
        self.world = world
        self._stop_flag = threading.Event()
        self._thread = None

    # ----------------------------------------------------------
    # Basic presets
    # ----------------------------------------------------------

    @staticmethod
    def clear_noon() -> carla.WeatherParameters:
        return carla.WeatherParameters.ClearNoon

    @staticmethod
    def soft_rain() -> carla.WeatherParameters:
        w = carla.WeatherParameters(
            cloudiness=60.0,
            precipitation=30.0,
            precipitation_deposits=20.0,
            wind_intensity=20.0,
            sun_azimuth_angle=80.0,
            sun_altitude_angle=50.0,
            fog_density=5.0,
            fog_distance=0.0,
            wetness=40.0
        )
        return w

    @staticmethod
    def heavy_rain() -> carla.WeatherParameters:
        w = carla.WeatherParameters(
            cloudiness=90.0,
            precipitation=80.0,
            precipitation_deposits=80.0,
            wind_intensity=60.0,
            sun_azimuth_angle=30.0,
            sun_altitude_angle=20.0,
            fog_density=20.0,
            fog_distance=0.0,
            wetness=100.0
        )
        return w

    @staticmethod
    def foggy() -> carla.WeatherParameters:
        w = carla.WeatherParameters(
            cloudiness=60.0,
            precipitation=0.0,
            fog_density=80.0,
            fog_distance=5.0,
            sun_azimuth_angle=10.0,
            sun_altitude_angle=10.0,
        )
        return w

    # ----------------------------------------------------------
    # Control methods
    # ----------------------------------------------------------

    def set_weather(self, weather: carla.WeatherParameters) -> None:
        self.world.set_weather(weather)

    def set_random_weather_once(self) -> None:
        presets = [
            self.clear_noon(),
            self.soft_rain(),
            self.heavy_rain(),
            self.foggy(),
        ]
        w = random.choice(presets)
        self.world.set_weather(w)

    # ----------------------------------------------------------
    # Cyclic / randomized weather
    # ----------------------------------------------------------

    def start_random_cycle(self, cycle_length_sec: float = 120.0) -> None:
        """
        Start a background thread that randomly changes weather every
        `cycle_length_sec` seconds.
        """
        if self._thread and self._thread.is_alive():
            return  # already running

        self._stop_flag.clear()

        def _loop():
            while not self._stop_flag.is_set():
                self.set_random_weather_once()
                for _ in range(int(cycle_length_sec)):
                    if self._stop_flag.is_set():
                        break
                    time.sleep(1.0)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop_cycle(self) -> None:
        self._stop_flag.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
