# ultimate_pipeline/scenarios/sweeps.py

from __future__ import annotations
import carla
import time

class ScenarioSweeper:
    """
    Run multiple scenarios on a tile to test robustness.
    """

    @staticmethod
    def run_sweep(world, ego, steps=200):
        weathers = [
            carla.WeatherParameters.ClearSunset,
            carla.WeatherParameters.WetCloudySunset,
            carla.WeatherParameters.HardRainNoon,
            carla.WeatherParameters.SoftRainSunset,
        ]

        for w in weathers:
            world.set_weather(w)
            print(f"Testing weather: {w}")

            for t in range(steps):
                ego.apply_control(carla.VehicleControl(throttle=0.3))
                time.sleep(0.03)
