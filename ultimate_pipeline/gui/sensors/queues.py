"""Bounded sensor callback queues and frame bookkeeping.

Hard rules from the operating contract:

* **A sensor callback performs no blocking I/O.** The callback enqueues and
  returns; all decoding happens on a worker thread.
* Queues are **bounded**. A full queue drops the *oldest* frame and increments a
  counter, so a slow consumer can never exhaust memory and never blocks the
  simulator callback thread.
* **Frame ids and timestamps are tracked**; non-monotonic frame ids are
  detected and reported, not smoothed over.
* GUI previews are **decimated** -- the preview path never carries full-rate
  data into the UI thread.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Generic, TypeVar

__all__ = [
    "Frame", "QueueStats", "BoundedFrameQueue", "FrameBookkeeping",
    "OrderingReport", "Decimator", "FrameIdMissingError",
]

T = TypeVar("T")


class FrameIdMissingError(ValueError):
    """A frame arrived without a frame id. Fabrication is refused."""


@dataclass(frozen=True)
class Frame:
    """One sensor sample. ``frame_id`` is mandatory."""

    frame_id: int
    timestamp: float
    payload: Any = None
    sensor_id: str = ""

    def __post_init__(self) -> None:
        if self.frame_id is None:
            raise FrameIdMissingError(
                "frame id is required; a missing frame id is never fabricated")


@dataclass
class QueueStats:
    enqueued: int = 0
    delivered: int = 0
    dropped_oldest: int = 0
    dropped_newest: int = 0
    max_depth: int = 0

    @property
    def dropped(self) -> int:
        return self.dropped_oldest + self.dropped_newest

    def as_dict(self) -> dict:
        return {"enqueued": self.enqueued, "delivered": self.delivered,
                "dropped": self.dropped, "dropped_oldest": self.dropped_oldest,
                "dropped_newest": self.dropped_newest, "max_depth": self.max_depth}


class BoundedFrameQueue(Generic[T]):
    """Thread-safe bounded queue for sensor callbacks. Never blocks the producer.

    The callback thread calls :meth:`offer` only. That method acquires a lock
    briefly and performs no I/O, no decoding and no waiting.
    """

    def __init__(self, maxlen: int = 64, *, drop: str = "oldest") -> None:
        if maxlen <= 0:
            raise ValueError("maxlen must be positive")
        if drop not in ("oldest", "newest"):
            raise ValueError("drop must be 'oldest' or 'newest'")
        self.maxlen = int(maxlen)
        self.drop = drop
        self._items: Deque[T] = deque(maxlen=self.maxlen)
        self._lock = threading.Lock()
        self.stats = QueueStats()

    def offer(self, item: T) -> bool:
        """Enqueue from a sensor callback. Returns False if the item was dropped."""
        with self._lock:
            if len(self._items) == self.maxlen:
                if self.drop == "oldest":
                    self._items.popleft()
                    self.stats.dropped_oldest += 1
                else:
                    self.stats.dropped_newest += 1
                    return False
            self._items.append(item)
            self.stats.enqueued += 1
            self.stats.max_depth = max(self.stats.max_depth, len(self._items))
            return True

    def get(self, timeout: float | None = None) -> T | None:
        """Consume one item on a worker thread. ``None`` when empty."""
        with self._lock:
            if not self._items:
                return None
            item = self._items.popleft()
            self.stats.delivered += 1
            return item

    def drain(self, limit: int | None = None) -> list[T]:
        out: list[T] = []
        with self._lock:
            while self._items and (limit is None or len(out) < limit):
                out.append(self._items.popleft())
                self.stats.delivered += 1
        return out

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


@dataclass
class OrderingReport:
    monotonic: bool
    regressions: int = 0
    duplicate_frame_ids: int = 0
    backwards_steps: tuple[tuple[int, int], ...] = ()
    max_backwards_jump: int = 0

    def as_dict(self) -> dict:
        return {"monotonic": self.monotonic, "regressions": self.regressions,
                "duplicate_frame_ids": self.duplicate_frame_ids,
                "backwards_steps": [list(p) for p in self.backwards_steps],
                "max_backwards_jump": self.max_backwards_jump}


@dataclass
class FrameBookkeeping:
    """Tracks frame-id ordering and drops for one sensor stream."""

    sensor_id: str = ""
    last_frame_id: int | None = None
    seen: set[int] = field(default_factory=set)
    dropped: int = 0
    regressions: int = 0
    steps: list[tuple[int, int]] = field(default_factory=list)

    def observe(self, frame: Frame) -> OrderingReport:
        """Record one frame and report whether ordering held."""
        if frame.frame_id in self.seen:
            self.dropped += 1
        self.seen.add(frame.frame_id)

        if self.last_frame_id is not None:
            if frame.frame_id < self.last_frame_id:
                self.regressions += 1
                self.steps.append((self.last_frame_id, frame.frame_id))

        self.last_frame_id = frame.frame_id
        return self.report()

    def report(self) -> OrderingReport:
        duplicates = self.dropped
        return OrderingReport(
            monotonic=self.regressions == 0,
            regressions=self.regressions,
            duplicate_frame_ids=duplicates,
            backwards_steps=tuple(self.steps),
            max_backwards_jump=max((a - b for a, b in self.steps), default=0),
        )

    def gap_count(self) -> int:
        """Missing frame ids implied by the observed range."""
        if not self.seen:
            return 0
        return (max(self.seen) - min(self.seen) + 1) - len(self.seen)


class Decimator:
    """Emit at most one preview frame per ``n`` input frames.

    Decimation happens on the worker path so the UI thread never receives
    full-rate data.
    """

    def __init__(self, n: int) -> None:
        if n < 1:
            raise ValueError("decimation factor must be >= 1")
        self.n = int(n)
        self._counter = 0

    def offer(self, item: T) -> T | None:
        self._counter += 1
        if self._counter % self.n == 0:
            return item
        return None

    @property
    def emitted(self) -> int:
        return self._counter // self.n