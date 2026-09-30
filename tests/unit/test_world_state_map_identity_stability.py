# -*- coding: utf-8 -*-
"""World state machine (NEW-248/249), runtime map identity (NEW-252/253/254),
post-load stability soak (NEW-260).

Core invariants:

* Once ``MAP_ESTABLISHED`` is entered, no further map-changing operation may
  be issued until the capture ends.
* Map identity is a canonical STRUCTURAL fingerprint; CARLA re-serialises
  OpenDRIVE, so byte equality is the wrong test.
* Perception may not start from merely ``MAP_LOADED``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ultimate_pipeline.perception.postload_stability import (
    HARD_MIN_TICKS,
    MAP_LOADED,
    MAP_STABLE,
    assert_perception_may_start,
    resolve_required_soak_ticks,
    run_postload_soak,
    write_soak_report,
)
from ultimate_pipeline.perception.runtime_map_identity import (
    capture_runtime_map_identity,
    compare_fingerprints,
    structural_fingerprint,
)
from ultimate_pipeline.perception.world_state_machine import (
    InvalidStateTransition,
    MapTravelForbidden,
    WorldPipelineState,
    WorldStateMachine,
    assert_no_map_change_after_established,
    guarded_load_world,
    is_map_changing,
)


def _xodr(*, road_count: int = 1, length: str = "100.000000", name: str = "Grid0828") -> str:
    roads = []
    for i in range(road_count):
        rid = i + 1
        roads.append(
            f'<road name="r{rid}" length="{length}" id="{rid}" junction="-1">'
            f'<planView>'
            f'<geometry s="0.000000" x="{i}.000000" y="0.000000" hdg="0.000000" '
            f'length="{length}"><line/></geometry>'
            f'</planView>'
            f'<lanes><laneSection s="0.000000">'
            f'<center><lane id="0" type="none" level="false"/></center>'
            f'</laneSection></lanes>'
            f'</road>'
        )
    return (
        '<OpenDRIVE>'
        f'<header revMajor="1" revMinor="6" name="{name}" version="1.0" date="2026"/>'
        + "".join(roads)
        + "</OpenDRIVE>"
    )


# =========================================================================== #
# world state machine
# =========================================================================== #


def test_initial_state_is_unresolved_and_map_change_is_permitted():
    machine = WorldStateMachine()
    assert machine.state is WorldPipelineState.UNRESOLVED
    assert not machine.established()
    machine.guard_map_change("load_world")  # must not raise
    assert machine.map_operation_attempts[-1]["permitted"] is True


def test_established_state_forbids_any_map_change():
    machine = WorldStateMachine()
    machine.begin_map_load("load_world")
    machine.mark_established()
    assert machine.established()

    with pytest.raises(MapTravelForbidden) as exc:
        machine.guard_map_change("load_world", detail="Grid0828")
    assert machine.state.value == "MAP_ESTABLISHED"
    assert "map_travel_forbidden" in str(exc.value)
    assert machine.map_operation_attempts[-1]["permitted"] is False


def test_every_map_changing_operation_is_forbidden_after_establishment():
    machine = WorldStateMachine()
    machine.begin_map_load("load_world")
    machine.mark_established()
    for op in ("load_world", "reload_world", "generate_opendrive_world"):
        with pytest.raises(MapTravelForbidden):
            machine.guard_map_change(op)


def test_illegal_transition_is_rejected():
    machine = WorldStateMachine()
    for target in (
        WorldPipelineState.CAPTURE_PREPARING,
        WorldPipelineState.CAPTURE_ACTIVE,
        WorldPipelineState.FINALIZING,
    ):
        with pytest.raises(InvalidStateTransition):
            machine.transition(target)
    # UNRESOLVED -> COMPLETE is legal: it is the offline-reuse short-circuit.
    machine.transition(WorldPipelineState.COMPLETE)
    with pytest.raises(InvalidStateTransition):
        machine.transition(WorldPipelineState.MAP_LOADING)  # COMPLETE is terminal


def test_try_transition_returns_false_instead_of_raising():
    machine = WorldStateMachine()
    assert machine.try_transition(WorldPipelineState.CAPTURE_ACTIVE) is False
    assert machine.try_transition(WorldPipelineState.MAP_LOADING) is True
    assert machine.state is WorldPipelineState.MAP_LOADING


def test_mark_established_is_idempotent_once_capture_started():
    machine = WorldStateMachine()
    machine.begin_map_load()
    machine.mark_established()
    machine.transition(WorldPipelineState.CAPTURE_PREPARING)
    machine.transition(WorldPipelineState.CAPTURE_ACTIVE)
    machine.mark_established()  # no-op, must not raise
    assert machine.state is WorldPipelineState.CAPTURE_ACTIVE


def test_mark_failed_is_terminal_and_cannot_be_revived():
    machine = WorldStateMachine()
    machine.begin_map_load()
    machine.mark_failed(reason="engine_died")
    assert machine.state is WorldPipelineState.FAILED
    machine.mark_complete()  # a late teardown must NOT rewrite a failure
    assert machine.state is WorldPipelineState.FAILED
    machine.mark_established()  # nor resurrect it
    assert machine.state is WorldPipelineState.FAILED


def test_complete_state_cannot_become_failed():
    machine = WorldStateMachine()
    machine.mark_complete(reason="offline_reuse")
    machine.mark_failed(reason="late_error")
    assert machine.state is WorldPipelineState.COMPLETE


def test_snapshot_and_write_snapshot_are_complete(tmp_path):
    machine = WorldStateMachine()
    machine.begin_map_load()
    machine.guard_map_change("load_world")
    machine.mark_established()

    snap = machine.snapshot()
    assert snap["state"] == "MAP_ESTABLISHED"
    assert snap["established"] is True
    assert snap["map_changing_operations_permitted"] is False
    assert any(e["event"] == "MAP_OPERATION_GUARD" for e in snap["history"])

    target = tmp_path / "world_state.json"
    machine.write_snapshot(target)
    assert json.loads(target.read_text(encoding="utf-8"))["state"] == "MAP_ESTABLISHED"


def test_journal_sink_receives_every_event():
    events = []
    machine = WorldStateMachine(journal=events.append)
    machine.begin_map_load()
    machine.mark_established()
    assert [e["event"] for e in events] == [
        "INITIAL",
        "MAP_OPERATION_GUARD",
        "TRANSITION",
        "TRANSITION",
    ]


def test_journal_sink_failure_does_not_break_the_run():
    def _boom(_entry):
        raise RuntimeError("sink dead")

    machine = WorldStateMachine(journal=_boom)
    machine.begin_map_load()  # must not raise


def test_guarded_load_world_marks_failed_on_exception():
    class _Client:
        def load_world(self, name, **kwargs):
            raise RuntimeError("nope")

    machine = WorldStateMachine()
    with pytest.raises(RuntimeError):
        guarded_load_world(_Client(), "Grid0828", state_machine=machine)
    assert machine.state is WorldPipelineState.FAILED


def test_guarded_load_world_records_success():
    class _Client:
        def __init__(self):
            self.calls = []

        def load_world(self, name, **kwargs):
            self.calls.append(name)
            return "world"

    machine = WorldStateMachine()
    client = _Client()
    assert guarded_load_world(client, "Grid0828", state_machine=machine) == "world"
    assert client.calls == ["Grid0828"]
    assert machine.state is WorldPipelineState.MAP_LOADING
    assert machine.map_operation_attempts[-1]["permitted"] is True


def test_assert_no_map_change_after_established_lists_violations():
    attempts = [
        {"operation": "load_world", "permitted": True},
        {"operation": "reload_world", "permitted": False},
    ]
    violations = assert_no_map_change_after_established(attempts)
    assert len(violations) == 1
    assert violations[0]["operation"] == "reload_world"
    assert assert_no_map_change_after_established([]) == []


def test_is_map_changing_covers_the_three_operations():
    assert is_map_changing("load_world")
    assert is_map_changing("reload_world")
    assert is_map_changing("generate_opendrive_world")
    assert not is_map_changing("world.tick")


# =========================================================================== #
# runtime map identity
# =========================================================================== #


def test_fingerprint_is_stable_across_formatting_noise():
    canonical = _xodr()
    noisy = canonical.replace("100.000000", "100.0").replace("><", ">\n  <")
    assert structural_fingerprint(canonical)["structural_sha256"] == (
        structural_fingerprint(noisy)["structural_sha256"]
    )


def test_fingerprint_detects_structural_change():
    one = structural_fingerprint(_xodr(road_count=1))
    two = structural_fingerprint(_xodr(road_count=2))
    assert one["structural_sha256"] != two["structural_sha256"]
    assert one["road_count"] == 1
    assert two["road_count"] == 2


def test_fingerprint_is_not_byte_equality():
    a = _xodr(length="100.000000")
    b = _xodr(length="100.0")
    # Different bytes, identical structure: CARLA re-serialises OpenDRIVE on
    # the way out of the engine, so raw byte equality is the wrong test.
    assert a != b
    assert structural_fingerprint(a)["structural_sha256"] == (
        structural_fingerprint(b)["structural_sha256"]
    )


def test_compare_identical_fingerprints_matches():
    fp = structural_fingerprint(_xodr())
    report = compare_fingerprints(fp, json.loads(json.dumps(fp)))
    assert report["match"] is True
    assert report["mismatched_components"] == []
    assert report["byte_equality_required"] is False
    assert "never raw byte equality" in report["byte_equality_note"]


def test_compare_reports_the_specific_mismatched_component():
    left = structural_fingerprint(_xodr(road_count=1))
    right = structural_fingerprint(_xodr(road_count=3))
    report = compare_fingerprints(left, right)
    assert report["match"] is False
    assert "road_count" in report["mismatched_components"]
    assert report["component_details"]["road_count"]["expected"] == 1
    assert report["component_details"]["road_count"]["actual"] == 3


def test_georeference_presence_mismatch_is_non_blocking_by_default():
    left = structural_fingerprint(_xodr())
    right = structural_fingerprint(_xodr())
    left["georeference"] = "+proj=utm +zone=32"
    report = compare_fingerprints(left, right)
    assert report["component_details"]["georeference"]["expected_present"] is True
    assert report["component_details"]["georeference"]["actual_present"] is False

    strict = compare_fingerprints(left, right, require_georeference_match=True)
    assert strict["match"] is False
    assert "georeference_presence" in strict["mismatched_components"]


class _FakeMap:
    def __init__(self, text, name="Grid0828"):
        self._text = text
        self.name = name

    def to_opendrive(self):
        return self._text


class _FakeWorld:
    def __init__(self, text, name="Grid0828", raise_on_to_xodr=False):
        self._map = _FakeMap(text, name)
        self._raise = raise_on_to_xodr

    def get_map(self):
        return self._map


def test_capture_runtime_identity_passes_when_name_and_structure_agree(tmp_path):
    text = _xodr()
    payload = capture_runtime_map_identity(
        world=_FakeWorld(text),
        expected_xodr_text=text,
        expected_label="manual_grid0828",
        output_path=tmp_path / "identity.json",
        map_name_matched=True,
        map_names_match_result=True,
    )
    assert payload["runtime_identity_pass"] is True
    assert payload["layer1_name_identity"]["passed"] is True
    assert payload["layer2_structural_identity"]["passed"] is True
    assert payload["layer1_name_identity"]["substring_matching_used"] is False
    assert (tmp_path / "identity.json").exists()


def test_capture_runtime_identity_fails_on_name_only_match_with_wrong_structure(tmp_path):
    payload = capture_runtime_map_identity(
        world=_FakeWorld(_xodr(road_count=5)),
        expected_xodr_text=_xodr(road_count=1),
        expected_label="manual_grid0828",
        output_path=tmp_path / "identity.json",
        map_name_matched=True,
    )
    assert payload["runtime_identity_pass"] is False
    assert payload["layer1_name_identity"]["passed"] is True
    assert payload["layer2_structural_identity"]["passed"] is False
    assert (
        "road_count"
        in payload["layer2_structural_identity"]["comparison"]["mismatched_components"]
    )


def test_capture_runtime_identity_fails_when_runtime_xodr_is_unavailable(tmp_path):
    payload = capture_runtime_map_identity(
        world=_FakeWorld(None),
        expected_xodr_text=_xodr(),
        expected_label="manual_grid0828",
        output_path=tmp_path / "identity.json",
        map_name_matched=True,
    )
    assert payload["runtime_identity_pass"] is False
    assert (
        "structural_fingerprint_unavailable"
        in payload["layer2_structural_identity"]["comparison"]["mismatched_components"]
    )


# =========================================================================== #
# post-load stability
# =========================================================================== #


def test_soak_ticks_can_be_RAISED_but_never_lowered_below_30(monkeypatch):
    monkeypatch.delenv("UP_POSTLOAD_SOAK_TICKS", raising=False)
    assert resolve_required_soak_ticks(None) == HARD_MIN_TICKS
    assert resolve_required_soak_ticks(1) == HARD_MIN_TICKS
    assert resolve_required_soak_ticks(0) == HARD_MIN_TICKS
    assert resolve_required_soak_ticks(120) == 120


def test_soak_ticks_honour_configuration_upward(monkeypatch):
    monkeypatch.setenv("UP_POSTLOAD_SOAK_TICKS", "45")
    assert resolve_required_soak_ticks(None) == 45
    monkeypatch.setenv("UP_POSTLOAD_SOAK_TICKS", "5")  # cannot lower it
    assert resolve_required_soak_ticks(None) == HARD_MIN_TICKS


class _FakeAdvancingWorld:
    """A world whose frames always advance on tick."""

    def __init__(self, start=0):
        self._frame = start
        self.ticks = 0

    def tick(self, timeout=None):
        self.ticks += 1
        self._frame += 1

    def get_snapshot(self):
        return SimpleNamespace(frame=self._frame)


class _FrozenWorld:
    """Frames never advance (engine wedged after load), then it starts erroring.

    The raise-after-N keeps the unit test fast: without it the soak correctly
    spins until its overall deadline.
    """

    def __init__(self):
        self._frame = 7
        self.ticks = 0

    def tick(self, timeout=None):
        self.ticks += 1
        if self.ticks > 5:
            raise RuntimeError("wedged")

    def get_snapshot(self):
        return SimpleNamespace(frame=self._frame)


class _DeadWorld:
    def tick(self, timeout=None):
        raise RuntimeError("RPC timeout")


def test_soak_passes_only_after_the_required_advancing_ticks():
    report = run_postload_soak(
        _FakeAdvancingWorld(),
        min_ticks=30,
        resource_sampler=lambda: {"vram_mb": 100.0, "rss_mb": 50.0},
    )
    assert report["gate"] == MAP_STABLE
    assert report["stable"] is True
    assert report["advancing_ticks"] >= 30
    assert report["rpc_failures"] == 0
    assert report["peak_vram_mb"] == 100.0
    assert_perception_may_start(report)


def test_soak_fails_when_ticks_do_not_advance():
    world = _FrozenWorld()
    report = run_postload_soak(
        world, min_ticks=30, resource_sampler=lambda: {"vram_mb": 1.0}
    )
    assert report["gate"] == MAP_LOADED
    assert report["stable"] is False
    # Six ticks were issued but only the first advanced the frame counter;
    # non-advancing ticks must never be counted as stability evidence.
    assert world.ticks > report["advancing_ticks"]
    assert report["advancing_ticks"] < report["required_ticks"]
    assert any(
        s.get("error") == "non_advancing_tick" for s in report["resource_samples"]
    )
    with pytest.raises(RuntimeError, match="postload_stability_gate_failed"):
        assert_perception_may_start(report)


def test_soak_fails_when_ticks_raise():
    report = run_postload_soak(_DeadWorld(), min_ticks=30)
    assert report["gate"] == MAP_LOADED
    assert report["tick_errors"]
    assert report["stable"] is False


def test_perception_may_not_start_without_a_report():
    with pytest.raises(RuntimeError, match="postload_stability_gate_failed"):
        assert_perception_may_start({})
    with pytest.raises(RuntimeError, match="postload_stability_gate_failed"):
        assert_perception_may_start(None)


def test_soak_report_is_written_atomically(tmp_path):
    report = run_postload_soak(_FakeAdvancingWorld(), min_ticks=30)
    target = tmp_path / "sub" / "postload_stability.json"
    written = write_soak_report(report, target)
    assert written == target
    assert json.loads(target.read_text(encoding="utf-8"))["gate"] == MAP_STABLE
    assert not list(target.parent.glob("*.tmp"))


def test_soak_records_progress_and_state_machine_events():
    progress = []
    machine = WorldStateMachine()
    machine.begin_map_load()
    report = run_postload_soak(
        _FakeAdvancingWorld(),
        min_ticks=30,
        state_machine=machine,
        on_progress=progress.append,
    )
    assert progress
    assert progress[-1]["required"] == 30
    events = [e["event"] for e in machine.history]
    assert "POSTLOAD_STABILITY_BEGIN" in events
    assert "POSTLOAD_STABILITY_RETURN" in events
    assert "MAP_STABLE" in events
    assert report["gate"] == MAP_STABLE
