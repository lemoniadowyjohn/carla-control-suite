# -*- coding: utf-8 -*-
"""Adversarial tests for the traffic-manager authority and walker lifecycle.

Covers findings D (CARLA API correctness), E (single-owner identity and
transactional release), F (evidence-derived claims), G (deterministic walker
scenario authority) and H (transactional walker/controller spawn).

No CARLA server is contacted. Every TM handle, actor and controller is a
duck-typed double exposing the real CARLA method names.
"""
from __future__ import annotations

import random

import pytest

from ultimate_pipeline.perception.environment import traffic_manager_session as tms


# ===========================================================================
# doubles
# ===========================================================================


class _FakeTM:
    """Duck-typed carla.TrafficManager exposing the real API method names."""

    def __init__(self, port: int = 8000, *, fail_seed: bool = False, expose_hybrid: bool = True):
        self._port = int(port)
        self.calls: list[tuple[str, tuple]] = []
        self._fail_seed = bool(fail_seed)
        if not expose_hybrid:
            # An older/limited build without the hybrid API.
            for name in ("hybrid_physics_mode", "hybrid_physics_radius"):
                self.__dict__[name] = None

    def get_port(self):
        return self._port

    def set_synchronous_mode(self, *a):
        self.calls.append(("set_synchronous_mode", a))

    def set_distance_to_leading_vehicle(self, *a):
        self.calls.append(("set_distance_to_leading_vehicle", a))

    def hybrid_physics_mode(self, *a):
        self.calls.append(("hybrid_physics_mode", a))

    def hybrid_physics_radius(self, *a):
        self.calls.append(("hybrid_physics_radius", a))

    def set_random_device_seed(self, *a):
        if self._fail_seed:
            raise RuntimeError("seed_rejected_by_tm")
        self.calls.append(("set_random_device_seed", a))

    def ignore_lights_percentage(self, *a):
        self.calls.append(("ignore_lights_percentage", a))

    def ignore_signs_percentage(self, *a):
        self.calls.append(("ignore_signs_percentage", a))

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


class _FakeClient:
    def __init__(self, handle=None, raise_on_get: bool = False):
        self.handle = handle
        self.raise_on_get = bool(raise_on_get)
        self.ports: list[int] = []

    def get_trafficmanager(self, port=8000):
        self.ports.append(int(port))
        if self.raise_on_get:
            raise RuntimeError("tm_unavailable")
        return self.handle


class _FakeActor:
    def __init__(self, actor_id="veh_1"):
        self.id = actor_id
        self.autopilot_calls: list[tuple] = []
        self._alive = True

    def is_alive(self):
        return self._alive

    def set_autopilot(self, enabled, port=None):
        self.autopilot_calls.append((bool(enabled), port))

    def destroy(self):
        self._alive = False


class _FakeController:
    def __init__(
        self,
        controller_id="ctl_1",
        *,
        fail_start: bool = False,
        fail_destination: bool = False,
        alive_after: bool = True,
    ):
        self.id = controller_id
        self.start_calls = 0
        self.destinations: list = []
        self.max_speeds: list = []
        self.stop_calls = 0
        self._fail_start = bool(fail_start)
        self._fail_destination = bool(fail_destination)
        self._alive = alive_after

    def start(self):
        self.start_calls += 1
        if self._fail_start:
            raise RuntimeError("controller_start_failed")

    def go_to_location(self, destination):
        if self._fail_destination:
            raise RuntimeError("destination_rejected")
        self.destinations.append(destination)

    def set_max_speed(self, speed):
        self.max_speeds.append(speed)

    def is_alive(self):
        return self._alive

    def stop(self):
        self.stop_calls += 1

    def destroy(self):
        self._alive = False


class _FakeWalkerWorld:
    """World double whose nav randomness can be governed or not."""

    def __init__(
        self,
        *,
        nav_random: bool = True,
        controller: _FakeController | None = None,
        controller_spawn_fails: bool = False,
        walker_spawn_fails: bool = False,
        controller_not_alive: bool = False,
    ):
        self.nav_random = bool(nav_random)
        self.controller = controller if controller is not None else _FakeController()
        self.controller_spawn_fails = bool(controller_spawn_fails)
        self.walker_spawn_fails = bool(walker_spawn_fails)
        self.controller_not_alive = bool(controller_not_alive)
        self.walkers: list[_FakeActor] = []
        self.spawned_controllers: list[_FakeController] = []

    def get_random_location_from_navigation(self):
        if not self.nav_random:
            return None
        return {"x": 999.0, "y": 999.0, "z": 0.0}

    def try_spawn_actor(self, bp, transform, attach_to=None):
        if attach_to is None:
            if self.walker_spawn_fails:
                return None
            actor = _FakeActor(f"walker_{len(self.walkers)}")
            self.walkers.append(actor)
            return actor
        if self.controller_spawn_fails:
            return None
        controller = self.controller
        if self.controller_not_alive:
            controller._alive = False
        self.spawned_controllers.append(controller)
        return controller

    def live_walkers(self) -> list[_FakeActor]:
        return [w for w in self.walkers if w.is_alive()]

    def live_controllers(self) -> list[_FakeController]:
        return [c for c in self.spawned_controllers if c.is_alive()]


@pytest.fixture(autouse=True)
def _reset_registry():
    tms.TrafficManagerSession.reset_master_registry()
    yield
    tms.TrafficManagerSession.reset_master_registry()


# ===========================================================================
# D. CARLA API correctness for hybrid physics
# ===========================================================================


def test_hybrid_false_uses_follow_gap_not_hybrid_api():
    handle = _FakeTM(expose_hybrid=True)
    session = tms.TrafficManagerSession(tm_port=8000, seed=7, hybrid_physics=False)
    session.acquire(_FakeClient(handle=handle))

    assert "hybrid_physics_mode" not in handle.names()
    assert "hybrid_physics_radius" not in handle.names()
    assert ("set_distance_to_leading_vehicle", (5.0,)) in handle.calls


def test_hybrid_true_calls_real_hybrid_api():
    """The exact expected calls, asserted against the real CARLA names."""
    handle = _FakeTM(expose_hybrid=True)
    session = tms.TrafficManagerSession(
        tm_port=8000, seed=7, hybrid_physics=True, hybrid_radius=12.5
    )
    session.acquire(_FakeClient(handle=handle))

    assert ("hybrid_physics_mode", (True,)) in handle.calls
    assert ("hybrid_physics_radius", (12.5,)) in handle.calls


def test_hybrid_radius_is_not_substituted_with_follow_gap():
    """The old bug: configuring the follow gap while claiming a radius."""
    handle = _FakeTM(expose_hybrid=True)
    session = tms.TrafficManagerSession(
        tm_port=8000, seed=7, hybrid_physics=True, hybrid_radius=12.5,
        global_distance=5.0,
    )
    session.acquire(_FakeClient(handle=handle))

    # The hybrid radius must be applied as the radius, not as the gap.
    assert ("hybrid_physics_radius", (12.5,)) in handle.calls
    assert ("set_distance_to_leading_vehicle", (5.0,)) not in handle.calls


def test_hybrid_radius_is_applied_only_when_requested():
    handle = _FakeTM(expose_hybrid=True)
    session = tms.TrafficManagerSession(
        tm_port=8000, seed=7, hybrid_physics=True, hybrid_radius=None
    )
    session.acquire(_FakeClient(handle=handle))
    assert ("hybrid_physics_mode", (True,)) in handle.calls
    assert "hybrid_physics_radius" not in handle.names()


def test_missing_hybrid_api_fails_closed():
    """If the hybrid API is absent, the governed hybrid config cannot be claimed."""
    handle = _FakeTM(expose_hybrid=False)
    session = tms.TrafficManagerSession(
        tm_port=8000, seed=7, hybrid_physics=True, hybrid_radius=12.5
    )
    with pytest.raises(RuntimeError, match="hybrid_physics"):
        session.acquire(_FakeClient(handle=handle))


def test_wrong_hybrid_api_name_mock_is_rejected():
    """A TM exposing only a wrong-name method must not pass the hybrid gate."""

    class _WrongNameTM:
        def __init__(self):
            self._port = 8000
            self.calls = []

        def get_port(self):
            return self._port

        def set_synchronous_mode(self, *a):
            self.calls.append(("set_synchronous_mode", a))

        def hybrid_physics_mode(self, *a):
            self.calls.append(("hybrid_physics_mode", a))

        def set_hybrid_physics_radius(self, *a):  # wrong name
            self.calls.append(("set_hybrid_physics_radius", a))

        def distance_to_leading_vehicle(self, *a):
            self.calls.append(("distance_to_leading_vehicle", a))

        def set_random_device_seed(self, *a):
            self.calls.append(("set_random_device_seed", a))

    handle = _WrongNameTM()
    session = tms.TrafficManagerSession(
        tm_port=8000, seed=7, hybrid_physics=True, hybrid_radius=12.5
    )
    with pytest.raises(RuntimeError, match="hybrid_physics_radius"):
        session.acquire(_FakeClient(handle=handle))
    # The wrong-name method must never have been called.
    assert ("set_hybrid_physics_radius", (12.5,)) not in handle.calls
    assert ("distance_to_leading_vehicle", (5.0,)) not in handle.calls


def test_hybrid_configuration_recorded_in_effective_config():
    handle = _FakeTM(expose_hybrid=True)
    session = tms.TrafficManagerSession(
        tm_port=8000, seed=7, hybrid_physics=True, hybrid_radius=9.0
    )
    session.acquire(_FakeClient(handle=handle))
    config = session.effective_config()
    assert config["hybrid_physics"] is True
    assert config["hybrid_radius"] == 9.0
    assert "hybrid_physics_radius=9.0" in config["configured_calls"]


# ===========================================================================
# E. single-owner identity
# ===========================================================================


def test_second_master_with_same_label_is_rejected():
    """A reused human-readable label must not bypass exclusivity."""
    a = tms.TrafficManagerSession(tm_port=8000, seed=1, session_id="127.0.0.1:8000")
    b = tms.TrafficManagerSession(tm_port=8000, seed=2, session_id="127.0.0.1:8000")

    assert a.session_id == b.session_id
    assert a.owner_token != b.owner_token
    assert a.run_uuid != b.run_uuid

    a.acquire(_FakeClient(handle=_FakeTM()))
    with pytest.raises(RuntimeError, match="TRAFFIC_MANAGER_MULTIPLE_MASTERS"):
        b.acquire(_FakeClient(handle=_FakeTM()))


def test_same_owner_token_may_reclaim():
    session = tms.TrafficManagerSession(tm_port=8000, seed=1)
    session.acquire(_FakeClient(handle=_FakeTM()))
    # Re-claiming as the same owner is idempotent, not an error.
    session.acquire(_FakeClient(handle=_FakeTM()))


def test_registry_records_owner_token_not_label():
    session = tms.TrafficManagerSession(
        tm_port=8000, seed=1, session_id="127.0.0.1:8000"
    )
    session.acquire(_FakeClient(handle=_FakeTM()))
    snapshot = tms.TrafficManagerSession.master_registry_snapshot()
    record = snapshot["8000"]
    assert record["owner_token"] == session.owner_token
    assert record["session_id"] == "127.0.0.1:8000"
    assert record["process_id"] > 0


def test_acquire_close_allows_next_run_on_same_port():
    first = tms.TrafficManagerSession(tm_port=8000, seed=1)
    first.acquire(_FakeClient(handle=_FakeTM()))
    first.close()

    second = tms.TrafficManagerSession(tm_port=8000, seed=2)
    second.acquire(_FakeClient(handle=_FakeTM()))
    assert second.effective_config()["seed"] == 2


def test_context_manager_releases_on_exception():
    session = tms.TrafficManagerSession(tm_port=8000, seed=1)
    with pytest.raises(RuntimeError, match="capture_failed"):
        with session:
            session.acquire(_FakeClient(handle=_FakeTM()))
            raise RuntimeError("capture_failed")

    # The claim must not leak: the port is free for the next run.
    assert "8000" not in tms.TrafficManagerSession.master_registry_snapshot()
    nxt = tms.TrafficManagerSession(tm_port=8000, seed=2)
    nxt.acquire(_FakeClient(handle=_FakeTM()))


def test_failed_acquire_after_claim_does_not_poison_registry():
    """A claim that is not followed by setup success must be released."""
    session = tms.TrafficManagerSession(tm_port=8000, seed=1)
    with pytest.raises(RuntimeError, match="TRAFFIC_MANAGER_SETUP_FAILED"):
        session.acquire(_FakeClient(raise_on_get=True))

    assert "8000" not in tms.TrafficManagerSession.master_registry_snapshot()
    nxt = tms.TrafficManagerSession(tm_port=8000, seed=2)
    nxt.acquire(_FakeClient(handle=_FakeTM()))


def test_failed_seed_after_claim_does_not_poison_registry():
    session = tms.TrafficManagerSession(tm_port=8000, seed=1)
    with pytest.raises(RuntimeError, match="set_random_device_seed"):
        session.acquire(_FakeClient(handle=_FakeTM(fail_seed=True)))
    assert "8000" not in tms.TrafficManagerSession.master_registry_snapshot()


def test_close_is_idempotent():
    session = tms.TrafficManagerSession(tm_port=8000, seed=1)
    session.acquire(_FakeClient(handle=_FakeTM()))
    first = session.close()
    second = session.close()
    assert first["master_released"] is True
    assert second["already_closed"] is True
    assert second["master_released"] is False


def test_close_detaches_governed_actors():
    session = tms.TrafficManagerSession(tm_port=8000, seed=1)
    session.acquire(_FakeClient(handle=_FakeTM()))
    actor = _FakeActor("veh_9")
    session.record_actor(actor, policies={"max_speed": 1.4})

    result = session.close()
    assert "veh_9" in result["autopilot_detached"]
    assert actor.autopilot_calls == [(False, 8000)]
    # Governed ownership metadata is detached, not merely flagged.
    assert session.actor_ledger()[0]["owner_session_id"] is None


# ===========================================================================
# F. evidence-derived TM claims
# ===========================================================================


def test_claims_are_derived_from_ledger():
    session = tms.TrafficManagerSession(tm_port=8000, seed=1, session_id="run_a")
    session.acquire(_FakeClient(handle=_FakeTM()))
    for i in range(3):
        session.record_actor(_FakeActor(f"veh_{i}"), policies={"max_speed": 1.4})

    evidence = tms.tm_actor_ledger_evidence(
        session.actor_ledger(), expected_tm_port=8000, expected_owner_session_id="run_a"
    )
    assert evidence["claims_are_derived"] is True
    assert evidence["unique_active_master_count"] == 1
    assert evidence["unique_tm_ports_for_governed_actors"] == [8000]
    assert evidence["actors_without_governed_tm"] == []
    assert evidence["actors_using_wrong_port"] == []
    assert evidence["single_tm_master"] is True
    assert evidence["all_governed_actors_use_single_port"] is True


def test_empty_ledger_yields_no_boolean_claims():
    """No evidence must mean None, never a hardcoded true."""
    evidence = tms.tm_actor_ledger_evidence([])
    assert evidence["insufficient_evidence"] is True
    assert evidence["insufficient_evidence_reason"] == "empty_actor_ledger"
    assert evidence["single_tm_master"] is None
    assert evidence["all_governed_actors_use_single_port"] is None
    assert evidence["all_governed_actors_owned"] is None


def test_actor_on_wrong_port_is_reported():
    session = tms.TrafficManagerSession(tm_port=8000, seed=1)
    ledger = [
        {"actor_id": "a", "actor_type": "vehicle", "autopilot_enabled": True,
         "tm_port": 8000, "owner_session_id": "run_a"},
        {"actor_id": "b", "actor_type": "vehicle", "autopilot_enabled": True,
         "tm_port": 9999, "owner_session_id": "run_a"},
    ]
    evidence = tms.tm_actor_ledger_evidence(ledger, expected_tm_port=8000)
    assert [row["actor_id"] for row in evidence["actors_using_wrong_port"]] == ["b"]
    assert evidence["all_governed_actors_on_expected_port"] is False
    assert evidence["all_governed_actors_use_single_port"] is False


def test_actor_without_governed_tm_is_reported():
    ledger = [
        {"actor_id": "a", "actor_type": "vehicle", "autopilot_enabled": True,
         "tm_port": None, "owner_session_id": None},
    ]
    evidence = tms.tm_actor_ledger_evidence(ledger)
    assert len(evidence["actors_without_governed_tm"]) == 1
    assert evidence["all_governed_actors_owned"] is False


def test_inactive_actor_is_not_counted_as_governed_traffic():
    ledger = [
        {"actor_id": "a", "actor_type": "vehicle", "autopilot_enabled": True,
         "tm_port": 8000, "owner_session_id": "run_a"},
        {"actor_id": "b", "actor_type": "vehicle", "autopilot_enabled": False,
         "tm_port": None, "owner_session_id": None},
    ]
    evidence = tms.tm_actor_ledger_evidence(ledger, expected_tm_port=8000)
    assert evidence["active_actor_count"] == 1
    assert evidence["actors_without_governed_tm"] == []
    assert evidence["all_governed_actors_owned"] is True


def test_two_masters_present_is_detected():
    a = tms.TrafficManagerSession(tm_port=8000, seed=1, is_master=True, session_id="run_a")
    a.acquire(_FakeClient(handle=_FakeTM()))
    # Bypass the guard to simulate a registry corruption / external claim.
    tms.TrafficManagerSession._masters[8001] = {
        "owner_token": "other", "run_uuid": "other", "session_id": "other",
        "process_id": 1, "claimed_at": 0.0,
    }
    evidence = tms.tm_actor_ledger_evidence(
        [{"actor_id": "x", "actor_type": "vehicle", "autopilot_enabled": True,
          "tm_port": 8000, "owner_session_id": "run_a"}]
    )
    assert evidence["unique_active_master_count"] == 2
    assert evidence["single_tm_master"] is False
    tms.TrafficManagerSession._masters.pop(8001, None)


# ===========================================================================
# G. deterministic walker scenario authority
# ===========================================================================


def test_manifest_binds_positions_and_hash():
    world = _FakeWalkerWorld(nav_random=False)
    world._governed_nav_pool = [
        {"x": 1.0, "y": 2.0, "z": 0.0},
        {"x": 3.0, "y": 4.0, "z": 0.0},
        {"x": 5.0, "y": 6.0, "z": 0.0},
    ]
    rng = random.Random(1234)
    manifest = tms.build_walker_scenario_manifest(
        world, rng=rng, seed_tree_branch="scenario", count=4, experiment_seed=1234
    )

    assert manifest["schema"] == "WALKER_SCENARIO_MANIFEST/v1"
    assert manifest["walker_count"] == 4
    assert len(manifest["scenario_manifest_sha256"]) == 64
    assert manifest["ungoverned_entry_count"] == 0
    for entry in manifest["entries"]:
        for field in (
            "walker_index", "blueprint", "spawn_transform",
            "destination_transform", "max_speed", "seed_tree_branch",
        ):
            assert field in entry, field
        assert entry["governed"] is True
        assert entry["spawn_provenance"] == "nav_governed_pool"


def test_manifest_is_replayable_for_paired_arms():
    """Both arms replay the same manifest instead of re-rolling nav."""
    world = _FakeWalkerWorld(nav_random=False)
    world._governed_nav_pool = [
        {"x": float(i), "y": float(i), "z": 0.0} for i in range(10)
    ]
    manifest = tms.build_walker_scenario_manifest(
        world, rng=random.Random(99), seed_tree_branch="scenario", count=3
    )

    # Arm B replays the recorded entries rather than sampling again.
    replayed = [
        (e["spawn_transform"], e["destination_transform"]) for e in manifest["entries"]
    ]
    assert len(replayed) == 3
    assert all(s is not None and d is not None for s, d in replayed)


def test_manifest_marks_carla_random_positions_ungoverned():
    """Uncontrolled CARLA nav randomness must not be called deterministic."""
    world = _FakeWalkerWorld(nav_random=True)
    manifest = tms.build_walker_scenario_manifest(
        world, rng=random.Random(5), seed_tree_branch="scenario", count=2
    )
    assert manifest["ungoverned_entry_count"] == 2
    for entry in manifest["entries"]:
        assert entry["governed"] is False
        assert entry["spawn_provenance"] == "nav_carla_random"


def test_manifest_hash_changes_with_positions():
    world = _FakeWalkerWorld(nav_random=False)
    world._governed_nav_pool = [{"x": 1.0, "y": 1.0, "z": 0.0}]
    a = tms.build_walker_scenario_manifest(
        world, rng=random.Random(1), seed_tree_branch="scenario", count=2
    )
    b = tms.build_walker_scenario_manifest(
        world, rng=random.Random(2), seed_tree_branch="scenario", count=2
    )
    # Same pool, same seed -> identical plan and digest.
    assert a["scenario_manifest_sha256"] == b["scenario_manifest_sha256"]


def test_ungoverned_random_walker_position_is_refused():
    """A CARLA-random position must not yield a controlled walker."""
    world = _FakeWalkerWorld(nav_random=True)
    result = tms.build_controlled_walker(
        world, None, "walker.pedestrian.0001", controller_bp="controller.ai.walker",
        rng=random.Random(3),
    )
    assert result["controlled"] is False
    assert tms.WALKER_POSITION_UNGOVERNED in result["failure_code"]
    assert world.live_walkers() == []


# ===========================================================================
# H. transactional walker/controller lifecycle
# ===========================================================================


def test_controlled_walker_commits_when_all_steps_succeed():
    world = _FakeWalkerWorld(nav_random=False)
    world._governed_nav_pool = [{"x": 1.0, "y": 1.0, "z": 0.0}]
    registry = tms.ScenarioActorRegistry()

    result = tms.build_controlled_walker(
        world, None, "walker.pedestrian.0001", controller_bp="controller.ai.walker",
        rng=random.Random(3), walker_index=0,
        ownership_registry=registry, seed_tree_branch="scenario",
        scenario_manifest_sha256="deadbeef",
    )

    assert result["controlled"] is True
    assert result["controller_started"] is True
    assert result["destination_assigned"] is True
    assert result["transaction_committed"] is True
    assert result["counts_as_pedestrian_traffic"] is True
    assert result["scenario_manifest_sha256"] == "deadbeef"
    assert registry.owned_count() == 2
    # Ownership is registered, so both actors are still alive.
    assert registry.verify_clean()["clean"] is False

    # After cleanup the registry must prove zero owned actors remain alive.
    registry.destroy_all()
    assert registry.verify_clean()["clean"] is True
    # owned_count stays 2 because the registry retains its bookkeeping rows;
    # what matters is that none of them is alive.
    assert registry.verify_clean()["owned_actors_still_alive"] == []


def test_walker_controller_spawn_failure_rolls_back_walker():
    world = _FakeWalkerWorld(nav_random=False, controller_spawn_fails=True)
    world._governed_nav_pool = [{"x": 1.0, "y": 1.0, "z": 0.0}]
    registry = tms.ScenarioActorRegistry()

    result = tms.build_controlled_walker(
        world, None, "walker.pedestrian.0001", controller_bp="controller.ai.walker",
        rng=random.Random(3), ownership_registry=registry,
    )

    assert result["controlled"] is False
    assert tms.WALKER_TRANSACTION_FAILED in result["failure_code"]
    # No walker may survive a controller failure.
    assert world.live_walkers() == []
    assert registry.owned_count() == 0


def test_walker_controller_start_failure_rolls_back_both():
    controller = _FakeController(fail_start=True)
    world = _FakeWalkerWorld(nav_random=False, controller=controller)
    world._governed_nav_pool = [{"x": 1.0, "y": 1.0, "z": 0.0}]
    registry = tms.ScenarioActorRegistry()

    result = tms.build_controlled_walker(
        world, None, "walker.pedestrian.0001", controller_bp="controller.ai.walker",
        rng=random.Random(3), ownership_registry=registry,
    )

    assert result["controlled"] is False
    assert result["controller_started"] is False
    assert "controller_start" in result["failure_code"]
    assert world.live_walkers() == []
    assert world.live_controllers() == []
    assert registry.owned_count() == 0


def test_walker_destination_failure_rolls_back_and_is_not_controlled():
    controller = _FakeController(fail_destination=True)
    world = _FakeWalkerWorld(nav_random=False, controller=controller)
    world._governed_nav_pool = [{"x": 1.0, "y": 1.0, "z": 0.0}]
    registry = tms.ScenarioActorRegistry()

    result = tms.build_controlled_walker(
        world, None, "walker.pedestrian.0001", controller_bp="controller.ai.walker",
        rng=random.Random(3), ownership_registry=registry,
    )

    assert result["controlled"] is False, (
        "a failed destination assignment must not report controlled=True"
    )
    assert result["destination_assigned"] is False
    assert "destination" in result["failure_code"]
    assert world.live_walkers() == []
    assert registry.owned_count() == 0


def test_walker_spawn_failure_reports_structured_failure():
    world = _FakeWalkerWorld(nav_random=False, walker_spawn_fails=True)
    world._governed_nav_pool = [{"x": 1.0, "y": 1.0, "z": 0.0}]
    result = tms.build_controlled_walker(
        world, None, "walker.pedestrian.0001", controller_bp="controller.ai.walker",
        rng=random.Random(3),
    )
    assert result["controlled"] is False
    assert "walker_spawn" in result["failure_code"]
    assert result["transaction_committed"] is False


def test_controller_not_alive_after_spawn_rolls_back():
    world = _FakeWalkerWorld(nav_random=False, controller_not_alive=True)
    world._governed_nav_pool = [{"x": 1.0, "y": 1.0, "z": 0.0}]
    result = tms.build_controlled_walker(
        world, None, "walker.pedestrian.0001", controller_bp="controller.ai.walker",
        rng=random.Random(3),
    )
    assert result["controlled"] is False
    assert "actor_not_alive" in result["failure_code"]
    assert world.live_walkers() == []


def test_status_is_never_true_without_a_real_controller():
    """Structural guard against the old unconditional controlled=True."""
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(tms.build_controlled_walker))
    func = ast.parse(src).body[0]
    # Every "controlled": True literal must be in the final success return, and
    # must not be reachable from a failure path.
    controlled_true = [
        n
        for n in ast.walk(func)
        if isinstance(n, ast.Dict)
        and any(
            isinstance(k, ast.Constant) and k.value == "controlled"
            for k in n.keys
            if isinstance(k, ast.Constant)
        )
        and any(
            isinstance(v, ast.Constant) and v.value is True for v in n.values
        )
    ]
    assert len(controlled_true) == 1, (
        "controlled=True must appear exactly once, on the committed-success path"
    )


def test_controlled_result_validates_under_validate_walker_mode():
    world = _FakeWalkerWorld(nav_random=False)
    world._governed_nav_pool = [{"x": 1.0, "y": 1.0, "z": 0.0}]
    result = tms.build_controlled_walker(
        world, None, "walker.pedestrian.0001", controller_bp="controller.ai.walker",
        rng=random.Random(3),
    )
    report = tms.validate_walker_mode([result], mode=tms.WALKER_MODE_CONTROLLED)
    assert report["valid"] is True
    assert report["controlled_pedestrians"] == 1


def test_failed_walker_is_rejected_by_validate_walker_mode():
    world = _FakeWalkerWorld(nav_random=True)
    result = tms.build_controlled_walker(
        world, None, "walker.pedestrian.0001", controller_bp="controller.ai.walker",
        rng=random.Random(3),
    )
    report = tms.validate_walker_mode([result], mode=tms.WALKER_MODE_CONTROLLED)
    assert report["valid"] is False, (
        "an ungoverned walker must fail the strict pedestrian scenario"
    )
