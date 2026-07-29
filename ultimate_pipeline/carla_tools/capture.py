from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

from ultimate_pipeline.carla_tools.session import CarlaSession
from ultimate_pipeline.carla_tools.sensor_registry import SensorRegistry
from ultimate_pipeline.carla_tools.data_manager import DataManager


@dataclass
class CaptureConfig:
    frames: int = 10
    tick_delta: float = 1.0 / 60.0
    sensors: dict[str, dict[str, Any]] = field(default_factory=dict)


class CaptureManager:
    def __init__(
        self,
        session: CarlaSession,
        sensor_registry: SensorRegistry,
        data_manager: DataManager,
    ):
        self.session = session
        self.sensor_registry = sensor_registry
        self.data_manager = data_manager
        self._callbacks: list[Callable] = []

    def add_callback(self, cb: Callable) -> None:
        self._callbacks.append(cb)

    def capture(self, config: CaptureConfig) -> int:
        if self.session.world is None:
            raise RuntimeError("No world loaded in session.")
        world = self.session.world
        bp_lib = world.get_blueprint_library()
        for sensor_id, spec_dict in config.sensors.items():
            spec = __import__(
                "ultimate_pipeline.carla_tools.sensor_registry",
                fromlist=["SensorSpec"],
            ).SensorSpec(**spec_dict)
            self.sensor_registry.spawn(world, bp_lib, sensor_id, spec)
        self.session.set_sync_mode(config.tick_delta)
        frames_captured = 0
        for _ in range(config.frames):
            frame = self.session.tick()
            self.data_manager.record(frame, "tick", {"frame": frame})
            for cb in self._callbacks:
                cb(frame)
            frames_captured += 1
        self.sensor_registry.clear()
        return frames_captured
