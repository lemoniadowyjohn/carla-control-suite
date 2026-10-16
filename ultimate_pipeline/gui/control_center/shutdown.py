"""Bounded shutdown for background map/RPC/MJPEG tasks."""
from __future__ import annotations

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QWidget


def stop_ui_workers(operator_pages: dict, wait_ms: int = 10000) -> bool:
    """Ask workers to stop; prevent Qt teardown while an active QThread remains."""
    workers: dict[int, QThread] = {}
    for workspace in operator_pages.values():
        for widget in (workspace, *workspace.findChildren(QWidget)):
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
            return False
    return True
