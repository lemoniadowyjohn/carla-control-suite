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

import math
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Generic, TypeVar

__all__ = [
    "Frame", "QueueStats", "BoundedFrameQueue", "FrameBookkeeping",
    "OrderingReport", "Decimator", "FrameIdMissingError", "FrameTimestampError",
]

T = TypeVar("T")


class FrameIdMissingError(ValueError):
    """A frame arrived without a frame id. Fabrication is refused."""


class FrameTimestampError(ValueError):
    """A frame arrived without a usable timestamp. Fabrication is refused."""


@dataclass(frozen=True)
class Frame:
    """One sensor sample. ``frame_id`` and ``timestamp`` are mandatory."""

    frame_id: int
    timestamp: float
    payload: Any = None
    sensor_id: str = ""

    def __post_init__(self) -> None:
        if self.frame_id is None:
            raise FrameIdMissingError(
                "frame id is required; a missing frame id is never fabricated")
        try:
            value = float(self.timestamp)
        except (TypeError, ValueError):
            raise FrameTimestampError(
                "timestamp is required and must be numeric; a malformed "
                "timestamp is never defaulted") from None
        if not math.isfinite(value):
            raise FrameTimestampError(
                "timestamp must be finite; NaN/inf is never defaulted")


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
    """Tracks frame-id ordering and drops for one sensor stream.

    Memory is bounded: ``seen`` is only a recent-id window used for duplicate
    detection (capped at ``seen_cap`` entries) and ``steps`` is capped at
    :data:`_STEPS_CAP` entries. Lifetime ``unique``/``min_seen``/``max_seen``
    aggregates let :meth:`gap_count` keep counting from the true observed
    range. Honest limitation: after a window reset, an id older than the
    window re-delivered counts as new, so gaps may be *understated* and
    ``dropped`` undercounted for very long streams -- gaps are never
    fabricated and never overstated. All bookkeeping work is O(1) per
    observed frame; gap *computation* happens only when :meth:`gap_count`
    is called explicitly (on-demand diagnostics), never implicitly on the
    producer path.
    """

    _STEPS_CAP = 64

    sensor_id: str = ""
    last_frame_id: int | None = None
    seen: set[int] = field(default_factory=set)
    dropped: int = 0
    regressions: int = 0
    steps: list[tuple[int, int]] = field(default_factory=list)
    seen_cap: int = 65536
    unique: int = 0
    min_seen: int | None = None
    max_seen: int | None = None

    def observe(self, frame: Frame) -> OrderingReport:
        """Record one frame and report whether ordering held. O(1) per frame."""
        if frame.frame_id in self.seen:
            self.dropped += 1
        else:
            if len(self.seen) >= self.seen_cap:
                # Bounded duplicate memory: the window resets, the lifetime
                # aggregates below survive; a re-delivered frame older than
                # the window is then counted as fresh, so gap_count and
                # dropped may be understated — never overstated.
                self.seen.clear()
            self.seen.add(frame.frame_id)
            self.unique += 1
            if self.min_seen is None or frame.frame_id < self.min_seen:
                self.min_seen = frame.frame_id
            if self.max_seen is None or frame.frame_id > self.max_seen:
                self.max_seen = frame.frame_id

        if self.last_frame_id is not None:
            if frame.frame_id < self.last_frame_id:
                self.regressions += 1
                if len(self.steps) >= self._STEPS_CAP:
                    self.steps.pop(0)
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
        """Missing frame ids implied by the observed range.

        Computed from lifetime aggregates (O(1)), so it is stable across
        duplicate-window resets with the documented caveat above: an
        out-of-window re-delivery inflates ``unique``, which can only
        *understate* the gap (never overstate it, never fabricate one).
        Callers must only invoke this on demand (diagnostics/stats),
        never per-frame on the producer path.
        """
        if self.unique == 0 or self.min_seen is None or self.max_seen is None:
            return 0
        span = (self.max_seen - self.min_seen + 1)
        return max(0, span - self.unique)


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