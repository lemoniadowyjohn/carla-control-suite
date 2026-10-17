"""Bounded shutdown for background map/RPC/MJPEG tasks."""
from __future__ import annotations

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QWidget


def stop_ui_workers(operator_pages: dict, wait_ms: int = 10000) -> bool:
    """Ask workers to stop; prevent Qt teardown while an active QThread remains.

    Panels exposing a zero-argument ``shutdown()`` method are duck-typed and
    called **only after every worker has stopped** (a normal Python call,
    never a destructor hook). A *refused* close therefore never runs panel
    shutdown hooks, so a window that stays open keeps its timers, streams
    and sensor attachments fully intact. A widget already deleted mid-
    teardown (RuntimeError) is tolerated.
    """
    workers: dict[int, QThread] = {}
    hooks: list = []
    for workspace in operator_pages.values():
        for widget in (workspace, *workspace.findChildren(QWidget)):
            hook = getattr(widget, "shutdown", None)
            if callable(hook):
                hooks.append(hook)
            streams = getattr(widget, "_streams", None)
            if isinstance(streams, dict):
                for worker in streams.values():
                    if isinstance(worker, QThread):
                        workers[id(worker)] = worker
            worker = getattr(widget, "_worker", None)
            if isinstance(worker, QThread):
                workers[id(worker)] = worker
    for worker in workers.values():
        if worker.isRunning():
            worker.requestInterruption()
    for worker in workers.values():
        if worker.isRunning() and not worker.wait(wait_ms):
            return False  # refused: hooks must NOT run, state stays intact
    for hook in hooks:
        try:
            hook()
        except RuntimeError:
            pass  # widget already deleted during teardown
    return True
