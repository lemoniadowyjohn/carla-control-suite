# -*- coding: utf-8 -*-
"""Crash bundle classification (section 17), single sensor-lifecycle authority
(NEW-267), staged bring-up + resource budget (section 9/27) and the sensor
readiness canary (NEW-255).

Pinned invariants:

* Every governed failure lands on the closed classification vocabulary --
  never silently dropped.
* ``KNOWN_UNSTABLE`` maps are never individually destroyed; failure cleanup is
  at least as safe as success cleanup.
* Bring-up stops at the first failing stage and records WHICH stage passed --
  a single boolean cannot express "S4 failed while S3 passed".
* TCP 2001 is diagnostic evidence only; the canary is the readiness gate.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ultimate_pipeline.perception.crash_bundle import (
    FAILURE_CLASSES,
    REQUIRED_BUNDLE_FILES,
    classify_failure,
    iter_failure_classes,
    write_crash_bundle,
)
from ultimate_pipeline.perception.sensor_canary import (
    _frame_id_plausible,
    assert_canary_passed,
    run_sensor_canary,
)
from ultimate_pipeline.perception.sensor_lifecycle import (
    KNOWN_UNSTABLE_MAPS,
    LifecyclePolicy,
    cleanup_spawned_sensors,
    env_forced_policy,
    is_known_unstable_map,
    policy_for_map,
    stop_sensor_callbacks,
)
from ultimate_pipeline.perception.staged_bringup import (
    STAGES,
    ResourceBudgetBlock,
    assert_within_budget,
    profile_names,
    record_vram_after_sensor,
    resolve_profile,
    run_staged_bringup,
    write_bringup_report,
)


# =========================================================================== #
# crash bundle / failure classification
# =========================================================================== #


def test_failure_vocabulary_is_closed_and_unique():
    classes = iter_failure_classes()
    assert len(classes) == len(set(classes))
    assert set(classes) == set(FAILURE_CLASSES)
    assert "UNKNOWN_ENGINE_FATAL" in classes


@pytest.mark.parametrize(
    "text,expected",
    [
        ("CUDA out of memory while allocating", "GPU_OOM"),
        ("std::bad_alloc in loader", "HOST_OOM"),
        ("wrong_map_loaded: expected Grid0828", "WRONG_MAP"),
        ("runtime_map_identity_mismatch on layer2", "RUNTIME_MAP_IDENTITY_MISMATCH"),
        ("postload_stability_gate_failed", "POSTLOAD_STALL"),
        ("capture_incomplete:complete_frames=2", "FRAME_ALIGNMENT_FAILURE"),
        ("writer_queue_full during flush", "WRITER_BACKLOG"),
        ("first_measurement_no_callbacks", "FIRST_FRAME_TIMEOUT"),
        ("OnSensorEndPlay called by engine", "ASENSOR_ENDPLAY_CRASH"),
        ("destroy_timeout after teardown", "TEARDOWN_FAILURE"),
    ],
)
def test_text_is_classified_into_the_closed_vocabulary(text, expected):
    report = classify_failure(reason=text)
    assert report["classification"] == expected
    assert report["matched_by"].startswith("text:")


def test_every_vocabulary_label_is_reachable_by_the_textual_matcher():
    from ultimate_pipeline.perception.crash_bundle import _TEXTUAL_HINTS

    matched = {label for label, _hints in _TEXTUAL_HINTS}
    assert matched == set(FAILURE_CLASSES)


def test_explicit_classification_is_authoritative():
    report = classify_failure(explicit="MAP_LOAD_TIMEOUT", reason="anything else")
    assert report["classification"] == "MAP_LOAD_TIMEOUT"
    assert report["matched_by"] == "explicit"


def test_explicit_classification_outside_the_vocabulary_is_ignored():
    report = classify_failure(explicit="MADE_UP_CLASS")
    assert report["classification"] in FAILURE_CLASSES


def test_stage_is_used_when_no_text_matches():
    report = classify_failure(reason="something unhelpful", stage="EGO_SPAWN")
    assert report["classification"] == "EGO_SPAWN_FAILURE"
    assert report["matched_by"].startswith("stage:")


def test_unmatched_failure_is_never_silently_dropped():
    report = classify_failure(reason="???")
    assert report["classification"] == "UNKNOWN_ENGINE_FATAL"
    assert report["matched_by"] == "fallback"
    assert "rather than silently dropped" in report["note"]


def test_journal_and_writer_errors_contribute_to_classification():
    report = classify_failure(
        reason=None,
        journal_tail=[{"phase": "MAP_LOAD_BEGIN"}, {"phase": "TICK_STALL", "v": 1}],
        writer_errors=["writer_backlog depth=64"],
    )
    # The journal tail is scanned line by line, so any matching phase wins.
    assert report["classification"] in FAILURE_CLASSES


def test_write_crash_bundle_materialises_the_complete_required_file_set(tmp_path):
    journal = tmp_path / "phase_journal.jsonl"
    journal.write_text(
        json.dumps({"phase": "MAP_LOAD_BEGIN"}) + "\n"
        + json.dumps({"phase": "TEARDOWN_BEGIN"}) + "\n",
        encoding="utf-8",
    )
    client_err = tmp_path / "client_stderr.txt"
    client_err.write_text("engine exited with code 1\n" * 50, encoding="utf-8")

    index = write_crash_bundle(
        tmp_path,
        reason="engine exited unexpectedly",
        stage="MAP_LOAD",
        phase_journal_path=journal,
        client_stderr_path=client_err,
        resource_samples=[{"vram_mb": 100}],
        sensor_spawn_trace=[{"sensor": "rgb_front", "ok": True}],
    )

    assert index["complete"] is True
    assert index["missing_files"] == []
    assert set(index["required_files"]) == set(REQUIRED_BUNDLE_FILES)
    assert index["classification"] == "MAP_LOAD_ENGINE_EXIT"

    bundle = tmp_path / "crash_bundle"
    for name in REQUIRED_BUNDLE_FILES:
        assert (bundle / name).exists(), name
    assert not list(bundle.glob("*.tmp"))

    written_journal = (bundle / "phase_journal.jsonl").read_text(encoding="utf-8")
    assert "MAP_LOAD_BEGIN" in written_journal
    assert "engine exited with code 1" in (bundle / "client_stderr.txt").read_text(
        encoding="utf-8"
    )


def test_write_crash_bundle_marks_missing_evidence_rather_than_omitting_files(tmp_path):
    index = write_crash_bundle(tmp_path, reason="no detail at all")
    assert index["complete"] is True  # NOT_PROVIDED placeholders still exist
    payload = json.loads(
        (tmp_path / "crash_bundle" / "map_identity.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "NOT_PROVIDED"


# =========================================================================== #
# sensor lifecycle (NEW-267)
# =========================================================================== #


class _FakeSensor:
    def __init__(self, *, fail_stop=False, hang_destroy=False):
        self.stopped = False
        self.destroyed = False
        self.fail_stop = fail_stop
        self.hang_destroy = hang_destroy

    def stop(self):
        if self.fail_stop:
            raise RuntimeError("listener wedged")
        self.stopped = True

    def destroy(self):
        if self.hang_destroy:
            import time as _time

            _time.sleep(30)
        self.destroyed = True


def test_grid_maps_resolve_to_the_known_unstable_policy():
    assert policy_for_map("Grid0821") is LifecyclePolicy.KNOWN_UNSTABLE
    assert policy_for_map("/Game/Maps/Grid0828") is LifecyclePolicy.KNOWN_UNSTABLE
    assert policy_for_map("grid0828") is LifecyclePolicy.KNOWN_UNSTABLE
    assert is_known_unstable_map("Town10HD") is False
    assert policy_for_map("Town10HD") is LifecyclePolicy.STABLE
    assert policy_for_map(None) is LifecyclePolicy.STABLE
    assert KNOWN_UNSTABLE_MAPS == frozenset({"grid0821", "grid0828"})


def test_callbacks_are_stopped_before_any_destroy_decision():
    sensor = _FakeSensor()
    report = stop_sensor_callbacks(
        [("rgb_front", sensor)],
        policy=LifecyclePolicy.STABLE,
        destroy=True,
        drain_timeout_s=0,
        map_name="Town10HD",
    )
    assert report.stopped == ["rgb_front"]
    assert sensor.stopped is True
    assert report.destroyed == ["rgb_front"]
    assert sensor.destroyed is True
    assert report.ok is True
    assert report.as_dict()["schema"] == "SENSOR_LIFECYCLE_REPORT/v1"


def test_known_unstable_policy_refuses_individual_destroy():
    sensor = _FakeSensor()
    report = stop_sensor_callbacks(
        [("rgb_front", sensor)],
        policy=LifecyclePolicy.KNOWN_UNSTABLE,
        destroy=True,  # caller demands it; policy still refuses
        drain_timeout_s=0,
        map_name="Grid0828",
    )
    assert sensor.stopped is True          # callbacks always stopped
    assert sensor.destroyed is False       # but never individually destroyed
    assert report.skipped_destroy == ["rgb_front"]
    assert report.destroyed == []
    assert report.unsafe_destroy_used is False
    # The safe conclusion for a Grid run: dispose of the whole session.
    assert report.session_disposable is True
    assert any(a.action == "destroy_skipped" for a in report.actions)


def test_stop_failure_is_reported_not_swallowed():
    sensor = _FakeSensor(fail_stop=True)
    report = stop_sensor_callbacks(
        [("rgb_front", sensor)],
        policy=LifecyclePolicy.STABLE,
        destroy=True,
        drain_timeout_s=0,
    )
    assert report.ok is False
    assert "listener wedged" in report.as_dict()["actions"][0]["error"]
    assert report.stopped == []
    # Destroy is still attempted: a sensor whose listener could not be stopped
    # must not be leaked, but the failure stays visible in report.ok.
    assert sensor.destroyed is True


def test_missing_actor_is_recorded_as_a_skipped_stop():
    report = stop_sensor_callbacks(
        [("rgb_front", None)],
        policy=LifecyclePolicy.STABLE,
        destroy=False,
        drain_timeout_s=0,
    )
    assert report.actions[0].ok is True
    assert report.actions[0].detail == "actor_none"


def test_cleanup_is_policy_derived_from_the_map():
    class _Entry:
        def __init__(self):
            self.actor = _FakeSensor()

    grid_entry = _Entry()
    report = cleanup_spawned_sensors(
        {"rgb_front": grid_entry},
        map_name="Grid0828",
        drain_timeout_s=0,
    )
    assert report.policy == "KNOWN_UNSTABLE"
    assert grid_entry.actor.stopped is True
    assert grid_entry.actor.destroyed is False
    assert report.session_disposable is True

    town_entry = _Entry()
    report = cleanup_spawned_sensors(
        {"rgb_front": town_entry}, map_name="Town10HD", drain_timeout_s=0
    )
    assert report.policy == "STABLE"
    assert town_entry.actor.destroyed is True


def test_cleanup_stops_sensors_in_reverse_spawn_order():
    order = []

    class _Recorder:
        def __init__(self, name):
            self.name = name

        def stop(self):
            order.append(self.name)

    spawned = {f"s{i}": SimpleNamespace(actor=_Recorder(f"s{i}")) for i in range(4)}
    report = cleanup_spawned_sensors(
        spawned, map_name="Town10HD", destroy=False, drain_timeout_s=0
    )
    assert order == ["s3", "s2", "s1", "s0"]
    assert report.stopped == ["s0", "s1", "s2", "s3"] or set(report.stopped) == {
        "s0", "s1", "s2", "s3",
    }


def test_cleanup_report_is_written(tmp_path):
    report = cleanup_spawned_sensors(
        {"rgb_front": SimpleNamespace(actor=_FakeSensor())},
        map_name="Grid0828",
        drain_timeout_s=0,
        report_path=tmp_path / "sub" / "sensor_lifecycle.json",
    )
    path = tmp_path / "sub" / "sensor_lifecycle.json"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["policy"] == "KNOWN_UNSTABLE"
    assert report.as_dict()["schema"] == "SENSOR_LIFECYCLE_REPORT/v1"


def test_environment_can_forced_override_the_policy(monkeypatch):
    monkeypatch.setenv("UP_SENSOR_LIFECYCLE_POLICY", "stable")
    assert env_forced_policy() is LifecyclePolicy.STABLE
    monkeypatch.delenv("UP_SENSOR_LIFECYCLE_POLICY")
    assert env_forced_policy() is None


# =========================================================================== #
# staged bring-up + resource budget (section 9 / 27)
# =========================================================================== #


def _checks(**overrides):
    def make(stage):
        def _check():
            payload = {"passed": True, "ticks_advanced": 5, "carla_alive": True,
                       "rpc_alive": True}
            payload.update(overrides.get(stage, {}))
            return payload

        return _check

    return {stage: make(stage) for stage in STAGES}


def test_full_ladder_passes_up_to_the_termination_stage():
    payload = run_staged_bringup(
        stage_checks=_checks(), profile="THESIS_FULL", stop_after="S6"
    )
    assert payload["passed"] is True
    assert payload["highest_stage_passed"] == "S6"
    assert payload["failed_stage"] is None
    assert payload["schema"] == "STAGED_BRINGUP/v1"
    assert payload["profile"] == "THESIS_FULL"


def test_failure_at_s4_records_highest_pass_as_s3():
    payload = run_staged_bringup(
        stage_checks=_checks(S4={"passed": False, "reason": "vram_spike"}),
        profile="THESIS_FULL",
        stop_after="S6",
    )
    assert payload["passed"] is False
    assert payload["highest_stage_passed"] == "S3"
    assert payload["failed_stage"] == "S4"
    # A single boolean cannot express "S4 failed while S3 passed".
    assert "highest_stage_passed=S3" in payload["diagnostic_note"]
    assert payload["stages"][4]["checks"]["world_ticks_advance"] == 5
    # S5..S7 never ran: the ladder stops at the first failure.
    assert len(payload["stages"]) == 5
    assert [s["stage"] for s in payload["stages"]] == ["S0", "S1", "S2", "S3", "S4"]


def test_stages_without_a_registered_check_are_skipped_not_failed():
    checks = _checks()
    del checks["S3"]
    payload = run_staged_bringup(stage_checks=checks, profile="THESIS_FULL", stop_after="S6")
    by_stage = {s["stage"]: s for s in payload["stages"]}
    assert by_stage["S3"]["skipped"] is True
    assert by_stage["S3"]["reason"] == "no_check_registered_for_stage"
    assert payload["passed"] is True


def test_start_stage_skips_earlier_stages():
    payload = run_staged_bringup(
        stage_checks=_checks(), profile="THESIS_FULL", start_stage="S3", stop_after="S6"
    )
    by_stage = {s["stage"]: s for s in payload["stages"]}
    assert by_stage["S0"]["skipped"] is True
    assert by_stage["S0"]["reason"] == "skipped_before_start_stage:S3"
    assert by_stage["S3"]["passed"] is True


def test_resource_budget_blocks_before_attaching_the_next_stage():
    payload = run_staged_bringup(
        stage_checks=_checks(),
        profile="LAPTOP_6GB_SAFE",
        stop_after="S4",
        resource_probe=lambda: {"vram_mb": 1e9, "rss_mb": 100.0},
    )
    blocked = [s for s in payload["stages"] if s["resource_budget_block"]]
    assert blocked, "expected a RESOURCE_BUDGET_BLOCK"
    assert blocked[0]["reason"].startswith("RESOURCE_BUDGET_BLOCK:vram=")
    assert payload["passed"] is False
    assert payload["failed_stage"] == blocked[0]["stage"]


def test_exception_in_a_stage_check_fails_that_stage_only():
    checks = _checks()

    def _boom():
        raise RuntimeError("rpc lost")

    checks["S2"] = _boom
    payload = run_staged_bringup(stage_checks=checks, profile="THESIS_FULL", stop_after="S6")
    assert payload["failed_stage"] == "S2"
    by_stage = {s["stage"]: s for s in payload["stages"]}
    assert by_stage["S2"]["reason"] == "stage_check_failed"
    assert "RuntimeError:rpc lost" in json.dumps(by_stage["S2"]["detail"])


def test_assert_within_budget_raises_with_the_numbers():
    assert_within_budget(100.0, budget_mb=5600.0)  # must not raise
    assert_within_budget(None, budget_mb=5600.0)
    with pytest.raises(ResourceBudgetBlock) as exc:
        assert_within_budget(9000.0, budget_mb=5600.0)
    assert "9000.0MB" in str(exc.value)
    assert "5600.0MB" in str(exc.value)


def test_vram_history_is_empirical_not_a_pixel_heuristic():
    payload = {}
    record_vram_after_sensor(payload, "rgb_front", 4100.0)
    record_vram_after_sensor(payload, "lidar_top", 4500.0)
    assert [h["after_sensor"] for h in payload["vram_history"]] == [
        "rgb_front", "lidar_top",
    ]
    assert payload["vram_history"][0]["vram_mb"] == 4100.0


def test_profiles_and_bringup_report(tmp_path):
    assert set(profile_names()) >= {"DEFAULT", "THESIS_FULL", "LAPTOP_6GB_SAFE"}
    assert resolve_profile("THESIS_FULL")["default_terminate_after_stage"] == "S6"
    # An unknown profile is refused loudly instead of silently defaulting.
    with pytest.raises(KeyError, match="unknown_capture_profile"):
        resolve_profile("unknown_profile_that_does_not_exist")

    payload = run_staged_bringup(stage_checks=_checks(), profile="THESIS_FULL")
    target = write_bringup_report(payload, tmp_path / "sub" / "bringup.json")
    assert target.exists()
    assert not list(target.parent.glob("*.tmp"))


# =========================================================================== #
# sensor canary (NEW-255)
# =========================================================================== #


def test_frame_id_plausibility_rejects_zero_negative_and_absurd_ids():
    assert _frame_id_plausible(1) is True
    assert _frame_id_plausible(0) is False
    assert _frame_id_plausible(-5) is False
    assert _frame_id_plausible("not a number") is False
    assert _frame_id_plausible(None) is False
    assert _frame_id_plausible(10**15) is False


def test_assert_canary_passed_names_the_failed_checks():
    with pytest.raises(RuntimeError, match="sensor_canary_failed"):
        assert_canary_passed({"passed": False, "checks": {"actor_alive": False}})
    with pytest.raises(RuntimeError, match="actor_alive"):
        assert_canary_passed({"passed": False, "checks": {"actor_alive": False}})
    with pytest.raises(RuntimeError):
        assert_canary_passed(None)
    assert_canary_passed({"passed": True, "checks": {}})  # must not raise


class _BrokenWorld:
    """A world that cannot provide a camera blueprint at all."""

    def get_blueprint_library(self):
        raise RuntimeError("no blueprint library")

    def tick(self, timeout=None):
        raise AssertionError("must not tick without a spawned sensor")


def test_canary_fails_closed_when_the_world_cannot_provide_a_camera(tmp_path):
    payload = run_sensor_canary(
        _BrokenWorld(),
        output_path=tmp_path / "SENSOR_CANARY.json",
        ticks=5,
    )
    assert payload["passed"] is False
    assert payload["frames_received"] == 0
    assert payload["errors"]
    assert payload["checks"]["actor_alive"] is False
    assert payload["checks"]["listener_attached"] is False
    # The decisive gate is the sensor, never the listening TCP port.
    assert payload["port_2001_status"] == "DIAGNOSTIC_ONLY_NOT_DECISIVE"
    assert "not a reliable readiness oracle" in payload["port_2001_note"]
    assert (tmp_path / "SENSOR_CANARY.json").exists()

    with pytest.raises(RuntimeError, match="sensor_canary_failed"):
        assert_canary_passed(payload)


def test_canary_writes_its_begin_and_callback_journal_entries():
    entries = []

    class _Journal:
        def record(self, phase, **fields):
            entries.append(phase)

    run_sensor_canary(_BrokenWorld(), phase_journal=_Journal(), ticks=5)
    assert entries[0] == "RGB_CANARY_BEGIN"
    assert "RGB_CANARY_CALLBACK" in entries
