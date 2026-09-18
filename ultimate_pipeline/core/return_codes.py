from __future__ import annotations

from enum import IntEnum


class PerceptionReturnCode(IntEnum):
    OK = 0
    CARLA_NOT_REACHABLE = 1
    CARLA_HUNG_NO_TICK = 2
    MAP_LOAD_FAILED = 3
    SPAWN_FAILED = 4
    SENSOR_SETUP_FAILED = 5
    CAPTURE_FAILED = 6
    METRICS_FAILED = 7
