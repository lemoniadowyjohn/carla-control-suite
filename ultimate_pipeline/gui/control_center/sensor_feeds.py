"""Native sensor feed bridge for the camera control center (Stage B4).

Connects the SensorService (Stage B2) to FeedsPanel's FrameIngress: a
bounded QTimer on the GUI thread drains decimated previews and publishes
QImage payloads only. Non-image payloads are counted and skipped --
never faked into pictures. Every adapter-fed tile label carries the
attachment's ``source_class`` so mock frames can never be presented as
CARLA-native (``LIVE_VERIFIED`` requires a live RPC, which this bridge
never claims).
"""
from __future__ import annotations

import time
from typing import Any, Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QImage

from ultimate_pipeline.gui.results import Result

__all__ = ["SensorFeedBridge", "CAMERA_TILE_MAP", "RENDERABLE_CAMERA_TYPES"]

SOURCE = "ultimate_pipeline/gui/control_center/sensor_feeds.py"

CAMERA_TILE_MAP: dict[str, str] = {
    "rgb_camera": "Front RGB",
    "depth_camera": "Depth",
    "semantic_segmentation": "Semantic",
}
RENDERABLE_CAMERA_TYPES = tuple(CAMERA_TILE_MAP)


class SensorFeedBridge(QObject):
    """Polls attached camera channels and publishes previews to FrameIngress.

    The timer runs on the GUI thread; ``poll_preview`` is a non-blocking
    drain (no decode, no I/O), which keeps Qt thread affinity trivially
    correct. Detach requires the same exclusive authority the SensorService
    demands -- the bridge never invents a grant.
    """

    activity = pyqtSignal(str)

    def __init__(self, sensors: Any, ingress: Any, *,
                 authority_provider: Callable[[], Any] | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sensors = sensors
        self._ingress = ingress
        self._authority_provider = authority_provider
        self._tiles: dict[str, str] = {}
        self._last_frame_at: dict[str, float] = {}
        self._non_image_payloads = 0
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.poll_once)

    @property
    def sensors(self) -> Any:
        return self._sensors

    @property
    def polling(self) -> bool:
        return self._timer.isActive()

    def _authority(self) -> Any:
        if self._authority_provider is None:
            return "SHARED_READONLY"
        return self._authority_provider()

    # -- attach / detach ---------------------------------------------------
    def attach_camera(self, sensor_type: str) -> Result:
        if sensor_type not in CAMERA_TILE_MAP:
            return Result.failure(
                f"{sensor_type} has no preview tile mapping",
                error_class="KeyError", error_source=SOURCE,
                remediation=f"renderable cameras: {list(CAMERA_TILE_MAP)}")
        # The poll timer (200 ms) is already the preview decimator; the
        # channel-level factor would drop the first frames of every attach.
        result = self._sensors.attach(sensor_type, None, self._authority(),
                                      preview_decimation=1)
        if not result.ok:
            self.activity.emit(
                f"ATTACH REFUSED · {sensor_type} · "
                f"{result.error_class or 'FAILURE'} · {result.reason}")
            return result
        attachment = result.unwrap()
        self._tiles[attachment.sensor_id] = CAMERA_TILE_MAP[sensor_type]
        self.activity.emit(
            f"ATTACHED {sensor_type} · {attachment.sensor_id} · source "
            f"{attachment.source_class} · adapter frames, not LIVE_VERIFIED")
        if not self._timer.isActive():
            self._timer.start()
        return result

    def detach(self, sensor_id: str) -> Result:
        result = self._sensors.detach(sensor_id, self._authority())
        self._tiles.pop(sensor_id, None)
        self._last_frame_at.pop(sensor_id, None)
        if result.ok:
            self.activity.emit(
                f"DETACHED {sensor_id} · channel closed before destroy")
        else:
            self.activity.emit(
                f"DETACH REFUSED · {sensor_id} · "
                f"{result.error_class or 'FAILURE'} · {result.reason}")
        if not self._sensors.sensor_ids():
            self._timer.stop()
        return result

    def stop_polling(self) -> None:
        """Stop the poll timer. Does not detach sensors."""
        self._timer.stop()

    # -- frame path --------------------------------------------------------
    def tile_for(self, sensor_id: str) -> str | None:
        return self._tiles.get(sensor_id)

    def source_label(self, sensor_id: str) -> str | None:
        """Tile source string for adapter-owned sensors; None if external."""
        if sensor_id not in self._tiles:
            return None
        attachment = self._sensors.attachment(sensor_id)
        source_class = attachment.source_class if attachment else "UNKNOWN"
        return f"ADAPTER {source_class}"

    def poll_once(self) -> int:
        """Drain previews for every attached camera. Returns frames published."""
        published = 0
        for sensor_id in list(self._tiles):
            result = self._sensors.poll_preview(sensor_id, limit=2)
            if not result.ok:
                continue
            for frame in result.value:
                image = frame.payload if isinstance(frame.payload, QImage) else None
                if image is None:
                    self._non_image_payloads += 1
                    continue
                self._ingress.publish(
                    sensor_id, image, frame.frame_id, frame.timestamp)
                self._last_frame_at[sensor_id] = time.monotonic()
                published += 1
        return published

    def frame_age_s(self, sensor_id: str) -> float | None:
        at = self._last_frame_at.get(sensor_id)
        return None if at is None else time.monotonic() - at

    # -- reporting ---------------------------------------------------------
    def diagnostics_text(self) -> str:
        lines: list[str] = []
        sensor_ids = self._sensors.sensor_ids()
        if not sensor_ids:
            lines.append("No attached native sensors.")
        for sensor_id in sensor_ids:
            stats = self._sensors.stats(sensor_id)
            queue = stats.get("queue", {})
            ordering = stats.get("ordering", {})
            age = self.frame_age_s(sensor_id)
            lines.append(
                f"{sensor_id} ({stats.get('sensor_type', '?')}): "
                f"enqueued={queue.get('enqueued', 0)} "
                f"dropped={queue.get('dropped', 0)} "
                f"pending={stats.get('pending', 0)} "
                f"monotonic={ordering.get('monotonic')} "
                f"gaps={stats.get('gaps', 0)} "
                f"frame_age={'N/A' if age is None else f'{age:.1f}s'}")
        if self._non_image_payloads:
            lines.append(
                "non-image payloads skipped (never rendered): "
                f"{self._non_image_payloads}")
        return "\n".join(lines)

    def inventory_rows(self) -> list[tuple[str, str, str]]:
        """(name, blueprint-or-dash, status) rows for the inventory table."""
        from ultimate_pipeline.gui.services.sensors import SENSOR_BLUEPRINTS

        declaration = self._sensors.supported_types()
        rows = [(name, SENSOR_BLUEPRINTS[name],
                 f"NATIVE · source {declaration['source_class']}")
                for name in declaration["native"]]
        rows += [(name, "—",
                  f"NOT_IMPLEMENTED · {entry['reason']}")
                 for name, entry in declaration["unsupported"].items()]
        for sensor_id in self._sensors.sensor_ids():
            attachment = self._sensors.attachment(sensor_id)
            if attachment is None:
                continue
            rows.append((
                f"attached:{sensor_id}", attachment.blueprint,
                f"ATTACHED · {attachment.source_class} · "
                f"cal={attachment.calibration_id or 'NONE'}"))
        return rows
