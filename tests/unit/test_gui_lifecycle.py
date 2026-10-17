"""Stage B3 lifecycle acceptance tests.

T-LIFE-01..08: worker shutdown, close refusal, sensor stop-before-destroy,
page-cache liveness (no stale-widget resurrection), registry identity,
authority defaults, and a single tick call site.
"""

from __future__ import annotations

import gc
import time
from pathlib import Path

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QThread
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QWidget

from ultimate_pipeline.gui.health import SessionAuthority
from ultimate_pipeline.gui.session.actor_registry import OwnedActorRegistry


@pytest.fixture
def app():
    from ultimate_pipeline.gui.shell.main_window import create_application
    return create_application([])


class _RecordingSensor:
    def __init__(self):
        self.calls: list[str] = []
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def stop(self) -> None:
        self.calls.append("stop")

    def destroy(self) -> None:
        self.calls.append("destroy")
        self.alive = False


class _StoppingThread(QThread):
    """Honors interruption, like MjpegSource."""

    def run(self) -> None:
        while not self.isInterruptionRequested():
            time.sleep(0.005)


class _StubbornThread(QThread):
    """Ignores interruption for a while, like a blocking RPC."""

    def __init__(self, hold_s: float = 1.0, parent=None) -> None:
        super().__init__(parent)
        self._hold = hold_s

    def run(self) -> None:
        time.sleep(self._hold)


class _WorkerHost(QWidget):
    def __init__(self, worker: QThread, parent=None) -> None:
        super().__init__(parent)
        self._worker = worker


# ============================================================ T-LIFE-01
def test_T_LIFE_01_stop_ui_workers_interrupts_and_waits(app):
    from ultimate_pipeline.gui.control_center.shutdown import stop_ui_workers

    worker = _StoppingThread()
    worker.start()
    pages = {"04_world_time": _WorkerHost(worker)}
    try:
        assert stop_ui_workers(pages, wait_ms=2000) is True
        assert not worker.isRunning()
    finally:
        worker.wait(2000)


# ============================================================ T-LIFE-02
def test_T_LIFE_02_stop_ui_workers_refuses_close_when_worker_will_not_die(app):
    from ultimate_pipeline.gui.control_center.shutdown import stop_ui_workers

    worker = _StubbornThread(hold_s=1.0)
    worker.start()
    pages = {"04_world_time": _WorkerHost(worker)}
    try:
        assert stop_ui_workers(pages, wait_ms=50) is False
        assert worker.isRunning()
    finally:
        worker.wait(3000)


# ============================================================ T-LIFE-03
def test_T_LIFE_03_close_event_refused_while_workers_stopping(app, tmp_path,
                                                             monkeypatch):
    from ultimate_pipeline.gui.shell.main_window import MainWindow
    from ultimate_pipeline.gui.shell.services import build_registry

    window = MainWindow(build_registry(), prefs_path=tmp_path / "ui.json")
    try:
        monkeypatch.setattr(
            "ultimate_pipeline.gui.shell.main_window.stop_ui_workers",
            lambda *a, **k: False)
        refused = QCloseEvent()
        window.closeEvent(refused)
        assert refused.isAccepted() is False

        monkeypatch.setattr(
            "ultimate_pipeline.gui.shell.main_window.stop_ui_workers",
            lambda *a, **k: True)
        allowed = QCloseEvent()
        window.closeEvent(allowed)
        assert allowed.isAccepted() is True
    finally:
        window.close()


# ============================================================ T-LIFE-04
def test_T_LIFE_04_sensor_listeners_stop_before_destroy():
    registry = OwnedActorRegistry()
    sensor = _RecordingSensor()
    registry.register(7, sensor, kind="sensor", parent_id=1)
    outcome = registry.destroy(7)
    assert outcome.ok, outcome.reason
    assert sensor.calls == ["stop", "destroy"]


def test_T_LIFE_04_stop_failure_still_destroys_but_destroy_failure_reports():
    registry = OwnedActorRegistry()

    class _StopFails(_RecordingSensor):
        def stop(self) -> None:
            self.calls.append("stop")
            raise RuntimeError("stop failed")

    sensor = _StopFails()
    registry.register(8, sensor, kind="sensor")
    assert registry.destroy(8).ok is True
    assert sensor.calls == ["stop", "destroy"]

    class _DestroyFails(_RecordingSensor):
        def destroy(self) -> None:
            self.calls.append("destroy")
            raise RuntimeError("destroy failed")

    broken = _DestroyFails()
    registry.register(9, broken, kind="sensor")
    outcome = registry.destroy(9)
    assert outcome.ok is False
    assert outcome.error_class == "RuntimeError"
    assert broken.calls == ["stop", "destroy"]


# ============================================================ T-LIFE-05
def test_T_LIFE_05_page_cache_never_resurrects_dead_widgets(app):
    from PyQt6 import sip

    from ultimate_pipeline.gui.shell.pages.runtime import runtime_page_factory
    from ultimate_pipeline.gui.shell.services import build_registry

    registry = build_registry()
    factory = runtime_page_factory("04_world_time")
    page = factory(registry)
    assert not sip.isdeleted(page)

    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, int(QEvent.Type.DeferredDelete))
    assert sip.isdeleted(page), "the C++ object must actually be gone"

    rebuilt = factory(registry)
    assert rebuilt is not page
    assert not sip.isdeleted(rebuilt)


# ============================================================ T-LIFE-06
def test_T_LIFE_06_cache_identity_holds_per_live_registry(app):
    from ultimate_pipeline.gui.shell.pages.runtime import runtime_page_factory
    from ultimate_pipeline.gui.shell.services import build_registry

    factory = runtime_page_factory("04_world_time")
    first = build_registry()
    second = build_registry()
    first_page = factory(first)
    second_page = factory(second)
    assert first_page is not second_page
    gc.collect()
    assert factory(first) is first_page
    assert factory(second) is second_page


# ============================================================ T-LIFE-07
def test_T_LIFE_07_shared_readonly_stays_the_default_everywhere():
    from ultimate_pipeline.gui.adapters.mock_backend import MockCarlaBackend
    from ultimate_pipeline.gui.session.runtime_session import RuntimeSession
    from ultimate_pipeline.gui.shell.services import build_registry

    registry = build_registry()
    assert registry.badges.session_authority == (
        SessionAuthority.SHARED_READONLY.value)
    assert RuntimeSession().authority == SessionAuthority.SHARED_READONLY.value
    backend = MockCarlaBackend()
    grant = backend.acquire_tick("b3-probe")
    assert grant.granted is False
    assert "exclusive" in grant.reason


# ============================================================ T-LIFE-08
def test_T_LIFE_08_gui_tree_has_exactly_one_world_tick_call_site():
    root = Path(__file__).resolve().parents[2] / "ultimate_pipeline" / "gui"
    hits: list[tuple[Path, int]] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        count = text.count("world.tick(")
        if count:
            hits.append((path.relative_to(root), count))
    assert hits == [(Path("session/tick_authority.py"), 1)], (
        f"expected exactly one world.tick() call site in gui/, found {hits}")


# ============================================================ T-LIFE-09
def test_T_LIFE_09_stop_ui_workers_invokes_widget_shutdown_hooks(app):
    from ultimate_pipeline.gui.control_center.shutdown import stop_ui_workers

    calls: list[str] = []

    class _HookedHost(QWidget):
        def shutdown(self) -> None:
            calls.append("shutdown")

    host = _HookedHost()
    try:
        assert stop_ui_workers({"08_sensors_streams": host},
                               wait_ms=500) is True
        assert calls == ["shutdown"], "panel shutdown hook must run exactly once"
    finally:
        host.close()


def test_T_LIFE_09_feeds_panel_is_wired_for_the_shutdown_hook(app):
    from ultimate_pipeline.gui.control_center.feeds import FeedsPanel

    panel = FeedsPanel()
    assert callable(getattr(panel, "shutdown", None))
    panel.shutdown()  # must be safe with no sensor bridge
    panel.close()


# ============================================================ T-LIFE-10
def test_T_LIFE_10_swallowed_stop_failure_recorded_as_diagnostic():
    registry = OwnedActorRegistry()

    class _StopFails(_RecordingSensor):
        def stop(self) -> None:
            self.calls.append("stop")
            raise RuntimeError("stop failed")

    sensor = _StopFails()
    registry.register(8, sensor, kind="sensor")
    outcome = registry.destroy(8)
    assert outcome.ok is True, "destroy must proceed despite stop failure"
    assert sensor.calls == ["stop", "destroy"]
    kinds = [d.kind for d in registry.diagnostics]
    assert kinds == ["SWALLOWED_EXCEPTION"]
    assert "sensor 8 stop()" in registry.diagnostics[0].subject
    assert "stop failed" in registry.diagnostics[0].detail

    report = registry.cleanup_report()
    assert report.ok is True
    assert len(report.value["diagnostics"]) == 1, (
        "cleanup evidence must carry the swallowed failure")


# ============================================================ T-LIFE-11
def test_T_LIFE_11_page_cache_evicts_dead_registries(app):
    import ultimate_pipeline.gui.shell.pages.runtime as runtime_mod
    from ultimate_pipeline.gui.shell.services import build_registry

    factory = runtime_mod.runtime_page_factory("04_world_time")
    registry = build_registry()
    factory(registry)
    key = id(registry)
    assert key in runtime_mod._PAGE_CACHE

    del registry
    gc.collect()

    factory(build_registry())  # next call prunes the dead entry
    entry = runtime_mod._PAGE_CACHE.get(key)
    assert entry is None or entry[0]() is not None, (
        "a dead registry must never pin its pages in the cache")
