#!/usr/bin/env python3
"""Pytest session start-up: stub carla for offline unit tests where CARLA is not installed."""

import sys
import types
from _pytest.config import Config

_carla_module = types.ModuleType("carla")
_carla_module.CityObjectLabel = type("CityObjectLabel", (), {"Road": 0, "TrafficLight": 1})()
_carla_module.ColorConverter = type("ColorConverter", (), {"CityScapesPalette": "palette"})
_carla_module.Image = object
_carla_module.Sensor = object

sys.modules["carla"] = _carla_module

# Also stub any submodules that might be accessed (e.g., carla.lane, carla.weather)
for key in ("carla.lane", "carla.weather", "carla.traffic_light", "carla.maps", "carla.map", "carla.data"):
    if "." in key:
        parent = sys.modules.get(key.rsplit(".", 1)[0])
        if parent:
            setattr(parent, key.split(".")[-1], type(key.split(".")[-1], (), {}))

# Now that carla exists, any import of it will use our stub, breaking circular import loops
# that occur when capture_writer imports segmentation_dataset_generator_queues, which
# imports carla, which is already mocked.