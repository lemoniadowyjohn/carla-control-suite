"""Bounded worker execution and debouncing for the Qt shell.

Two guarantees the acceptance tests check directly:

* **No widget mutation off the main thread.** A worker returns a value; the
  caller applies it on the GUI thread via a Qt signal. The worker has no
  reference to any widget.
* **Bounded and cancellable.** A worker queue has a fixed depth, a submitting
  thread is never blocked indefinitely, and every job carries a
  ``CancellationToken`` so a superseded job can stop without touching a widget.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from ultimate_pipeline.gui.cancellation import CancellationToken, OperationCancelled
from ultimate_pipeline.gui.results import Result

__all__ = ["JobHandle", "WorkerPool", "Debouncer"]


@dataclass
class JobHandle:
    """A submitted job. Holds a result, never a widget."""

    job_id: str
    token: CancellationToken = field(default_factory=CancellationToken)
    future: Future | None = None

    def cancel(self, reason: str = "superseded by a newer request") -> None:
        self.token.cancel(reason)

    @property
    def cancelled(self) -> bool:
        return self.token.cancelled


class WorkerPool:
    """A deliberately tiny, bounded worker pool for UI reads only.

    Concurrency is capped at one by default so a UI read storm cannot compete
    with the simulator thread that the runtime services own.
    """

    def __init__(self, *, max_workers: int = 1, queue_depth: int = 32) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self.max_workers = int(max_workers)
        self.queue_depth = max(1, int(queue_depth))
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="carla-gui")
        self._lock = threading.Lock()
        self._counter = 0
        self._in_flight = 0
        self.rejected = 0

    @staticmethod
    def _captures_widget(work: Callable) -> str | None:
        """Refuse a callable that can reach a Qt widget or QObject.

        The docstring alone cannot stop ``lambda t: self.table.setItem(...)``.
        Qt widgets must only be touched on the GUI thread, so any widget
        reachable from the callable -- through a closure cell *or* through the
        module globals its free variables bind to -- is rejected at submission.
        """
        try:
            from PyQt6.QtCore import QObject
        except ImportError:  # pragma: no cover - Qt is a hard dependency here
            return None

        found: list[str] = []

        def check(value: Any) -> None:
            try:
                if isinstance(value, QObject):
                    found.append(type(value).__name__)
            except TypeError:
                pass

        for cell in (getattr(work, "__closure__", None) or ()):
            try:
                check(cell.cell_contents)
            except ValueError:
                continue
        # A name bound in the module namespace (not a closure cell) still lets
        # the callable mutate a widget, so globals are checked too.
        code = getattr(work, "__code__", None)
        globals_map = getattr(work, "__globals__", {}) or {}
        # co_freevars: names bound as closure cells. co_names: module globals
        # the callable dereferences. Both can hand a widget to the worker.
        referenced = list(getattr(code, "co_freevars", ()) or ()) + \
            list(getattr(code, "co_names", ()) or ())
        for name in referenced:
            if name in globals_map:
                check(globals_map[name])
        return found[0] if found else None

    def submit(self, work: Callable[[CancellationToken], Any], *,
               allow_widget_capture: bool = False) -> JobHandle:
        """Submit a read-only callable. It must not touch a widget.

        Set ``allow_widget_capture`` only for a genuinely non-UI callable; the
        default refuses any closure holding a QObject.
        """
        if not allow_widget_capture:
            offender = self._captures_widget(work)
            if offender is not None:
                raise TypeError(
                    f"refusing to submit a worker that captures a Qt object "
                    f"({offender}); widgets may only be mutated on the GUI thread")
        with self._lock:
            if self._in_flight >= self.queue_depth:
                # Bounded: refuse rather than grow without limit.
                self._counter += 1
                self.rejected += 1
                raise RuntimeError(
                    f"worker queue is full ({self.queue_depth}); submission refused")
            self._counter += 1
            job_id = f"job-{self._counter}"
            self._in_flight += 1

        handle = JobHandle(job_id)

        def runner() -> Result:
            try:
                handle.token.raise_if_cancelled()
                value = work(handle.token)
                handle.token.raise_if_cancelled()
                return Result.success(value)
            except OperationCancelled:
                return Result.blocked("job cancelled")
            except Exception as exc:
                return Result.failure(f"{type(exc).__name__}: {exc}",
                                      error_class=type(exc).__name__,
                                      error_source=getattr(work, "__module__", ""),
                                      state_restored=None)
            finally:
                with self._lock:
                    self._in_flight -= 1

        try:
            handle.future = self._executor.submit(runner)
        except Exception:
            # The executor refused (e.g. after shutdown); do not leak the slot.
            with self._lock:
                self._in_flight -= 1
                self.rejected += 1
            raise
        return handle

    @staticmethod
    def result_of(handle: JobHandle, timeout: float | None = None) -> Result:
        """Collect a result. Safe to call from the GUI thread."""
        if handle.future is None:
            return Result.blocked("job was never submitted")
        try:
            return handle.future.result(timeout=timeout)
        except Exception as exc:
            return Result.failure(f"job failed: {exc}", error_class=type(exc).__name__)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def stats(self) -> dict:
        return {"submitted": self._counter, "in_flight": self._in_flight,
                "rejected": self.rejected, "queue_depth": self.queue_depth,
                "max_workers": self.max_workers}


class Debouncer:
    """Coalesce rapid input (search boxes) into one later call.

    Implemented with a monotonic deadline rather than a Qt timer so the
    behaviour is testable without a running event loop.
    """

    def __init__(self, delay_ms: int = 250,
                 clock: Callable[[], float] | None = None) -> None:
        import time
        self.delay_ms = int(delay_ms)
        self._clock = clock or time.monotonic
        self._last = None
        self._pending = None

    def push(self, value: Any) -> bool:
        """Record input. Returns True when the debounce window has elapsed."""
        self._pending = value
        now = self._clock()
        if self._last is None or (now - self._last) * 1000.0 >= self.delay_ms:
            self._last = now
            return True
        return False

    @property
    def pending(self) -> Any:
        return self._pending

    def flush(self) -> Any:
        """Emit the pending value immediately (used on focus-out / Enter)."""
        self._last = self._clock()
        value, self._pending = self._pending, None
        return value