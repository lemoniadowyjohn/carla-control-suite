#!/usr/bin/env python3
"""Pytest session start-up: stub carla for offline unit tests where CARLA is not installed.

If a real `carla` package is importable (e.g. the real 0.9.16 client is
installed in this venv), it must NOT be shadowed: tests that explicitly
check against the live carla API (carla.Client, carla.Transform, the real
CityObjectLabel enum values, etc. -- see test_carla_classes.py,
test_semantic_tagging.py, tests/carla_tools/test_world_settings_hardening.py)
depend on getting the genuine module, with a live-server skip handled by the
test itself. Installing this stub unconditionally previously poisoned
sys.modules["carla"] for the entire pytest session (conftest.py import
happens during collection, before any test runs), which is a test-isolation
bug, not an offline-support feature.
"""

import sys
import types

try:
    import carla as _real_carla  # noqa: F401
    _REAL_CARLA_AVAILABLE = True
except Exception:
    _REAL_CARLA_AVAILABLE = False

if not _REAL_CARLA_AVAILABLE:
    _carla_module = types.ModuleType("carla")
    _carla_module.CityObjectLabel = type("CityObjectLabel", (), {"Road": 0, "TrafficLight": 1})()
    _carla_module.ColorConverter = type("ColorConverter", (), {"CityScapesPalette": "palette"})
    _carla_module.Image = object
    _carla_module.Sensor = object
    _carla_module.__offline_stub__ = True

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