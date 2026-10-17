"""Per-sensor bounded frame bridge (BL-26 core).

Connects a sensor-callback producer to a worker consumer without ever
blocking the producer thread. Qt-free by design: the GUI hand-off is an
ingress object owned by the caller (``FrameIngress`` in feeds), not this
module.

Contract:
* ``offer`` is the only producer entry point. It performs no I/O, no
  decoding and no waiting -- the rules CARLA listener threads must obey.
* Queues are bounded; overflow drops the oldest frame and counts it.
* Frame ids are never fabricated; regressions and duplicates are recorded
  in :class:`FrameBookkeeping`, not smoothed over.
* ``close`` stops acceptance before anything is destroyed, mirroring the
  required ``sensor.stop()`` before ``sensor.destroy()`` ordering.
"""

from __future__ import annotations

import threading

from ultimate_pipeline.gui.results import Result
from ultimate_pipeline.gui.sensors.queues import (
    BoundedFrameQueue, Decimator, Frame, FrameBookkeeping,
)

__all__ = ["SensorChannel"]

_SOURCE = "ultimate_pipeline/gui/core/sensor_bridge.py"


class SensorChannel:
    """Bounded frame pipeline for one sensor stream.

    Producer side: ``SensorService.deliver`` -> ``offer`` on the sensor
    callback thread.  Consumer side: ``poll_preview`` on a worker thread,
    which forwards decimated previews to a caller-owned Qt ingress.
    """

    def __init__(
        self,
        sensor_id: str,
        sensor_type: str,
        *,
        maxlen: int = 64,
        drop: str = "oldest",
        preview_decimation: int = 4,
    ) -> None:
        if not sensor_id:
            raise ValueError("sensor_id is required")
        if not sensor_type:
            raise ValueError("sensor_type is required")
        self.sensor_id = sensor_id
        self.sensor_type = sensor_type
        self._queue: BoundedFrameQueue[Frame] = BoundedFrameQueue(
            maxlen=maxlen, drop=drop)
        self._bookkeeping = FrameBookkeeping(sensor_id=sensor_id)
        self._preview = Decimator(preview_decimation)
        self._lock = threading.Lock()
        self._closed = False
        self._rejected_after_close = 0

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def offer(self, frame: Frame) -> Result:
        """Producer-side enqueue. Never blocks; never raises for backpressure."""
        if frame is None:
            return Result.failure(
                "frame is None", error_class="ValueError", error_source=_SOURCE,
                remediation="a missing frame is never fabricated")
        if frame.sensor_id and frame.sensor_id != self.sensor_id:
            return Result.failure(
                f"frame belongs to sensor {frame.sensor_id!r}, "
                f"not {self.sensor_id!r}",
                error_class="ValueError", error_source=_SOURCE)
        with self._lock:
            if self._closed:
                self._rejected_after_close += 1
                return Result.failure(
                    f"channel for {self.sensor_id!r} is closed",
                    error_class="SensorChannelClosed", error_source=_SOURCE,
                    remediation="attach a new sensor before delivering frames")
            ordering = self._bookkeeping.observe(frame)
            accepted = self._queue.offer(frame)
            pending = len(self._queue)
        # No gap computation on the producer path: gap_count is an on-demand
        # diagnostics value (see stats()). Per-frame work stays O(1).
        return Result.success({
            "accepted": accepted,
            "pending": pending,
            "ordering": ordering.as_dict(),
        })

    def poll_preview(self, limit: int = 8) -> list[Frame]:
        """Worker-side drain. Returns only decimated preview frames."""
        drained = self._queue.drain(limit)
        previews: list[Frame] = []
        for frame in drained:
            preview = self._preview.offer(frame)
            if preview is not None:
                previews.append(preview)
        return previews

    def pending(self) -> int:
        return len(self._queue)

    def close(self) -> dict:
        """Stop accepting frames and drain the remainder. Idempotent."""
        with self._lock:
            self._closed = True
        discarded = self._queue.drain()
        stats = self.stats()
        stats["discarded_on_close"] = len(discarded)
        return stats

    def stats(self) -> dict:
        with self._lock:
            ordering = self._bookkeeping.report()
            gaps = self._bookkeeping.gap_count()
            rejected = self._rejected_after_close
        return {
            "sensor_id": self.sensor_id,
            "sensor_type": self.sensor_type,
            "closed": self.closed,
            "pending": self.pending(),
            "queue": self._queue.stats.as_dict(),
            "ordering": ordering.as_dict(),
            "gaps": gaps,
            "rejected_after_close": rejected,
            "preview_emitted": self._preview.emitted,
        }
