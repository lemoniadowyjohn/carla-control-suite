# -*- coding: utf-8 -*-
"""Back-to-back run contamination (finding I).

Two runs execute sequentially IN ONE PROCESS. Run B must be governed entirely by
B's requested state and must inherit nothing from run A: no TM master ownership,
no scenario actors, no callbacks, no writer work, no frame ids, no RNG state and
no walker destinations.

Every CARLA object is a duck-typed double; no server is contacted. The RNG
assertions deliberately use the process-global generator, because a leak there
is invisible to seed-tree-only checks.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from ultimate_pipeline.perception.environment import (
    seed_tree as seeds,
    traffic_manager_session as tms,
)
from ultimate_pipeline.sensors.recorder import RecorderConfig, SensorRecorder


# ===========================================================================
# doubles
# ===========================================================================


class _FakeTM:
    def __init__(self, port: int = 8000):
        self._port = int(port)
        self.calls: list[tuple[str, tuple]] = []

    def get_port(self):
        return self._port

    def set_synchronous_mode(self, *a):
        self.calls.append(("set_synchronous_mode", a))

    def set_distance_to_leading_vehicle(self, *a):
        self.calls.append(("set_distance_to_leading_vehicle", a))

    def set_random_device_seed(self, *a):
        self.calls.append(("set_random_device_seed", a))

    def ignore_lights_percentage(self, *a):
        self.calls.append(("ignore_lights_percentage", a))

    def ignore_signs_percentage(self, *a):
        self.calls.append(("ignore_signs_percentage", a))


class _FakeClient:
    def __init__(self, handle=None):
        self.handle = handle
        self.ports: list[int] = []

    def get_trafficmanager(self, port=8000):
        self.ports.append(int(port))
        return self.handle


class _FakeActor:
    def __init__(self, actor_id: str):
        self.id = actor_id
        self._alive = True
        self.autopilot_calls: list[tuple] = []

    def is_alive(self):
        return self._alive

    def set_autopilot(self, enabled, port=None):
        self.autopilot_calls.append((bool(enabled), port))

    def destroy(self):
        self._alive = False


class _FakeController:
    def __init__(self, controller_id: str):
        self.id = controller_id
        self.destinations: list = []
        self.max_speeds: list = []
        self._alive = True

    def start(self):
        return None

    def go_to_location(self, destination):
        self.destinations.append(destination)

    def set_max_speed(self, speed):
        self.max_speeds.append(speed)

    def is_alive(self):
        return self._alive

    def stop(self):
        return None

    def destroy(self):
        self._alive = False


class _WalkerWorld:
    """Walker world whose nav pool is the deterministic index pool."""

    def __init__(self, pool):
        self._governed_nav_pool = list(pool)
        self.walkers: list[_FakeActor] = []
        self.controllers: list[_FakeController] = []

    def get_random_location_from_navigation(self):
        # CARLA-side randomness must never be reached: the pool governs.
        raise AssertionError("CARLA nav randomness must not be used in governed mode")

    def try_spawn_actor(self, bp, transform, attach_to=None):
        if attach_to is None:
            actor = _FakeActor(f"walker_{len(self.walkers)}")
            self.walkers.append(actor)
            return actor
        controller = _FakeController(f"ctl_{len(self.controllers)}")
        self.controllers.append(controller)
        return controller

    def live_walkers(self) -> list[_FakeActor]:
        return [w for w in self.walkers if w.is_alive()]

    def live_controllers(self) -> list[_FakeController]:
        return [c for c in self.controllers if c.is_alive()]


class _ImageData:
    def __init__(self, frame: int):
        self.frame = frame
        self.width = 2
        self.height = 2
        self.raw_data = b"\x07" * 16

    def save_to_disk(self, path):
        Path(path).write_bytes(b"png")


class _FakeSensor:
    def __init__(self, actor_id: int = 1, type_id: str = "sensor.camera.semantic_segmentation"):
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


POOL_A = [{"x": 10.0, "y": 11.0, "z": 0.0}, {"x": 12.0, "y": 13.0, "z": 0.0}]
POOL_B = [{"x": 90.0, "y": 91.0, "z": 0.0}, {"x": 92.0, "y": 93.0, "z": 0.0}]


@pytest.fixture(autouse=True)
def _reset_registry():
    tms.TrafficManagerSession.reset_master_registry()
    yield
    tms.TrafficManagerSession.reset_master_registry()


# ===========================================================================
# one governed run
# ===========================================================================


def _run(
    tmp_path: Path,
    label: str,
    *,
    seed: int,
    tm_port: int,
    nav_pool,
    frames,
    sensor_actor_id: int,
) -> dict:
    """Execute one complete governed run and return its observable state."""
    tree = seeds.build_seed_tree(seed)
    rng = random.Random(tree["seeds"]["scenario"])

    # TM session
    session = tms.TrafficManagerSession(
        tm_port=tm_port, seed=tree["seeds"]["tm"], session_id=label
    )
    session.acquire(_FakeClient(handle=_FakeTM(port=tm_port)))

    # Walker scenario: manifest built from the deterministic index pool
    world = _WalkerWorld(nav_pool)
    registry = tms.ScenarioActorRegistry()
    manifest = tms.build_walker_scenario_manifest(
        world,
        rng=rng,
        seed_tree_branch="scenario",
        count=2,
        experiment_seed=seed,
    )
    walker_results = []
    for entry in manifest["entries"]:
        walker_results.append(
            tms.build_controlled_walker(
                world,
                None,
                entry["blueprint"],
                controller_bp=entry["controller_blueprint"],
                rng=rng,
                walker_index=entry["walker_index"],
                spawn_location=entry["spawn_transform"],
                destination_location=entry["destination_transform"],
                spawn_provenance=entry["spawn_provenance"],
                destination_provenance=entry["destination_provenance"],
                max_speed=entry["max_speed"],
                seed_tree_branch=entry["seed_tree_branch"],
                scenario_manifest_sha256=manifest["scenario_manifest_sha256"],
                ownership_registry=registry,
            )
        )

    # Sensor capture
    sensor = _FakeSensor(actor_id=sensor_actor_id)
    recorder = _Recorder(
        world=_FakeWorld(),
        sensors={"cam": sensor},
        output_dir=str(tmp_path / label),
        config=RecorderConfig(strict=True, required_sensors=("cam",)),
    )
    recorder.start()
    for frame in frames:
        sensor.emit(_ImageData(frame))
    drain = recorder.join_writer_threads(timeout_s=10.0)
    correspondence = recorder.frame_correspondence()

    state = {
        "label": label,
        "seed_tree_sha256": seeds.seed_tree_sha256(tree),
        "tm_seed": tree["seeds"]["tm"],
        "tm_port": tm_port,
        "owner_token": session.owner_token,
        "scenario_manifest_sha256": manifest["scenario_manifest_sha256"],
        "walker_destinations": [
            (w["destination_transform"]["x"], w["destination_transform"]["y"])
            for w in walker_results
            if w["controlled"]
        ],
        "controlled_walker_count": sum(1 for w in walker_results if w["controlled"]),
        "callback_frame_ids": list(correspondence["per_sensor_frame_ids"]["cam"]),
        "drain_state": drain["state"],
        "drain_pending": drain["pending_frame_count"],
        "world": world,
        "registry": registry,
        "session": session,
        "sensor": sensor,
        "recorder": recorder,
        "master_registry_after": tms.TrafficManagerSession.master_registry_snapshot(),
    }

    # cleanup
    state["destroyed"] = registry.destroy_all()
    state["clean_after_cleanup"] = registry.verify_clean()["clean"]
    state["close_result"] = session.close()
    state["master_registry_after_cleanup"] = (
        tms.TrafficManagerSession.master_registry_snapshot()
    )
    state["tm_session_closed"] = session.closed
    return state


# ===========================================================================
# the contamination matrix
# ===========================================================================


def test_back_to_back_runs_do_not_contaminate(tmp_path):
    run_a = _run(
        tmp_path,
        "run_a",
        seed=1001,
        tm_port=8000,
        nav_pool=POOL_A,
        frames=[1, 2, 3],
        sensor_actor_id=11,
    )
    run_b = _run(
        tmp_path,
        "run_b",
        seed=2002,
        tm_port=8000,
        nav_pool=POOL_B,
        frames=[101, 102, 103],
        sensor_actor_id=22,
    )

    # -- TM ownership ------------------------------------------------------
    # Run A's claim was released, so B could take the same port. This is the
    # proof that A left no ownership behind: had A leaked, B's acquire would
    # have raised TRAFFIC_MANAGER_MULTIPLE_MASTERS before reaching here.
    assert run_a["tm_port"] == run_b["tm_port"] == 8000
    assert run_a["owner_token"] != run_b["owner_token"]
    assert run_a["tm_session_closed"] is True
    assert run_b["tm_session_closed"] is True
    assert str(8000) not in run_a["master_registry_after_cleanup"]

    # -- scenario actors --------------------------------------------------
    for run in (run_a, run_b):
        assert run["controlled_walker_count"] == 2, (
            f"{run['label']}: both walkers must be genuinely controlled"
        )
        assert run["clean_after_cleanup"] is True
        assert run["world"].live_walkers() == []
        assert run["world"].live_controllers() == []

    # -- callbacks / writer work / frame ids ------------------------------
    assert run_a["callback_frame_ids"] == [1, 2, 3]
    assert run_b["callback_frame_ids"] == [101, 102, 103]
    assert set(run_a["callback_frame_ids"]).isdisjoint(run_b["callback_frame_ids"])
    for run in (run_a, run_b):
        assert run["drain_state"] == "WRITER_DRAIN_PASS"
        assert run["drain_pending"] == 0

    # -- walker destinations ----------------------------------------------
    assert run_a["walker_destinations"] != run_b["walker_destinations"]
    assert set(run_a["walker_destinations"]).isdisjoint(run_b["walker_destinations"])
    assert run_a["scenario_manifest_sha256"] != run_b["scenario_manifest_sha256"]

    # -- seed identity ----------------------------------------------------
    assert run_a["seed_tree_sha256"] != run_b["seed_tree_sha256"]
    assert run_a["tm_seed"] != run_b["tm_seed"]


def test_run_b_does_not_inherit_run_a_nav_pool(tmp_path):
    """B's walker positions must come from B's pool only."""
    run_a = _run(
        tmp_path, "a", seed=1001, tm_port=8000, nav_pool=POOL_A,
        frames=[1], sensor_actor_id=11,
    )
    run_b = _run(
        tmp_path, "b", seed=2002, tm_port=8000, nav_pool=POOL_B,
        frames=[101], sensor_actor_id=12,
    )

    b_xs = {x for x, _y in run_b["walker_destinations"]}
    a_xs = {x for x, _y in run_a["walker_destinations"]}
    assert b_xs, "run B must have planned destinations"
    assert b_xs.isdisjoint(a_xs)
    assert b_xs <= {90.0, 92.0}


def test_run_b_does_not_see_run_a_frame_ids_in_its_recorder(tmp_path):
    """Each recorder's frame accounting is independent."""
    run_a = _run(
        tmp_path, "a", seed=1001, tm_port=8000, nav_pool=POOL_A,
        frames=[1, 2], sensor_actor_id=11,
    )
    run_b = _run(
        tmp_path, "b", seed=2002, tm_port=8000, nav_pool=POOL_B,
        frames=[50, 60, 70], sensor_actor_id=12,
    )

    b_ids = run_b["recorder"].backpressure_report()["callback_frame_ids"]["cam"]
    assert b_ids == [50, 60, 70]
    for leaked in (1, 2):
        assert leaked not in b_ids
    a_ids = run_a["recorder"].backpressure_report()["callback_frame_ids"]["cam"]
    assert a_ids == [1, 2]


def test_global_rng_is_not_leaked_between_runs(tmp_path):
    """A leak in the PROCESS-GLOBAL generator is invisible to seed-tree checks."""

    def _expected_draws(seed_value: int) -> list[float]:
        random.seed(seed_value)
        return [random.random() for _ in range(5)]

    # Seed the global generator to a known state, then run B.
    random.seed(4242)
    expected = [random.random() for _ in range(5)]

    random.seed(4242)
    _run(
        tmp_path, "b", seed=2002, tm_port=8000, nav_pool=POOL_B,
        frames=[1, 2], sensor_actor_id=12,
    )
    actual = [random.random() for _ in range(5)]

    assert actual == expected, (
        "the run consumed or reseeded the process-global RNG; governed runs must "
        "use owned RNG instances only"
    )
    # Sanity: the comparison is meaningful.
    assert _expected_draws(4242) == expected
    assert _expected_draws(9999) != expected


def test_carla_nav_randomness_is_never_reached_in_governed_runs(tmp_path):
    """_WalkerWorld raises if CARLA-side randomness is consulted."""

    class _ExplodingWorld(_WalkerWorld):
        def get_random_location_from_navigation(self):
            raise AssertionError(
                "CARLA-side nav randomness is not governed by the Python seed tree"
            )

    world = _ExplodingWorld(POOL_B)
    rng = random.Random(7)
    manifest = tms.build_walker_scenario_manifest(
        world, rng=rng, seed_tree_branch="scenario", count=2
    )
    assert manifest["ungoverned_entry_count"] == 0
    for entry in manifest["entries"]:
        result = tms.build_controlled_walker(
            world, None, entry["blueprint"],
            controller_bp=entry["controller_blueprint"], rng=rng,
            walker_index=entry["walker_index"],
            spawn_location=entry["spawn_transform"],
            destination_location=entry["destination_transform"],
            spawn_provenance=entry["spawn_provenance"],
            destination_provenance=entry["destination_provenance"],
            scenario_manifest_sha256=manifest["scenario_manifest_sha256"],
        )
        assert result["controlled"] is True
        assert result["position_governed"] is True


def test_same_inputs_reproduce_identical_run_state(tmp_path):
    """Determinism: two identical runs must produce identical governed state."""

    def _governed_summary(seed_value, pool):
        state = _run(
            tmp_path, f"r{seed_value}", seed=seed_value, tm_port=8000,
            nav_pool=pool, frames=[1, 2], sensor_actor_id=7,
        )
        return {
            "seed_tree_sha256": state["seed_tree_sha256"],
            "scenario_manifest_sha256": state["scenario_manifest_sha256"],
            "walker_destinations": state["walker_destinations"],
            "callback_frame_ids": state["callback_frame_ids"],
            "drain_state": state["drain_state"],
        }

    first = _governed_summary(3003, POOL_B)
    second = _governed_summary(3003, POOL_B)
    assert first == second


def test_tm_ledger_is_detached_on_close(tmp_path):
    """A closed session must not leave actors claiming governed ownership."""
    session = tms.TrafficManagerSession(tm_port=8000, seed=1001, session_id="run_a")
    session.acquire(_FakeClient(handle=_FakeTM(port=8000)))
    actor = _FakeActor("veh_1")
    session.record_actor(actor, policies={"max_speed": 1.4})

    assert session.actor_ledger()[0]["owner_session_id"] == "run_a"

    session.close()

    ledger = session.actor_ledger()
    assert ledger, "the ledger retains its rows"
    for row in ledger:
        assert row["owner_session_id"] is None
        assert row["detached"] is True
    assert actor.autopilot_calls == [(False, 8000)]
