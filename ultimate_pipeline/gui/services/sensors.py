"""Native sensor adapter service (BL-26, Stage B2).

Truthfulness contract:
* ``rgb_camera``, ``depth_camera``, ``semantic_segmentation``,
  ``instance_segmentation`` and ``lidar`` are advertised native because
  CARLA 0.9.16 provides these blueprints and the repository has a spawn
  path for them.
* ``radar``, ``gnss`` and ``imu`` have **no truthful adapter** anywhere in
  this repository (``COVERAGE_ACCOUNTING.json`` lists them under
  ``sensor_types_absent``). They are reported unsupported with evidence,
  never stubbed into something that looks working.
* Every attachment carries its ``source_class`` (``MOCK_BACKEND`` or
  ``LIVE_CARLA``) so a GUI can never label mock frames CARLA-native.
* ``attach``/``detach`` mutate the simulated world and are refused without
  an explicit exclusive authority (the Stage B0 fail-closed gate).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from ultimate_pipeline.gui.core.sensor_bridge import SensorChannel
from ultimate_pipeline.gui.results import Result, UnsupportedCapability
from ultimate_pipeline.gui.sensors.queues import Frame
from ultimate_pipeline.gui.session.session import exclusive_claimed

__all__ = [
    "SensorService", "SensorAttachment", "NativeSensorSpec",
    "SENSOR_BLUEPRINTS", "UNSUPPORTED_SENSOR_TYPES",
]

SOURCE = "ultimate_pipeline/gui/services/sensors.py"
AUTHORITY_SOURCE = "ultimate_pipeline/gui/session/session.py"

SENSOR_BLUEPRINTS: dict[str, str] = {
    "rgb_camera": "sensor.camera.rgb",
    "depth_camera": "sensor.camera.depth",
    "semantic_segmentation": "sensor.camera.semantic_segmentation",
    "instance_segmentation": "sensor.camera.instance_segmentation",
    "lidar": "sensor.lidar.ray_cast",
}

_SCANNED = (
    "ultimate_pipeline/carla_tools/sensor_registry.py implements rgb/lidar "
    "only; COVERAGE_ACCOUNTING.json lists radar/gnss/imu in "
    "sensor_types_absent"
)

UNSUPPORTED_SENSOR_TYPES: dict[str, UnsupportedCapability] = {
    name: UnsupportedCapability(
        f"{name} sensor adapter",
        "no truthful adapter exists in this repository",
        "keep the panel NOT_IMPLEMENTED until a native adapter is reviewed",
        _SCANNED,
    )
    for name in ("radar", "gnss", "imu")
}


@dataclass(frozen=True)
class NativeSensorSpec:
    """Adapter-side spawn request handed to the backend."""

    sensor_type: str
    blueprint: str


@dataclass(frozen=True)
class SensorAttachment:
    """One attached sensor plus its bounded frame channel."""

    sensor_id: str
    sensor_type: str
    blueprint: str
    source_class: str
    calibration_id: str
    channel: SensorChannel


class SensorService:
    """Owns sensor attachments and their per-sensor frame channels.

    The service is the single frame-ingress boundary: adapters call
    :meth:`deliver` from sensor callback threads, workers call
    :meth:`poll_preview`. Nothing else touches the queues.
    """

    def __init__(
        self,
        backend: Any,
        *,
        source_class: str = "MOCK_BACKEND",
        default_queue_len: int = 64,
        preview_decimation: int = 4,
    ) -> None:
        if not source_class:
            raise ValueError(
                "source_class is required; frame origin is never assumed")
        self.source_class = source_class
        self._backend = backend
        self._default_queue_len = int(default_queue_len)
        self._preview_decimation = int(preview_decimation)
        self._channels: dict[str, SensorChannel] = {}
        self._attachments: dict[str, SensorAttachment] = {}
        self._lock = threading.RLock()

    # -- declarations ------------------------------------------------------
    def supported_types(self) -> dict:
        return {
            "native": sorted(SENSOR_BLUEPRINTS),
            "unsupported": {
                name: {"reason": uc.reason, "remediation": uc.remediation,
                       "source": uc.source}
                for name, uc in sorted(UNSUPPORTED_SENSOR_TYPES.items())
            },
            "source_class": self.source_class,
        }

    # -- attach / detach ---------------------------------------------------
    def attach(
        self,
        sensor_type: str,
        calibration: Any,
        authority: Any,
        *,
        queue_len: int | None = None,
        preview_decimation: int | None = None,
    ) -> Result:
        """Spawn and bind a sensor. Mutating: requires exclusive authority."""
        unsupported = UNSUPPORTED_SENSOR_TYPES.get(sensor_type)
        if unsupported is not None:
            return Result.failure(
                f"{sensor_type} has no truthful adapter: {unsupported.reason}",
                error_class="UnsupportedSensorError",
                error_source=unsupported.source,
                remediation=unsupported.remediation)
        blueprint = SENSOR_BLUEPRINTS.get(sensor_type)
        if blueprint is None:
            return Result.failure(
                f"unknown sensor type {sensor_type!r}",
                error_class="KeyError", error_source=SOURCE,
                remediation=(
                    f"native: {sorted(SENSOR_BLUEPRINTS)}; unsupported: "
                    f"{sorted(UNSUPPORTED_SENSOR_TYPES)}"))
        if not exclusive_claimed(authority):
            return Result.blocked(
                f"attach({sensor_type}) mutates the world; authority "
                f"{authority!r} is not an explicit exclusive grant",
                remediation="claim EXCLUSIVE_WORLD before attaching sensors",
                error_class="AuthorityRequired", error_source=AUTHORITY_SOURCE)
        bound = self._backend.attach_sensor(
            NativeSensorSpec(sensor_type, blueprint), calibration)
        if not bound.ok:
            return bound
        binding = bound.unwrap()
        channel = SensorChannel(
            binding.sensor_id,
            sensor_type,
            maxlen=queue_len or self._default_queue_len,
            preview_decimation=(preview_decimation
                                or self._preview_decimation),
        )
        attachment = SensorAttachment(
            sensor_id=binding.sensor_id,
            sensor_type=sensor_type,
            blueprint=blueprint,
            source_class=self.source_class,
            calibration_id=getattr(binding, "calibration_id", ""),
            channel=channel,
        )
        with self._lock:
            self._channels[binding.sensor_id] = channel
            self._attachments[binding.sensor_id] = attachment
        return Result.success(attachment)

    def detach(self, sensor_id: str, authority: Any) -> Result:
        """Close the channel first, then destroy the backend sensor."""
        with self._lock:
            channel = self._channels.get(sensor_id)
        if channel is None:
            return Result.failure(
                f"sensor {sensor_id!r} is not attached",
                error_class="KeyError", error_source=SOURCE)
        if not exclusive_claimed(authority):
            return Result.blocked(
                f"detach({sensor_id}) destroys a sensor; authority "
                f"{authority!r} is not an explicit exclusive grant",
                remediation="claim EXCLUSIVE_WORLD before detaching sensors",
                error_class="AuthorityRequired", error_source=AUTHORITY_SOURCE)
        channel_stats = channel.close()
        detach_sensor = getattr(self._backend, "detach_sensor", None)
        if detach_sensor is None:
            with self._lock:
                self._channels.pop(sensor_id, None)
                self._attachments.pop(sensor_id, None)
            return Result.failure(
                f"backend {type(self._backend).__name__} has no detach_sensor; "
                "channel closed but the sensor may still exist",
                error_class="UnsupportedCapability", error_source=SOURCE,
                value=channel_stats)
        backend_result = detach_sensor(sensor_id)
        with self._lock:
            self._channels.pop(sensor_id, None)
            self._attachments.pop(sensor_id, None)
        if not backend_result.ok:
            return Result.failure(
                f"channel closed but backend detach failed: "
                f"{backend_result.reason}",
                error_class=backend_result.error_class or "RuntimeError",
                error_source=backend_result.error_source or SOURCE,
                value=channel_stats)
        return Result.success({"sensor_id": sensor_id, "channel": channel_stats})

    # -- frame path --------------------------------------------------------
    def deliver(self, sensor_id: str, frame: Frame) -> Result:
        """Sensor-callback entry point. Non-blocking; performs no I/O."""
        if frame is None:
            return Result.failure(
                "frame is None", error_class="ValueError", error_source=SOURCE,
                remediation="a missing frame is never fabricated")
        if frame.sensor_id and frame.sensor_id != sensor_id:
            return Result.failure(
                f"frame belongs to {frame.sensor_id!r}, not {sensor_id!r}",
                error_class="ValueError", error_source=SOURCE)
        with self._lock:
            channel = self._channels.get(sensor_id)
        if channel is None:
            return Result.failure(
                f"sensor {sensor_id!r} is not attached",
                error_class="KeyError", error_source=SOURCE,
                remediation="attach() the sensor before delivering frames")
        return channel.offer(frame)

    def poll_preview(self, sensor_id: str, limit: int = 8) -> Result:
        """Worker-side drain with preview decimation."""
        with self._lock:
            channel = self._channels.get(sensor_id)
        if channel is None:
            return Result.failure(
                f"sensor {sensor_id!r} is not attached",
                error_class="KeyError", error_source=SOURCE)
        return Result.success(channel.poll_preview(limit))

    # -- introspection -----------------------------------------------------
    def attachment(self, sensor_id: str) -> SensorAttachment | None:
        with self._lock:
            return self._attachments.get(sensor_id)

    def channel(self, sensor_id: str) -> SensorChannel | None:
        with self._lock:
            return self._channels.get(sensor_id)

    def sensor_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._channels))

    def stats(self, sensor_id: str | None = None) -> dict:
        with self._lock:
            if sensor_id is not None:
                channel = self._channels.get(sensor_id)
                return channel.stats() if channel is not None else {}
            return {sid: ch.stats()
                    for sid, ch in sorted(self._channels.items())}
