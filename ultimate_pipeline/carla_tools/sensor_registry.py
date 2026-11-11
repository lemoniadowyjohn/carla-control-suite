from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable


class SensorStopError(RuntimeError):
    """A producer could not be proven stopped, so its actor was not destroyed."""


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
        """Stop the producer, prove it stopped, then destroy the actor.

        Fail-closed: if ``stop()`` raises or the actor still reports
        ``is_listening`` afterwards, nothing is destroyed and the actor
        reference is kept. Destroying storage while a producer may still be
        live is exactly the use-after-free this ordering exists to prevent.
        """
        if self.actor is None:
            return
        stop = getattr(self.actor, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception as exc:
                raise SensorStopError(
                    f"sensor {self.id!r} stop() failed; refusing destroy "
                    f"while producer liveness is unproven: {exc}"
                ) from exc
        listening = getattr(self.actor, "is_listening", None)
        if listening:
            raise SensorStopError(
                f"sensor {self.id!r} still reports is_listening={listening!r} "
                f"after stop(); refusing destroy"
            )
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
        instance = self._sensors.get(sensor_id)
        if instance is None:
            return
        instance.destroy()
        self._sensors.pop(sensor_id, None)

    def clear(self) -> None:
        failures: list[str] = []
        for sensor_id, instance in list(self._sensors.items()):
            try:
                instance.destroy()
            except Exception as exc:
                failures.append(f"{sensor_id}: {exc}")
                continue
            self._sensors.pop(sensor_id, None)
        if failures:
            raise SensorStopError(
                "refusing to clear sensors whose producers were not proven "
                f"stopped: {'; '.join(failures)}"
            )

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
