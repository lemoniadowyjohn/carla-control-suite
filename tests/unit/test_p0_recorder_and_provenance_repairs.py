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


def test_p0_4_map_sha_is_the_provenance_authority():
    """A pinned expected XODR SHA must be the authority that is enforced.

    This is the part of the provenance contract that is verified: a wrong
    expected SHA is refused outright, and when tiles DO declare manifests the
    pinned SHA is compared against their recorded source SHA.
    """
    import hashlib
    import tempfile
    from pathlib import Path

    from ultimate_pipeline.tiling.large_map_package import stage_large_map_package

    tmp = Path(tempfile.mkdtemp())
    xodr = tmp / "map.xodr"
    xodr.write_text("A", encoding="utf-8")
    real_sha = hashlib.sha256(xodr.read_bytes()).hexdigest()
    tile = tmp / "Ingolstadt_Tile_0_0.fbx"
    tile.write_bytes(b"fake")

    # Correct SHA, synthetic fixture with no tile manifests: the documented
    # opt-out applies and staging succeeds.
    ok = stage_large_map_package(
        map_name="Ingolstadt",
        xodr_path=str(xodr),
        tile_fbx_paths=[str(tile)],
        import_root=str(tmp / "Import_ok"),
        expected_xodr_sha256=real_sha,
    )
    assert ok.status == "ok", ok.reason

    # Wrong SHA must be refused regardless of manifests.
    bad = stage_large_map_package(
        map_name="Ingolstadt",
        xodr_path=str(xodr),
        tile_fbx_paths=[str(tile)],
        import_root=str(tmp / "Import_bad"),
        expected_xodr_sha256="0" * 64,
    )
    assert bad.status == "failed"
    assert "sha256 mismatch" in bad.reason


def test_p0_4_synthetic_fixture_opt_out_is_documented_and_preserved():
    """The no-manifest opt-out is a committed contract, not an oversight.

    tests/unit/test_o1_cook_provenance_chain.py asserts that tiles with no
    manifests may be staged when the XODR check itself passes. P0-4's
    reconstruction initially broke that, so this test pins the contract so a
    future tightening has to confront it deliberately.
    """
    import ultimate_pipeline.tiling.large_map_package as lmp

    source = inspect.getsource(lmp.stage_large_map_package)
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert "strict_provenance = has_any_manifest" in code, (
        "per-tile provenance must stay keyed on whether tiles declare manifests; "
        "forcing it on a no-manifest caller breaks the committed synthetic-fixture "
        "contract in test_o1_cook_provenance_chain.py"
    )


def test_p0_4_reconstruction_is_not_asserted_as_complete():
    """The original P0-4 diff was lost and could not be recovered.

    Recorded explicitly so the gap is not silently forgotten: if the true P0-4
    tightened provenance via the expected SHA, this reconstruction does not
    implement it and the original must be restored.
    """
    import ultimate_pipeline.tiling.large_map_package as lmp

    source = inspect.getsource(lmp.stage_large_map_package)
    assert "P0-4 status: NOT VERIFIED" in source, (
        "the unverified state of the P0-4 reconstruction must stay recorded in "
        "the code until the original diff is recovered"
    )


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
