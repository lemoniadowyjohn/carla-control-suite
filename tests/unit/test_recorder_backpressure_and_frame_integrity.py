# -*- coding: utf-8 -*-
"""Adversarial tests for recorder backpressure, drain and frame integrity.

Covers finding A (writer backpressure visibility), B (genuinely bounded writer
teardown), C (exact callback frame-id authority) and the artifact-to-frame
binding rules.

Every CARLA object is a duck-typed double. No server is contacted and none of
these tests asserts live behaviour.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from ultimate_pipeline.sensors.recorder import (
    CAPTURE_FRAME_ARTIFACT_MISMATCH,
    CAPTURE_FRAME_DROP,
    WRITER_DRAIN_FAILURE,
    WRITER_DRAIN_PASS,
    WRITER_DRAIN_TIMEOUT,
    RecorderConfig,
    SensorRecorder,
)


# ===========================================================================
# doubles
# ===========================================================================


class _FakeWorld:
    """Minimal world double: enough for start()/stop(), no tick side effects."""

    def get_snapshot(self):
        return None

    def tick(self, timeout=None):
        return 0

    def get_settings(self):
        class S:
            synchronous_mode = False

        return S()


class _Recorder(SensorRecorder):
    """Recorder wired to doubles, with no world tick side effects."""

    def _flush_post_stop_tick(self):
        return None


class _RgbData:
    """Duck-typed carla.Image for the plain camera writer."""

    def __init__(self, frame: int):
        self.frame = frame
        self.width = 2
        self.height = 2

    def save_to_disk(self, path: str) -> None:
        Path(path).write_bytes(b"\x89PNG-fake-rgb")


class _SemsegData(_RgbData):
    """Duck-typed carla.Image carrying a BGRA buffer for the semseg writer."""

    def __init__(self, frame: int, payload: int = 7):
        super().__init__(frame)
        self.raw_data = bytes([payload] * (self.width * self.height * 4))


class _BadFrameData:
    """Sensor data whose .frame is not an integer (P0-2 malformed-frame case)."""

    def __init__(self, frame=None):
        self.frame = frame


class _FakeSensor:
    def __init__(
        self,
        actor_id: int = 1,
        type_id: str = "sensor.camera.semantic_segmentation",
    ):
        self.id = actor_id
        self.type_id = type_id
        self._callback = None
        self._stopped = False

    def listen(self, callback):
        self._callback = callback

    def stop(self):
        self._stopped = True

    def emit(self, data):
        if self._callback is not None:
            self._callback(data)


def _make(tmp_path: Path, **cfg_kwargs) -> _Recorder:
    sensor = _FakeSensor()
    rec = _Recorder(
        world=_FakeWorld(),
        sensors={"semseg_front": sensor},
        output_dir=str(tmp_path),
        config=RecorderConfig(**cfg_kwargs),
    )
    rec.start()
    return rec


def _wait_for_executing(rec: _Recorder, minimum: int = 1, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if rec.backpressure_report()["write_jobs_executing"] >= minimum:
            return True
        time.sleep(0.01)
    return False


# ===========================================================================
# A. backpressure accounting
# ===========================================================================


def test_backpressure_report_exposes_required_fields(tmp_path):
    rec = _make(tmp_path)
    sensor = rec.sensors["semseg_front"]
    for frame in (1, 2, 3):
        sensor.emit(_SemsegData(frame))

    report = rec.backpressure_report()
    for field in (
        "queue_capacity",
        "queue_high_water_mark",
        "write_jobs_pending",
        "write_jobs_completed",
        "write_jobs_failed",
        "frames_dropped",
    ):
        assert field in report, field
    assert report["callback_frame_ids"]["semseg_front"] == [1, 2, 3]
    rec.join_writer_threads(timeout_s=5.0)


def test_writer_saturation_records_drop_and_fails_strict_capture(tmp_path):
    """Reduced capacity + a slowed writer => queue fills => strict capture FAIL."""
    gate = threading.Event()
    rec = _make(
        tmp_path,
        writer_queue_capacity=1,
        writer_max_workers=1,
        strict=True,
        required_sensors=("semseg_front",),
        require_frame_correspondence=True,
        require_artifact_frame_binding=True,
    )
    original = rec._write_semseg_frame

    def slow_write(data, *, out_path, viz_path=None):
        gate.wait(timeout=10.0)
        original(data, out_path=out_path, viz_path=viz_path)

    rec._write_semseg_frame = slow_write
    sensor = rec.sensors["semseg_front"]

    # Frame 1 occupies the single slot and blocks inside the writer.
    sensor.emit(_SemsegData(1))
    assert _wait_for_executing(rec), "writer never started"

    # Frames 2..5 cannot be accepted: capacity is exhausted.
    for frame in (2, 3, 4, 5):
        sensor.emit(_SemsegData(frame))

    report = rec.backpressure_report()
    assert report["frames_dropped"] > 0, "saturation must be visible as drops"
    assert report["write_dropped_frame_ids"]["semseg_front"], (
        "dropped frame ids must be recorded per sensor"
    )
    # The callback frames are still recorded: the sensor DID deliver them.
    assert report["callback_frame_ids"]["semseg_front"] == [1, 2, 3, 4, 5]

    gate.set()
    verdict = rec.close()
    assert verdict["valid"] is False
    assert CAPTURE_FRAME_DROP in verdict["invalid_reasons"]
    assert verdict["backpressure"]["frames_dropped"] > 0


def test_dropped_frame_is_not_hidden_by_file_counts(tmp_path):
    """A dropped frame invalidates the capture even though files were written."""
    rec = _make(
        tmp_path,
        writer_queue_capacity=1,
        writer_max_workers=1,
        strict=True,
        required_sensors=("semseg_front",),
    )
    gate = threading.Event()
    original = rec._write_semseg_frame

    def blocking_write(data, *, out_path, viz_path=None):
        gate.wait(timeout=10.0)
        original(data, out_path=out_path, viz_path=viz_path)

    rec._write_semseg_frame = blocking_write
    sensor = rec.sensors["semseg_front"]
    sensor.emit(_SemsegData(1))
    assert _wait_for_executing(rec)
    sensor.emit(_SemsegData(2))
    gate.set()

    verdict = rec.close()
    assert verdict["valid"] is False
    assert CAPTURE_FRAME_DROP in verdict["invalid_reasons"]
    assert "aggregate file counts are not used" in verdict["verdict_basis"]


def test_write_failure_is_accounted(tmp_path):
    rec = _make(tmp_path, strict=True, required_sensors=("semseg_front",))

    def exploding_write(data, *, out_path, viz_path=None):
        raise OSError("disk_full")

    rec._write_semseg_frame = exploding_write
    rec.sensors["semseg_front"].emit(_SemsegData(1))

    verdict = rec.close()
    assert verdict["valid"] is False
    assert verdict["backpressure"]["write_jobs_failed"] >= 1
    assert verdict["backpressure"]["write_failed_frame_ids"]["semseg_front"] == [1]


# ===========================================================================
# B. bounded drain
# ===========================================================================


def test_drain_returns_pass_when_writer_finishes(tmp_path):
    rec = _make(tmp_path)
    rec.sensors["semseg_front"].emit(_SemsegData(1))
    drain = rec.join_writer_threads(timeout_s=5.0)
    assert drain["state"] == WRITER_DRAIN_PASS
    assert drain["capture_complete"] is True
    assert drain["pending_frame_count"] == 0


def test_drain_timeout_is_real_not_indefinite(tmp_path):
    """A writer that blocks longer than the timeout must return, not hang."""
    rec = _make(tmp_path, writer_queue_capacity=4, writer_max_workers=1)
    gate = threading.Event()
    original = rec._write_semseg_frame

    def hanging_write(data, *, out_path, viz_path=None):
        gate.wait(timeout=30.0)
        original(data, out_path=out_path, viz_path=viz_path)

    rec._write_semseg_frame = hanging_write
    rec.sensors["semseg_front"].emit(_SemsegData(1))
    assert _wait_for_executing(rec)

    started = time.monotonic()
    drain = rec.join_writer_threads(timeout_s=0.5)
    elapsed = time.monotonic() - started

    assert drain["state"] == WRITER_DRAIN_TIMEOUT
    assert drain["capture_complete"] is False
    assert elapsed < 5.0, f"drain ignored its timeout (took {elapsed:.2f}s)"
    assert drain["timeout_s"] == 0.5
    assert drain["pending_frame_ids_by_sensor"]["semseg_front"] == [1]
    assert drain["write_jobs_executing"] >= 1
    gate.set()


def test_drain_timeout_quarantines_output(tmp_path):
    rec = _make(tmp_path, writer_queue_capacity=4, writer_max_workers=1)
    gate = threading.Event()
    original = rec._write_semseg_frame

    def hanging_write(data, *, out_path, viz_path=None):
        gate.wait(timeout=30.0)
        original(data, out_path=out_path, viz_path=viz_path)

    rec._write_semseg_frame = hanging_write
    rec.sensors["semseg_front"].emit(_SemsegData(1))
    assert _wait_for_executing(rec)

    drain = rec.join_writer_threads(timeout_s=0.4)
    assert drain["state"] == WRITER_DRAIN_TIMEOUT

    marker = tmp_path / "DRAIN_INCOMPLETE.json"
    assert marker.is_file(), "an undrained capture must be quarantined on disk"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["capture_complete"] is False
    assert payload["invalid_reason"] == WRITER_DRAIN_TIMEOUT
    assert payload["pending_frame_ids_by_sensor"]["semseg_front"] == [1]
    gate.set()


def test_drain_stops_accepting_new_callbacks(tmp_path):
    rec = _make(tmp_path, writer_queue_capacity=4, writer_max_workers=1)
    gate = threading.Event()
    original = rec._write_semseg_frame

    def hanging_write(data, *, out_path, viz_path=None):
        gate.wait(timeout=30.0)
        original(data, out_path=out_path, viz_path=viz_path)

    rec._write_semseg_frame = hanging_write
    rec.sensors["semseg_front"].emit(_SemsegData(1))
    assert _wait_for_executing(rec)

    rec.join_writer_threads(timeout_s=0.3)
    assert rec.backpressure_report()["accepting_callbacks"] is False

    accepted = rec._queue_write_job(
        sensor_name="semseg_front",
        sensor_kind="rgb",
        frame_id=99,
        write_fn=lambda: None,
    )
    assert accepted is False
    assert 99 in rec.backpressure_report()["write_dropped_frame_ids"]["semseg_front"]
    gate.set()


def test_drain_failure_state_is_representable(tmp_path):
    rec = _make(tmp_path)

    class _BrokenExecutor:
        def shutdown(self, *args, **kwargs):
            raise RuntimeError("executor_poisoned")

    rec._executor = _BrokenExecutor()
    drain = rec.join_writer_threads(timeout_s=0.2)
    assert drain["state"] == WRITER_DRAIN_FAILURE
    assert drain["capture_complete"] is False


def test_timeout_is_not_a_lie_in_source():
    """Structural guard: the timeout must not be discarded."""
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(SensorRecorder.join_writer_threads))
    tree = ast.parse(source)
    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef)

    # Strip the docstring: it documents the old defect by name.
    docstring_nodes = [
        n
        for n in ast.walk(func)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    docstring_ids = {id(n) for n in docstring_nodes}

    del_names = [
        n
        for n in ast.walk(func)
        if isinstance(n, ast.Delete)
        for t in n.targets
        if isinstance(t, ast.Name) and t.id == "timeout_s"
    ]
    assert not del_names, (
        "join_writer_threads deletes its timeout parameter, so the bound is a lie"
    )

    # The timeout must actually reach a clock comparison.
    uses_monotonic = any(
        isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "time"
        and n.attr == "monotonic"
        for n in ast.walk(func)
        if id(n) not in docstring_ids
    )
    assert uses_monotonic, "the drain must poll against a real deadline"

    # shutdown must not block: wait=True would restore the old unbounded wait.
    blocks_on_shutdown = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "shutdown"
        and any(
            kw.arg == "wait" and isinstance(kw.value, ast.Constant) and kw.value.value is True
            for kw in n.keywords
        )
        for n in ast.walk(func)
    )
    assert not blocks_on_shutdown, (
        "executor.shutdown(wait=True) blocks until every job finishes, which is "
        "the unbounded wait this method is supposed to replace"
    )

    # Cancelling accepted work would silently drop frames, so it must be absent.
    cancels_accepted_work = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "shutdown"
        and any(
            kw.arg == "cancel_futures"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in n.keywords
        )
        for n in ast.walk(func)
    )
    assert not cancels_accepted_work, (
        "queued writer jobs are accepted frames; cancel_futures would discard "
        "frames the recorder already promised to write"
    )


# ===========================================================================
# C. exact frame-id authority
# ===========================================================================


def test_frame_correspondence_uses_callback_frame_ids(tmp_path):
    camera = _FakeSensor(1, "sensor.camera.rgb")
    lidar = _FakeSensor(2, "sensor.lidar.ray_cast")
    rec = _Recorder(
        world=_FakeWorld(),
        sensors={"rgb_front": camera, "lidar": lidar},
        output_dir=str(tmp_path),
        config=RecorderConfig(),
    )
    rec.start()
    for frame in (10, 11, 12):
        camera.emit(_RgbData(frame))

    corr = rec.frame_correspondence()
    assert corr["schema"] == "FRAME_CORRESPONDENCE/v1"
    assert corr["per_sensor_frame_ids"]["rgb_front"] == [10, 11, 12]
    assert corr["per_sensor_frame_ids"]["lidar"] == []
    assert corr["common_frame_ids"] == []
    assert corr["common_frame_count"] == 0
    rec.join_writer_threads(timeout_s=5.0)


def test_cross_sensor_mismatched_frames_detected(tmp_path):
    """Equal frame COUNTS over disjoint ids are not synchronised."""
    camera = _FakeSensor(1, "sensor.camera.rgb")
    lidar = _FakeSensor(2, "sensor.lidar.ray_cast")
    rec = _Recorder(
        world=_FakeWorld(),
        sensors={"rgb_front": camera, "lidar": lidar},
        output_dir=str(tmp_path),
        config=RecorderConfig(
            strict=True,
            require_frame_correspondence=True,
            required_sensors=("rgb_front", "lidar"),
        ),
    )
    rec.start()
    for frame in (1, 2, 3):
        camera.emit(_RgbData(frame))
    for frame in (2, 3, 4):
        lidar.emit(_RgbData(frame))

    corr = rec.frame_correspondence()
    assert len(corr["per_sensor_frame_ids"]["rgb_front"]) == 3
    assert len(corr["per_sensor_frame_ids"]["lidar"]) == 3
    assert corr["common_frame_ids"] == [2, 3]
    assert corr["first_common_frame"] == 2
    assert corr["last_common_frame"] == 3
    assert corr["extra_by_sensor"]["rgb_front"] == [1]
    assert corr["extra_by_sensor"]["lidar"] == [4]
    rec.join_writer_threads(timeout_s=5.0)


def test_disjoint_frame_ranges_produce_no_common_frames(tmp_path):
    camera = _FakeSensor(1, "sensor.camera.rgb")
    lidar = _FakeSensor(2, "sensor.lidar.ray_cast")
    rec = _Recorder(
        world=_FakeWorld(),
        sensors={"rgb_front": camera, "lidar": lidar},
        output_dir=str(tmp_path),
        config=RecorderConfig(
            strict=True,
            require_frame_correspondence=True,
            required_sensors=("rgb_front", "lidar"),
        ),
    )
    rec.start()
    for frame in (1, 2, 3):
        camera.emit(_RgbData(frame))
    for frame in (101, 102, 103):
        lidar.emit(_RgbData(frame))

    corr = rec.frame_correspondence()
    assert corr["common_frame_count"] == 0

    verdict = rec.final_report(drain={"state": WRITER_DRAIN_PASS})
    assert verdict["valid"] is False
    assert any("no_common_frames" in r for r in verdict["invalid_reasons"])


def test_duplicate_callback_frame_is_recorded(tmp_path):
    rec = _make(tmp_path, strict=True, required_sensors=("semseg_front",))
    sensor = rec.sensors["semseg_front"]
    sensor.emit(_SemsegData(1))
    sensor.emit(_SemsegData(1))  # duplicate delivery
    sensor.emit(_SemsegData(2))

    report = rec.backpressure_report()
    assert report["duplicate_frame_ids"]["semseg_front"] == [1]
    assert report["callback_frame_ids"]["semseg_front"] == [1, 2]

    verdict = rec.final_report(drain={"state": WRITER_DRAIN_PASS})
    assert verdict["valid"] is False
    assert any("duplicate_frames" in r for r in verdict["invalid_reasons"])
    rec.join_writer_threads(timeout_s=5.0)


def test_malformed_callback_frame_does_not_leak_counter(tmp_path):
    rec = _make(tmp_path, strict=True, required_sensors=("semseg_front",))
    sensor = rec.sensors["semseg_front"]
    for bad in (None, "12", 3.5, object()):
        sensor.emit(_BadFrameData(bad))

    assert rec._callbacks_in_flight == 0
    assert any("save_failed:semseg_front" in e for e in rec.get_save_errors_tail(50))
    assert rec.backpressure_report()["callback_frame_ids"].get("semseg_front", []) == []
    rec.join_writer_threads(timeout_s=5.0)


def test_sensor_with_no_frames_fails_strict_capture(tmp_path):
    rec = _make(tmp_path, strict=True, required_sensors=("semseg_front",))
    verdict = rec.final_report(drain={"state": WRITER_DRAIN_PASS})
    assert verdict["valid"] is False
    assert any("no_frames" in r for r in verdict["invalid_reasons"])


def test_frame_correspondence_artifact_written(tmp_path):
    rec = _make(tmp_path)
    rec.sensors["semseg_front"].emit(_SemsegData(5))
    path = rec.write_frame_correspondence_artifact()
    assert path.name == "FRAME_CORRESPONDENCE.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for field in (
        "per_sensor_frame_ids",
        "common_frame_ids",
        "missing_by_sensor",
        "extra_by_sensor",
        "duplicates_by_sensor",
        "first_common_frame",
        "last_common_frame",
        "common_frame_count",
    ):
        assert field in payload, field
    rec.join_writer_threads(timeout_s=5.0)


# ===========================================================================
# 5. artifact <-> callback frame binding
# ===========================================================================


def test_artifact_is_bound_to_callback_frame(tmp_path):
    rec = _make(tmp_path, strict=True, required_sensors=("semseg_front",))
    rec.sensors["semseg_front"].emit(_SemsegData(42))
    rec.join_writer_threads(timeout_s=5.0)

    artifacts = rec._artifact_report()["artifacts"]
    record = artifacts["semseg_front"]["42"]
    assert record["callback_frame_id"] == 42
    assert record["filename_frame_id"] == 42
    assert record["filename_matches_callback_frame_id"] is True
    assert record["write_status"] == "WRITTEN"
    assert record["output_sha256"]
    assert record["sensor_actor_id"] == 1
    assert Path(record["output_path"]).name == "00000042.png"


def test_filename_rewritten_to_another_frame_invalidates(tmp_path):
    rec = _make(tmp_path, strict=True, required_sensors=("semseg_front",))
    original = rec._write_semseg_frame

    def wrong_name(data, *, out_path, viz_path=None):
        # Substitutes a different frame's filename AND reports it, so the
        # binding must follow the real write rather than the request.
        substituted = out_path.with_name("00000099.png")
        original(data, out_path=substituted, viz_path=viz_path)
        return substituted

    rec._write_semseg_frame = wrong_name
    rec.sensors["semseg_front"].emit(_SemsegData(7))
    rec.join_writer_threads(timeout_s=5.0)

    report = rec._artifact_report()
    assert report["filename_frame_id_mismatches"], "rewritten filename must be detected"
    verdict = rec.final_report(drain={"state": WRITER_DRAIN_PASS})
    assert verdict["valid"] is False
    assert CAPTURE_FRAME_ARTIFACT_MISMATCH in verdict["invalid_reasons"]


def test_duplicate_file_for_same_sensor_and_frame_invalidates(tmp_path):
    rec = _make(tmp_path, strict=True, required_sensors=("semseg_front",))
    rec.sensors["semseg_front"].emit(_SemsegData(3))
    rec.join_writer_threads(timeout_s=5.0)
    rec._bind_artifact(
        sensor_name="semseg_front",
        sensor_kind="rgb",
        callback_frame_id=3,
        output_path=rec._output_path("semseg_front", "rgb", 3, "png"),
        write_status="WRITTEN",
        sensor=rec.sensors["semseg_front"],
    )

    report = rec._artifact_report()
    assert report["duplicate_artifacts_by_sensor"]["semseg_front"] == [3]
    verdict = rec.final_report(drain={"state": WRITER_DRAIN_PASS})
    assert verdict["valid"] is False
    assert any("duplicate_files" in r for r in verdict["invalid_reasons"])


def test_file_present_without_callback_receipt(tmp_path):
    rec = _make(tmp_path, strict=True, required_sensors=("semseg_front",))
    path = rec._output_path("semseg_front", "rgb", 11, "png")
    path.write_bytes(b"orphan")
    rec._bind_artifact(
        sensor_name="semseg_front",
        sensor_kind="rgb",
        callback_frame_id=11,
        output_path=path,
        write_status="FAILED",
        sensor=rec.sensors["semseg_front"],
    )
    with rec._lock:
        rec._write_completed_frame_ids.setdefault("semseg_front", []).append(11)

    report = rec._artifact_report()
    assert report["file_without_callback_receipt"], "orphan artifact must be reported"
    assert rec.final_report(drain={"state": WRITER_DRAIN_PASS})["valid"] is False


def test_callback_receipt_without_file(tmp_path):
    rec = _make(tmp_path, strict=True, required_sensors=("semseg_front",))
    with rec._lock:
        rec._write_completed_frame_ids.setdefault("semseg_front", []).append(21)
        rec._sensor_frame_counts["semseg_front"] = 1

    report = rec._artifact_report()
    assert report["callback_receipt_without_file"] == [
        {"sensor_name": "semseg_front", "callback_frame_id": 21}
    ]
    verdict = rec.final_report(drain={"state": WRITER_DRAIN_PASS})
    assert verdict["valid"] is False
    assert any("receipt_without_file" in r for r in verdict["invalid_reasons"])


def test_camera_frame_n_with_lidar_n_plus_one_is_not_synchronised(tmp_path):
    camera = _FakeSensor(1, "sensor.camera.rgb")
    lidar = _FakeSensor(2, "sensor.lidar.ray_cast")
    rec = _Recorder(
        world=_FakeWorld(),
        sensors={"rgb_front": camera, "lidar": lidar},
        output_dir=str(tmp_path),
        config=RecorderConfig(
            strict=True,
            require_frame_correspondence=True,
            required_sensors=("rgb_front", "lidar"),
        ),
    )
    rec.start()
    for n in (5, 6):
        camera.emit(_RgbData(n))
        lidar.emit(_RgbData(n + 1))  # one frame ahead

    corr = rec.frame_correspondence()
    assert corr["per_sensor_frame_ids"]["rgb_front"] == [5, 6]
    assert corr["per_sensor_frame_ids"]["lidar"] == [6, 7]
    # The intersection is only frame 6; equal counts (2 and 2) prove nothing.
    assert corr["common_frame_ids"] == [6]
    assert corr["common_frame_count"] == 1
    rec.join_writer_threads(timeout_s=5.0)
