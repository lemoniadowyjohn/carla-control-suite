"""Cancellation token shared by every GUI service adapter.

Blocking CARLA RPCs and long worker loops must be interruptible.  A token is
the single mechanism: services poll :meth:`CancellationToken.raise_if_cancelled`
at their own bounded checkpoints and never spin.
"""

from __future__ import annotations

import threading
from typing import Callable

__all__ = ["CancellationToken", "OperationCancelled"]


class OperationCancelled(Exception):
    """Raised when a cooperative cancellation point is reached."""


class CancellationToken:
    """Thread-safe, one-shot cancellation flag with callback support.

    Deliberately *not* an ``asyncio`` primitive: adapters run on Qt worker
    threads and on plain ``ThreadPoolExecutor`` workers alike.
    """

    __slots__ = ("_event", "_callbacks", "_reason", "_lock")

    def __init__(self) -> None:
        self._event = threading.Event()
        self._callbacks: list[Callable[[str], None]] = []
        self._reason = ""
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "operator requested cancellation") -> None:
        """Request cancellation.  Idempotent; the first reason wins."""
        with self._lock:
            if self._event.is_set():
                return
            self._reason = reason
            callbacks = list(self._callbacks)
        self._event.set()
        for callback in callbacks:
            try:
                callback(reason)
            except Exception:  # pragma: no cover - callbacks must not mask cancel
                pass

    def on_cancel(self, callback: Callable[[str], None]) -> None:
        """Register a callback.  Fires immediately if already cancelled."""
        with self._lock:
            if not self._event.is_set():
                self._callbacks.append(callback)
                return
            reason = self._reason
        callback(reason)

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OperationCancelled(self._reason or "cancelled")

    def wait(self, timeout: float | None = None) -> bool:
        """Block until cancelled or the timeout elapses. Returns the flag."""
        return self._event.wait(timeout)