"""Stage B2 acceptance tests: native sensor adapters + bounded frame pipeline.

Acceptance IDs from task-06 (BL-26/BL-41):
T-SENSOR-01..06 -- missing ID/frame, out-of-order frames, overfull queue,
sensor teardown, worker/Qt thread affinity, decimated previews.
T-THR-01..08 -- non-blocking callbacks, concurrency, close-under-load,
Qt signal affinity, bookkeeping integrity, detach under load, no Qt in the
core, and the authority gate on attach/detach.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from ultimate_pipeline.gui.adapters.mock_backend import MockCarlaBackend
from ultimate_pipeline.gui.core.sensor_bridge import SensorChannel
from ultimate_pipeline.gui.health import SessionAuthority
from ultimate_pipeline.gui.results import Result
from ultimate_pipeline.gui.sensors.queues import Frame, FrameIdMissingError
from ultimate_pipeline.gui.services.sensors import (
    SENSOR_BLUEPRINTS, UNSUPPORTED_SENSOR_TYPES, NativeSensorSpec,
    SensorService,
)

EXCLUSIVE = SessionAuthority.EXCLUSIVE_WORLD
READONLY = SessionAuthority.SHARED_READONLY


@pytest.fixture
def app():
    from ultimate_pipeline.gui.shell.main_window import create_application
    return create_application([])


class _Calibration:
    profile_id = "cal-001"


def _frame(frame_id: int, sensor_id: str = "") -> Frame:
    return Frame(frame_id=frame_id, timestamp=float(frame_id),
                 payload=b"payload", sensor_id=sensor_id)


def _service(**kwargs) -> tuple[SensorService, MockCarlaBackend]:
    backend = MockCarlaBackend()
    return SensorService(backend, **kwargs), backend


def _attach(service: SensorService, sensor_type: str = "rgb_camera") -> str:
    attachment = service.attach(sensor_type, _Calibration(), EXCLUSIVE)
    assert attachment.ok, attachment.reason
    return attachment.unwrap().sensor_id


# =========================================================== T-SENSOR-01
def test_T_SENSOR_01_frame_without_id_is_refused_at_construction():
    with pytest.raises(FrameIdMissingError):
        Frame(frame_id=None, timestamp=0.0)  # type: ignore[arg-type]


def test_T_SENSOR_01_deliver_rejects_missing_frame_and_unknown_sensor():
    service, _ = _service()
    sensor_id = _attach(service)
    assert service.deliver("sensor-unknown", _frame(1)).ok is False
    assert service.deliver(sensor_id, None).ok is False  # type: ignore[arg-type]
    wrong = _frame(2, sensor_id="sensor-other")
    assert service.deliver(sensor_id, wrong).ok is False
    assert service.deliver(sensor_id, _frame(3, sensor_id=sensor_id)).ok is True


# =========================================================== T-SENSOR-02
def test_T_SENSOR_02_out_of_order_frames_reported_not_smoothed():
    service, _ = _service()
    sensor_id = _attach(service)
    for frame_id in (1, 2, 5, 3):
        assert service.deliver(sensor_id, _frame(frame_id, sensor_id)).ok
    stats = service.stats(sensor_id)
    ordering = stats["ordering"]
    assert ordering["monotonic"] is False
    assert ordering["regressions"] == 1
    assert [5, 3] in [list(step) for step in ordering["backwards_steps"]]
    assert stats["gaps"] == 1  # frame 4 never arrived; not fabricated


# =========================================================== T-SENSOR-03
def test_T_SENSOR_03_overfull_queue_drops_oldest_and_counts():
    channel = SensorChannel("s1", "rgb_camera", maxlen=4)
    for frame_id in range(1, 11):
        result = channel.offer(_frame(frame_id, "s1"))
        assert result.ok and result.value["accepted"] is True
    stats = channel.stats()
    assert stats["pending"] == 4
    assert stats["queue"]["enqueued"] == 10
    assert stats["queue"]["dropped_oldest"] == 6
    assert stats["queue"]["dropped"] == 6


def test_T_SENSOR_03_drop_newest_mode_rejects_new_frames():
    channel = SensorChannel("s1", "rgb_camera", maxlen=2, drop="newest")
    assert channel.offer(_frame(1, "s1")).value["accepted"] is True
    assert channel.offer(_frame(2, "s1")).value["accepted"] is True
    assert channel.offer(_frame(3, "s1")).value["accepted"] is False
    assert channel.stats()["queue"]["dropped_newest"] == 1
    assert channel.stats()["pending"] == 2


# =========================================================== T-SENSOR-04
def test_T_SENSOR_04_detach_closes_channel_before_backend_destroy():
    service, backend = _service()
    sensor_id = _attach(service)
    service.deliver(sensor_id, _frame(1, sensor_id))
    result = service.detach(sensor_id, EXCLUSIVE)
    assert result.ok, result.reason
    assert result.value["channel"]["closed"] is True
    assert service.channel(sensor_id) is None
    assert sensor_id not in backend.owned_sensor_ids()
    after = service.deliver(sensor_id, _frame(2, sensor_id))
    assert after.ok is False
    assert after.error_class == "KeyError"


def test_T_SENSOR_04_detach_refused_under_shared_readonly():
    service, backend = _service()
    sensor_id = _attach(service)
    blocked = service.detach(sensor_id, READONLY)
    assert blocked.ok is False
    assert blocked.error_class == "AuthorityRequired"
    assert service.channel(sensor_id) is not None
    assert sensor_id in backend.owned_sensor_ids()
    assert service.channel(sensor_id).closed is False


# =========================================================== T-SENSOR-05
def test_T_SENSOR_05_worker_publishes_to_frame_ingress_on_gui_thread(app):
    from PyQt6.QtCore import QThread
    from PyQt6.QtGui import QImage

    from ultimate_pipeline.gui.control_center.feeds import FrameIngress

    service, _ = _service(preview_decimation=1)
    sensor_id = _attach(service)
    ingress = FrameIngress()
    seen: list[tuple[str, int, threading.Thread]] = []
    ingress.frame_received.connect(
        lambda sid, image, fid, ts: seen.append(
            (sid, fid, QThread.currentThread())))

    delivered = 4
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for frame_id in range(1, delivered + 1):
                service.deliver(sensor_id, _frame(frame_id, sensor_id))
                for preview in service.poll_preview(sensor_id, limit=8).unwrap():
                    image = QImage(1, 1, QImage.Format.Format_RGB888)
                    ingress.publish(sensor_id, image,
                                    preview.frame_id, preview.timestamp)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    thread = threading.Thread(target=worker, name="b2-frame-worker")
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive(), "worker thread hung"
    assert not errors, errors
    app.processEvents()

    assert [fid for _, fid, _ in seen] == [1, 2, 3, 4]
    main_thread = app.thread()
    assert all(t == main_thread for _, _, t in seen), (
        "frames must be delivered to the GUI thread via the Qt signal")


# =========================================================== T-SENSOR-06
def test_T_SENSOR_06_preview_decimation_never_carries_full_rate():
    channel = SensorChannel("s1", "lidar", maxlen=64, preview_decimation=4)
    for frame_id in range(1, 9):
        channel.offer(_frame(frame_id, "s1"))
    previews = channel.poll_preview(limit=8)
    assert [p.frame_id for p in previews] == [4, 8]
    assert channel.stats()["preview_emitted"] == 2
    assert channel.stats()["queue"]["enqueued"] == 8


# ============================================================= T-THR-01
def test_T_THR_01_producer_never_blocks_when_consumer_is_absent():
    channel = SensorChannel("s1", "rgb_camera", maxlen=32)
    total = 5000
    started = time.perf_counter()
    for frame_id in range(total):
        channel.offer(_frame(frame_id % 1000, "s1"))
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0, f"producer path took {elapsed:.2f}s; it must never block"
    stats = channel.stats()
    assert stats["queue"]["enqueued"] == total
    assert stats["pending"] <= 32
    assert stats["queue"]["dropped"] == total - 32


# ============================================================= T-THR-02
def test_T_THR_02_concurrent_offer_and_poll_keep_consistent_stats():
    channel = SensorChannel("s1", "rgb_camera", maxlen=128,
                            preview_decimation=1)
    total = 1000
    stop = threading.Event()
    errors: list[BaseException] = []

    def producer() -> None:
        try:
            for frame_id in range(1, total + 1):
                channel.offer(_frame(frame_id, "s1"))
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    def consumer() -> None:
        try:
            while not stop.is_set() or channel.pending() > 0:
                channel.poll_preview(limit=16)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    consumer_thread = threading.Thread(target=consumer)
    producer_thread = threading.Thread(target=producer)
    consumer_thread.start()
    producer_thread.start()
    producer_thread.join(timeout=15)
    assert not producer_thread.is_alive()
    stop.set()
    consumer_thread.join(timeout=15)
    assert not consumer_thread.is_alive()
    assert not errors, errors

    stats = channel.stats()
    assert stats["queue"]["enqueued"] == total
    assert stats["pending"] == 0
    # drop-oldest invariant: every enqueued frame was delivered or dropped
    assert stats["queue"]["enqueued"] == (
        stats["queue"]["delivered"] + stats["queue"]["dropped_oldest"])
    assert stats["ordering"]["monotonic"] is True
    assert stats["ordering"]["regressions"] == 0
    assert stats["gaps"] == 0


# ============================================================= T-THR-03
def test_T_THR_03_close_during_producer_load_never_deadlocks():
    channel = SensorChannel("s1", "rgb_camera", maxlen=64)
    failures: list[Result] = []
    errors: list[BaseException] = []

    def producer() -> None:
        try:
            for frame_id in range(10_000):
                result = channel.offer(_frame(frame_id, "s1"))
                if not result.ok:
                    failures.append(result)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    thread = threading.Thread(target=producer)
    thread.start()
    time.sleep(0.02)
    closed = channel.close()
    thread.join(timeout=15)
    assert not thread.is_alive(), "producer hung on close"
    assert not errors, errors
    assert closed["closed"] is True
    if failures:
        assert all(f.error_class == "SensorChannelClosed" for f in failures)
    assert channel.closed is True
    assert channel.offer(_frame(99_999, "s1")).ok is False


# ============================================================= T-THR-04
def test_T_THR_04_frame_ingress_publish_from_foreign_thread_dispatches_to_gui(app):
    from PyQt6.QtCore import QThread
    from PyQt6.QtGui import QImage

    from ultimate_pipeline.gui.control_center.feeds import FrameIngress

    ingress = FrameIngress()
    seen: list[threading.Thread] = []
    ingress.frame_received.connect(
        lambda sid, image, fid, ts: seen.append(QThread.currentThread()))

    thread = threading.Thread(
        target=lambda: ingress.publish("s", QImage(1, 1,
                                                   QImage.Format.Format_RGB888),
                                       1, 0.0))
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive()
    app.processEvents()
    assert seen == [app.thread()]


# ============================================================= T-THR-05
def test_T_THR_05_concurrent_deliver_through_service_is_thread_safe():
    service, _ = _service()
    sensor_id = _attach(service)
    threads_n, per_thread = 4, 250
    errors: list[BaseException] = []

    def worker(base: int) -> None:
        try:
            for i in range(per_thread):
                result = service.deliver(sensor_id, _frame(base + i, sensor_id))
                assert result.ok, result.reason
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n * per_thread,))
               for n in range(threads_n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    assert not errors, errors
    stats = service.stats(sensor_id)
    assert stats["queue"]["enqueued"] == threads_n * per_thread
    assert stats["pending"] == 64  # bounded default; overflow dropped oldest
    assert stats["queue"]["dropped_oldest"] == threads_n * per_thread - 64


# ============================================================= T-THR-06
def test_T_THR_06_detach_while_producers_run_is_safe():
    service, backend = _service()
    sensor_id = _attach(service)
    stop = threading.Event()
    errors: list[BaseException] = []

    def producer() -> None:
        frame_id = 0
        try:
            while not stop.is_set():
                frame_id += 1
                service.deliver(sensor_id, _frame(frame_id, sensor_id))
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=producer) for _ in range(2)]
    for thread in threads:
        thread.start()
    time.sleep(0.02)
    result = service.detach(sensor_id, EXCLUSIVE)
    stop.set()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    assert not errors, errors
    assert result.ok, result.reason
    assert sensor_id not in backend.owned_sensor_ids()
    assert service.channel(sensor_id) is None


# ============================================================= T-THR-07
def test_T_THR_07_bridge_and_service_sources_import_no_qt():
    root = Path(__file__).resolve().parents[2] / "ultimate_pipeline" / "gui"
    for rel in ("core/sensor_bridge.py", "services/sensors.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "PyQt" not in text, f"{rel} must stay Qt-free"


# ============================================================= T-THR-08
def test_T_THR_08_attach_refused_without_exclusive_authority():
    service, backend = _service()
    blocked = service.attach("rgb_camera", _Calibration(), READONLY)
    assert blocked.ok is False
    assert blocked.error_class == "AuthorityRequired"
    assert backend.owned_sensor_ids() == ()
    assert service.sensor_ids() == ()


def test_T_THR_08_unsupported_types_refused_even_with_exclusive_authority():
    service, _ = _service()
    for sensor_type in ("radar", "gnss", "imu"):
        result = service.attach(sensor_type, _Calibration(), EXCLUSIVE)
        assert result.ok is False, sensor_type
        assert result.error_class == "UnsupportedSensorError"


# ============================================================ truthfulness
def test_supported_types_declares_five_native_and_three_unsupported():
    service, _ = _service()
    declaration = service.supported_types()
    assert declaration["native"] == sorted(SENSOR_BLUEPRINTS)
    assert set(declaration["native"]) == {
        "rgb_camera", "depth_camera", "semantic_segmentation",
        "instance_segmentation", "lidar"}
    assert set(declaration["unsupported"]) == {"radar", "gnss", "imu"}
    for name, entry in declaration["unsupported"].items():
        assert entry["reason"], name
        assert entry["source"], name
    assert declaration["source_class"] == "MOCK_BACKEND"
    assert set(UNSUPPORTED_SENSOR_TYPES) == {"radar", "gnss", "imu"}


def test_attachments_carry_source_class_and_blueprint():
    service, _ = _service()
    sensor_id = _attach(service, "lidar")
    attachment = service.attachment(sensor_id)
    assert attachment.source_class == "MOCK_BACKEND"
    assert attachment.blueprint == "sensor.lidar.ray_cast"
    assert attachment.calibration_id == "cal-001"
    assert isinstance(attachment.channel, SensorChannel)


def test_native_sensor_specs_match_carla_0_9_16_blueprints():
    assert SENSOR_BLUEPRINTS == {
        "rgb_camera": "sensor.camera.rgb",
        "depth_camera": "sensor.camera.depth",
        "semantic_segmentation": "sensor.camera.semantic_segmentation",
        "instance_segmentation": "sensor.camera.instance_segmentation",
        "lidar": "sensor.lidar.ray_cast",
    }
    spec = NativeSensorSpec("rgb_camera", SENSOR_BLUEPRINTS["rgb_camera"])
    assert spec.blueprint == "sensor.camera.rgb"


def test_mock_backend_detach_is_fail_closed_for_unknown_sensor():
    backend = MockCarlaBackend()
    unknown = backend.detach_sensor("sensor-404")
    assert unknown.ok is False
    assert unknown.error_class == "RuntimeError"
    bound = backend.attach_sensor(
        NativeSensorSpec("rgb_camera", "sensor.camera.rgb"), _Calibration())
    sensor_id = bound.unwrap().sensor_id
    assert backend.detach_sensor(sensor_id).ok is True
    assert backend.detach_sensor(sensor_id).ok is False  # second detach fails
    assert backend.cleanup() == []


def test_service_requires_source_class_and_unknown_type_fails_closed():
    with pytest.raises(ValueError):
        SensorService(MockCarlaBackend(), source_class="")
    service, _ = _service()
    result = service.attach("magnetometer", _Calibration(), EXCLUSIVE)
    assert result.ok is False
    assert result.error_class == "KeyError"
    assert "radar" in result.remediation


def test_sensors_service_registered_in_build_registry():
    from ultimate_pipeline.gui.shell.services import build_registry
    registry = build_registry()
    assert registry.available("sensors")
    service = registry.resolve("sensors")
    assert service.source_class == "MOCK_BACKEND"
    assert registry.source_of("sensors") == (
        "ultimate_pipeline/gui/services/sensors.py")


# =========================================================== T-SENSOR-07
def test_T_SENSOR_07_malformed_timestamp_refused_not_defaulted():
    from ultimate_pipeline.gui.sensors.queues import FrameTimestampError

    for bad in (None, "not-a-time", float("nan"), float("inf")):
        with pytest.raises(FrameTimestampError):
            Frame(frame_id=1, timestamp=bad)  # type: ignore[arg-type]
    assert Frame(frame_id=1, timestamp=1).timestamp == 1


# =========================================================== T-SENSOR-08
class _ExplodingBackend(MockCarlaBackend):
    def __init__(self) -> None:
        super().__init__()
        self.explode_on_attach = False
        self.explode_on_detach = False

    def attach_sensor(self, spec, calibration):
        if self.explode_on_attach:
            raise RuntimeError("adapter exploded during attach")
        return super().attach_sensor(spec, calibration)

    def detach_sensor(self, sensor_id):
        if self.explode_on_detach:
            raise RuntimeError("adapter exploded during detach")
        return super().detach_sensor(sensor_id)


def test_T_SENSOR_08_backend_exceptions_become_results_not_crashes():
    backend = _ExplodingBackend()
    service = SensorService(backend)

    backend.explode_on_attach = True
    failed = service.attach("rgb_camera", _Calibration(), EXCLUSIVE)
    assert failed.ok is False and failed.error_class == "RuntimeError"
    assert service.sensor_ids() == ()
    assert backend.owned_sensor_ids() == ()

    backend.explode_on_attach = False
    sensor_id = _attach(service)

    backend.explode_on_detach = True
    failed = service.detach(sensor_id, EXCLUSIVE)
    assert failed.ok is False and failed.error_class == "RuntimeError"
    # zombie, not orphan: still registered, channel closed, retryable
    assert sensor_id in service.sensor_ids()
    assert service.channel(sensor_id) is not None
    assert service.channel(sensor_id).closed is True

    backend.explode_on_detach = False
    retried = service.detach(sensor_id, EXCLUSIVE)
    assert retried.ok, retried.reason
    assert service.sensor_ids() == ()
    assert sensor_id not in backend.owned_sensor_ids()


def test_T_SENSOR_08b_backend_refused_detach_keeps_registration():
    service, backend = _service()
    sensor_id = _attach(service)
    # force a backend refusal by asking the backend twice underneath service
    assert backend.detach_sensor(sensor_id).ok is True
    result = service.detach(sensor_id, EXCLUSIVE)
    assert result.ok is False
    assert sensor_id in service.sensor_ids()
    assert service.channel(sensor_id).closed is True


# =========================================================== T-SENSOR-09
def test_T_SENSOR_09_invalidate_all_closes_everything_with_evidence():
    service, backend = _service()
    one = _attach(service, "rgb_camera")
    two = _attach(service, "depth_camera")
    service.deliver(one, _frame(1, one))

    outcome = service.invalidate_all("MAP_LOAD", source="test")
    assert outcome.ok, outcome.reason
    value = outcome.value
    assert value["reason"] == "MAP_LOAD"
    assert value["invalidated"] == sorted([one, two])
    assert value["backend_failures"] == {}
    assert value["closed"][one]["closed"] is True
    assert service.sensor_ids() == ()
    assert service.channel(one) is None
    assert backend.owned_sensor_ids() == ()
    assert backend.cleanup() == []

    again = service.invalidate_all("SHUTDOWN")
    assert again.ok and again.value["invalidated"] == []


# =========================================================== T-SENSOR-10
def test_T_SENSOR_10_live_carla_source_requires_backend_attestation():
    with pytest.raises(ValueError):
        SensorService(MockCarlaBackend(), source_class="LIVE_CARLA")

    class _AttestedBackend(MockCarlaBackend):
        def live_attestation(self) -> dict:
            return {"rpc": "127.0.0.1:2000", "verified": True}

    service = SensorService(_AttestedBackend(), source_class="LIVE_CARLA")
    assert service.source_class == "LIVE_CARLA"


# =========================================================== T-SENSOR-11
def test_T_SENSOR_11_bookkeeping_window_bounded_gaps_survive_resets():
    from ultimate_pipeline.gui.sensors.queues import FrameBookkeeping

    book = FrameBookkeeping(sensor_id="s", seen_cap=8)
    ids = [1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13]  # frame 4 never arrived
    for frame_id in ids:
        book.observe(Frame(frame_id=frame_id, timestamp=float(frame_id)))
    assert len(book.seen) <= 8, "recent-id window must stay bounded"
    assert book.gap_count() == 1
    assert book.unique == len(ids)

    book.observe(Frame(frame_id=13, timestamp=13.0))  # in-window duplicate
    assert book.dropped == 1
    assert book.gap_count() == 1  # duplicates never fabricate a gap

    for frame_id in range(14, 40):
        book.observe(Frame(frame_id=frame_id, timestamp=float(frame_id)))
    assert len(book.seen) <= 8, "window resets must not grow memory"
    assert book.gap_count() == 1, "hole at 4 survives window resets"


# ============================================================= T-THR-09
def test_T_THR_09_offer_path_stays_linear_at_high_frame_counts():
    channel = SensorChannel("s1", "rgb_camera", maxlen=64)
    total = 20000
    started = time.perf_counter()
    for frame_id in range(total):
        assert channel.offer(_frame(frame_id, "s1")).ok
    elapsed = time.perf_counter() - started
    # Quadratic bookkeeping measured 8.83s at 20k frames (reviewer evidence);
    # the linear producer path must stay far below that.
    assert elapsed < 3.0, (
        f"offer path took {elapsed:.2f}s for {total} frames; "
        "gap work must not run per-frame")


# ============================================================= T-THR-10
def test_T_THR_10_stats_concurrent_with_offer_never_deadlocks():
    channel = SensorChannel("s1", "rgb_camera", maxlen=128,
                            preview_decimation=1)
    stop = threading.Event()
    errors: list[BaseException] = []

    def producer() -> None:
        frame_id = 0
        try:
            while not stop.is_set():
                frame_id += 1
                channel.offer(_frame(frame_id, "s1"))
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=producer) for _ in range(2)]
    for thread in threads:
        thread.start()
    deadline = time.perf_counter() + 1.0
    while time.perf_counter() < deadline:
        channel.stats()  # must never invert the channel->stats lock order
    stop.set()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    assert not errors, errors
    assert channel.stats()["queue"]["enqueued"] > 0


# =========================================================== T-SENSOR-12
def test_T_SENSOR_12_post_spawn_setup_failure_rolls_back():
    service, backend = _service()
    failed = service.attach("rgb_camera", _Calibration(), EXCLUSIVE,
                            queue_len=-1)  # reaches SensorChannel -> raises
    assert failed.ok is False
    assert failed.error_class == "ValueError"
    assert "rolled back via backend detach_sensor" in failed.remediation
    assert service.sensor_ids() == ()
    assert backend.owned_sensor_ids() == ()
    assert backend.cleanup() == []


def test_T_SENSOR_12_malformed_binding_fails_honestly():
    class _MalformedBackend(MockCarlaBackend):
        def attach_sensor(self, spec, calibration):
            super().attach_sensor(spec, calibration)  # spawns for real

            class _Binding:
                sensor_id = ""  # unusable: we cannot name what spawned
                calibration_id = ""

            return Result.success(_Binding())

    backend = _MalformedBackend()
    service = SensorService(backend)
    failed = service.attach("rgb_camera", _Calibration(), EXCLUSIVE)
    assert failed.ok is False
    assert "no usable sensor_id" in failed.reason
    assert "may retain the spawn" in failed.remediation
    assert service.sensor_ids() == ()
