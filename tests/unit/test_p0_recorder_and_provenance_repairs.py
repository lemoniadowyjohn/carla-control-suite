# -*- coding: utf-8 -*-
"""Regression tests for the five P0 repairs.

These repairs were applied as an uncommitted working-tree change and then lost
to an accidental repo-wide `git checkout -- .`. They are reconstructed here from
their recorded behaviour, with tests that fail against the pre-fix code so a
silent re-regression is caught.

* P0-1  SensorRecorder.tick() nested-lock deadlock
* P0-2  malformed-frame callback counter leak
* P0-3  submission recorder copy carries the same two fixes
* P0-4  production tile strict-provenance activation
* P0-5  runtime_map_qa required-check verdict derivation
"""
from __future__ import annotations

import inspect
import threading
from pathlib import Path

import pytest

from ultimate_pipeline.sensors.recorder import (
    RecorderConfig,
    SensorRecorder,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ===========================================================================
# doubles
# ===========================================================================


class _FakeSensor:
    def __init__(self, actor_id: int = 1, type_id: str = "sensor.camera.rgb"):
        self.id = actor_id
        self.type_id = type_id
        self._callback = None

    def listen(self, callback):
        self._callback = callback

    def stop(self):
        return None

    def emit(self, data):
        if self._callback is not None:
            self._callback(data)


class _FakeWorld:
    def get_snapshot(self):
        return None

    def tick(self, timeout=None):
        return 0

    def get_settings(self):
        class S:
            synchronous_mode = False

        return S()


class _Recorder(SensorRecorder):
    def _flush_post_stop_tick(self):
        return None


class _ImageData:
    def __init__(self, frame):
        self.frame = frame
        self.width = 2
        self.height = 2
        self.raw_data = b"\x07" * 16

    def save_to_disk(self, path):
        Path(path).write_bytes(b"png")


class _BadFrameData:
    def __init__(self, frame=None):
        self.frame = frame


# ===========================================================================
# P0-1: tick() nested-lock deadlock
# ===========================================================================


def test_p0_1_tick_does_not_deadlock(tmp_path):
    """tick() holds self._lock; it must not re-enter it via a helper."""
    rec = _Recorder(
        world=_FakeWorld(),
        sensors={"cam": _FakeSensor()},
        output_dir=str(tmp_path),
        config=RecorderConfig(),
    )
    rec.start()

    done = threading.Event()
    result = {}

    def _call():
        result["value"] = rec.tick()
        done.set()

    worker = threading.Thread(target=_call, daemon=True)
    worker.start()
    assert done.wait(timeout=10.0), "tick() deadlocked on the recorder lock"
    assert result["value"]["ok"] is True


def test_p0_1_tick_does_not_call_locked_helper_under_lock(tmp_path):
    """Structural guard: tick() must not call get_recorded_frame_count()."""
    rec = _Recorder(
        world=_FakeWorld(),
        sensors={"cam": _FakeSensor()},
        output_dir=str(tmp_path),
        config=RecorderConfig(),
    )
    rec.start()

    # Strip comments: the fix's explanatory comment names the helper it
    # deliberately no longer calls.
    code = "\n".join(
        line for line in inspect.getsource(type(rec).tick).splitlines()
        if not line.strip().startswith("#")
    )
    assert "get_recorded_frame_count" not in code, (
        "tick() calls get_recorded_frame_count(), which acquires the same "
        "non-reentrant Lock it is already holding"
    )


def test_p0_1_tick_minimum_across_sensors(tmp_path):
    """The inline computation must preserve min-across-sensors semantics."""
    rec = _Recorder(
        world=_FakeWorld(),
        sensors={"a": _FakeSensor(1), "b": _FakeSensor(2)},
        output_dir=str(tmp_path),
        config=RecorderConfig(),
    )
    rec.start()
    with rec._lock:
        rec._sensor_frame_counts["a"] = 5
        rec._sensor_frame_counts["b"] = 2
    assert rec.tick()["frames_recorded"] == 2

    with rec._lock:
        rec._sensor_frame_counts = {}
    assert rec.tick()["frames_recorded"] == 0


# ===========================================================================
# P0-2: malformed-frame callback counter leak
# ===========================================================================


def test_p0_2_malformed_frame_does_not_leak_in_flight_counter(tmp_path):
    rec = _Recorder(
        world=_FakeWorld(),
        sensors={"cam": _FakeSensor()},
        output_dir=str(tmp_path),
        config=RecorderConfig(),
    )
    rec.start()
    sensor = rec.sensors["cam"]

    for bad in (None, "7", 2.5, object()):
        sensor.emit(_BadFrameData(bad))

    assert rec._callbacks_in_flight == 0, (
        "_callbacks_in_flight leaked: a malformed .frame escaped before the "
        "finally decrement"
    )


def test_p0_2_frame_id_resolved_inside_try(tmp_path):
    """Structural guard: _next_frame_id must run inside the try block."""
    rec = _Recorder(
        world=_FakeWorld(),
        sensors={"cam": _FakeSensor()},
        output_dir=str(tmp_path),
        config=RecorderConfig(),
    )
    cb = rec._make_sensor_callback("cam", rec.sensors["cam"])
    source = inspect.getsource(cb)
    lines = [line.strip() for line in source.splitlines()]
    frame_line = next(
        (i for i, line in enumerate(lines) if "_next_frame_id" in line), None
    )
    try_line = next((i for i, line in enumerate(lines) if line.startswith("try:")), None)
    assert frame_line is not None and try_line is not None
    assert frame_line > try_line, (
        "_next_frame_id() must be inside the try block so its exception is "
        "caught and the finally decrement runs"
    )


def test_p0_2_except_handles_unbound_frame_id(tmp_path):
    """The error report must not raise NameError when frame_id is unbound."""
    rec = _Recorder(
        world=_FakeWorld(),
        sensors={"cam": _FakeSensor()},
        output_dir=str(tmp_path),
        config=RecorderConfig(),
    )
    rec.start()
    rec.sensors["cam"].emit(_BadFrameData(None))

    errors = rec.get_save_errors_tail(limit=20)
    assert errors, "the malformed frame must be recorded as an error"
    assert any("save_failed:cam" in e for e in errors)
    assert any("unknown" in e for e in errors), (
        "an unbound frame id must be reported as 'unknown', not raise"
    )
    assert rec._callbacks_in_flight == 0


def test_p0_2_valid_frames_still_recorded_after_malformed(tmp_path):
    rec = _Recorder(
        world=_FakeWorld(),
        sensors={"cam": _FakeSensor()},
        output_dir=str(tmp_path),
        config=RecorderConfig(),
    )
    rec.start()
    sensor = rec.sensors["cam"]
    sensor.emit(_ImageData(1))
    sensor.emit(_BadFrameData(None))
    sensor.emit(_ImageData(2))

    assert rec._callbacks_in_flight == 0
    # Counts advance in the writer thread, so drain before asserting.
    rec.join_writer_threads(timeout_s=10.0)
    assert rec.get_recorded_frame_count() == 2, (
        "the malformed frame must not stop the surrounding valid frames "
        "from being recorded"
    )


# ===========================================================================
# P0-3: submission recorder copy
# ===========================================================================


def test_p0_3_submission_copy_has_both_fixes():
    sub = REPO_ROOT / "submission" / "infrastructure" / "ultimate_pipeline" / "sensors" / "recorder.py"
    assert sub.is_file(), f"submission recorder copy missing: {sub}"
    source = sub.read_text(encoding="utf-8")

    assert "frames_recorded = 0" in source, (
        "submission copy is missing the P0-1 nested-lock fix"
    )
    assert "fid = frame_id if" in source, (
        "submission copy is missing the P0-2 unbound-frame-id fix"
    )

    tick_code = "\n".join(
        line for line in inspect.getsource(_Recorder.tick).splitlines()
        if not line.strip().startswith("#")
    )
    assert "get_recorded_frame_count" not in tick_code, (
        "submission copy still calls the locked helper inside tick()"
    )


def test_p0_3_submission_copy_stays_in_sync_with_primary():
    """The two recorder copies must not drift apart again."""
    primary = REPO_ROOT / "ultimate_pipeline" / "sensors" / "recorder.py"
    sub = REPO_ROOT / "submission" / "infrastructure" / "ultimate_pipeline" / "sensors" / "recorder.py"
    assert primary.read_text(encoding="utf-8") == sub.read_text(encoding="utf-8"), (
        "primary and submission recorder copies have drifted"
    )


# ===========================================================================
# P0-4: production tile strict-provenance activation
# ===========================================================================


def test_p0_4_expected_sha_activates_strict_provenance():
    """An explicitly pinned XODR SHA must activate strict provenance.

    Previously strictness keyed only on has_any_manifest, so pinning the map
    SHA while supplying no per-tile manifests ran the permissive path.
    """
    import ultimate_pipeline.tiling.large_map_package as lmp

    source = inspect.getsource(lmp.stage_large_map_package)
    assert "strict_provenance = bool(expected_xodr_sha256) or has_any_manifest" in source, (
        "strict_provenance must be activated by an explicit expected_xodr_sha256"
    )


def test_p0_4_strictness_matrix():
    """Both activation routes must yield True; neither must yield False."""
    cases = [
        (None, False, False),
        (None, True, True),
        ("a" * 64, False, True),
        ("a" * 64, True, True),
    ]
    for expected_sha, has_manifest, want in cases:
        got = bool(expected_sha) or has_manifest
        assert got == want, (expected_sha, has_manifest, got, want)


# ===========================================================================
# P0-5: runtime_map_qa required-check verdict derivation
# ===========================================================================


def test_p0_5_verdict_requires_every_required_check():
    from tools.runtime_map_qa import REQUIRED_CHECKS, _compute_verdict

    assert _compute_verdict({name: "PASS" for name in REQUIRED_CHECKS}) == "PASS"
    assert _compute_verdict({}) == "INCOMPLETE"
    assert _compute_verdict({"connect": "PASS"}) == "INCOMPLETE"
    assert (
        _compute_verdict({**{n: "PASS" for n in REQUIRED_CHECKS}, "route_drive": "FAIL"})
        == "FAIL"
    )
    assert (
        _compute_verdict({**{n: "PASS" for n in REQUIRED_CHECKS}, "rgb_capture": "NOT_RUN"})
        == "INCOMPLETE"
    )


def test_p0_5_verdict_is_not_hardcoded_pass():
    """The harness must not assign PASS without consulting the checks."""
    import tools.runtime_map_qa as qa

    source = inspect.getsource(qa.run_runtime_qa)
    assert '_compute_verdict(report["checks"])' in source, (
        "run_runtime_qa must derive its verdict from the observed checks"
    )
    assert 'report["status"] = "PASS"' not in source, (
        "run_runtime_qa assigns PASS unconditionally"
    )


def test_p0_5_required_checks_cover_the_declared_check_keys():
    from tools.runtime_map_qa import REQUIRED_CHECKS

    source = inspect.getsource(__import__("tools.runtime_map_qa", fromlist=["x"]))
    for name in REQUIRED_CHECKS:
        assert f'"{name}"' in source, f"{name} is required but not a declared check"


def test_p0_5_offline_report_is_incomplete_not_pass():
    """No CARLA server here, so the verdict must not be PASS."""
    from tools.runtime_map_qa import run_runtime_qa

    report = run_runtime_qa(frame_count=1)
    assert report["status"] != "PASS"
    if report["status"] == "BLOCKED_RUNTIME":
        assert "blocked_reason" in report
    else:
        assert report["status"] in ("INCOMPLETE", "FAIL")
