from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SensorSpec:
    blueprint: str
    transform: Any | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    callback: Callable | None = None
    attached_to: int | None = None

    def to_dict(self) -> dict:
        return {
            "blueprint": self.blueprint,
            "transform": str(self.transform),
            "attributes": dict(self.attributes),
            "attached_to": self.attached_to,
        }


@dataclass
class SensorInstance:
    spec: SensorSpec
    actor: Any
    id: str

    def destroy(self) -> None:
        if self.actor is not None:
            self.actor.destroy()
            self.actor = None

    def listen(self, callback: Callable) -> None:
        if self.actor is not None:
            self.actor.listen(callback)


class SensorRegistry:
    def __init__(self) -> None:
        self._sensors: dict[str, SensorInstance] = {}

    @property
    def sensors(self) -> dict[str, SensorInstance]:
        return dict(self._sensors)

    def register(self, sensor_id: str, spec: SensorSpec, actor: Any) -> SensorInstance:
        instance = SensorInstance(spec=spec, actor=actor, id=sensor_id)
        self._sensors[sensor_id] = instance
        return instance

    def get(self, sensor_id: str) -> SensorInstance | None:
        return self._sensors.get(sensor_id)

    def remove(self, sensor_id: str) -> None:
        instance = self._sensors.pop(sensor_id, None)
        if instance:
            instance.destroy()

    def clear(self) -> None:
        for instance in list(self._sensors.values()):
            instance.destroy()
        self._sensors.clear()

    def spawn(
        self,
        world: Any,
        blueprint_library: Any,
        sensor_id: str,
        spec: SensorSpec,
    ) -> SensorInstance:
        bp = blueprint_library.find(spec.blueprint)
        for key, val in spec.attributes.items():
            if bp.has_attribute(key):
                bp.set_attribute(key, val)
        if spec.transform:
            actor = world.spawn_actor(bp, spec.transform)
        else:
            actor = world.spawn_actor(bp)
        return self.register(sensor_id, spec, actor)

    def listen_all(self, callback: Callable) -> None:
        for instance in self._sensors.values():
            if instance.actor is not None:
                instance.listen(callback)

    def to_dict(self) -> dict:
        return {sid: inst.spec.to_dict() for sid, inst in self._sensors.items()}
