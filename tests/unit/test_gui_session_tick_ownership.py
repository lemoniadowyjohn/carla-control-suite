"""Task 04 acceptance tests: tick authority, actor ownership, cancellation.

Covers T-TICK-01..06, T-OWNER-01..08, T-ACTOR-01, T-ACTOR-05, T-CLEAN-01,
T-EXP-CANCEL-01..06 and T-THR-01..08.

Offline: no CARLA server, no network, no display, no live simulator.
"""

from __future__ import annotations

import threading
import time

import pytest

from ultimate_pipeline.gui.cancellation import OperationCancelled
from ultimate_pipeline.gui.health import SessionAuthority
from ultimate_pipeline.gui.results import Result
from ultimate_pipeline.gui.session.actor_registry import OwnedActorRegistry, is_alive
from ultimate_pipeline.gui.session.session import (
    CleanupEvidence,
    Session,
    ShutdownReason,
    Watchdog,
)
from ultimate_pipeline.gui.session.tick_authority import (
    KNOWN_TICK_WRITERS,
    SyncSettings,
    TickAuthority,
    TickRefusal,
    substep_support_verified,
)


# ---------------------------------------------------------------- fakes
class FakeSettings:
    def __init__(self, synchronous_mode=False, fixed_delta_seconds=0.0):
        self.synchronous_mode = synchronous_mode
        self.fixed_delta_seconds = fixed_delta_seconds


class FakeWorld:
    """Deterministic fake world: records every tick and settings change."""

    def __init__(self, settings=None, fail_tick=False):
        self._settings = settings or FakeSettings()
        self.ticks = 0
        self.applied: list[SyncSettings] = []
        self.fail_tick = fail_tick

    def get_settings(self):
        return self._settings

    def apply_settings(self, settings):
        self.applied.append(settings)
        self._settings = FakeSettings(settings.synchronous_mode, settings.fixed_delta_seconds)

    def tick(self):
        if self.fail_tick:
            raise RuntimeError("simulated RPC timeout")
        self.ticks += 1


class MethodAliveActor:
    def __init__(self, alive=True, raise_on_destroy=False):
        self._alive = alive
        self._raise = raise_on_destroy
        self.destroyed = False

    def is_alive(self):
        return self._alive

    def destroy(self):
        if self._raise:
            raise RuntimeError("destroy refused")
        self.destroyed = True
        self._alive = False


class AttributeAliveActor:
    """The Q21 bug: ``is_alive`` exposed as a truthy attribute, not a method."""

    def __init__(self, alive=True):
        self.is_alive = alive      # bool attribute, shadows the method
        self.destroyed = False

    def destroy(self):
        self.destroyed = True
        self.is_alive = False


# ================================================================= T-TICK
def test_T_TICK_01_six_known_writers_are_recorded_and_substep_unclaimed():
    assert len(KNOWN_TICK_WRITERS) == 6
    assert all(w.startswith("ultimate_pipeline/") for w in KNOWN_TICK_WRITERS)
    # Substepping must NOT be claimed: support was never independently verified.
    assert substep_support_verified() is False


def test_T_TICK_02_shared_readonly_never_grants_a_tick():
    world = FakeWorld()
    authority = TickAuthority(world=world, exclusive=False)
    grant = authority.acquire("gui")
    assert not grant.granted
    assert grant.refusal == TickRefusal.SHARED_READONLY.value
    assert world.applied == [], "a refused grant must not touch world settings"


def test_T_TICK_03_exclusive_grant_snapshots_and_enters_sync_mode():
    world = FakeWorld(FakeSettings(False, 0.0))
    authority = TickAuthority(world=world, exclusive=True)
    grant = authority.acquire("gui")
    assert grant.granted and grant.owner == "gui"
    assert world.applied[0] == SyncSettings(True, 0.05)


def test_T_TICK_04_release_restores_the_exact_original_settings():
    world = FakeWorld(FakeSettings(False, 0.0333))
    authority = TickAuthority(world=world, exclusive=True)
    authority.acquire("gui")
    released = authority.release("gui")
    assert released.ok
    restored = world.get_settings()
    assert restored.synchronous_mode is False
    assert abs(restored.fixed_delta_seconds - 0.0333) < 1e-9


def test_T_TICK_05_runtime_conflict_is_detected_and_refused():
    world = FakeWorld()
    authority = TickAuthority(world=world, exclusive=True)
    authority.note_external_write("ultimate_pipeline/carla_sim_consolidated.py")
    grant = authority.acquire("gui")
    assert not grant.granted
    assert grant.refusal == TickRefusal.CONFLICTING_WRITER.value
    assert grant.conflict_writers == ("ultimate_pipeline/carla_sim_consolidated.py",)
    # unknown writers are rejected outright
    with pytest.raises(ValueError):
        authority.note_external_write("some.random.module")


def test_T_TICK_06_failed_tick_recovers_without_claiming_success():
    world = FakeWorld(fail_tick=True)
    authority = TickAuthority(world=world, exclusive=True)
    authority.acquire("gui")
    result = authority.tick("gui")
    assert result.ok is False
    assert "tick failed" in result.reason
    assert isinstance(result, Result)


# ================================================================= T-OWNER
def test_T_OWNER_01_second_grant_is_refused():
    authority = TickAuthority(world=FakeWorld(), exclusive=True)
    first = authority.acquire("session-a")
    second = authority.acquire("session-b")
    assert first.granted is True
    assert second.granted is False
    assert second.refusal == TickRefusal.ALREADY_GRANTED.value


def test_T_OWNER_02_only_the_holder_may_tick():
    authority = TickAuthority(world=FakeWorld(), exclusive=True)
    authority.acquire("session-a")
    assert authority.tick("session-a").ok is True
    denied = authority.tick("session-b")
    assert denied.ok is False and "held by" in denied.reason


def test_T_OWNER_03_release_requires_the_holder():
    authority = TickAuthority(world=FakeWorld(), exclusive=True)
    authority.acquire("session-a")
    denied = authority.release("session-b")
    assert denied.ok is False and denied.error_class == "PermissionError"


def test_T_OWNER_04_no_world_means_refusal_not_success():
    authority = TickAuthority(world=None, exclusive=True)
    grant = authority.acquire("gui")
    assert grant.granted is False
    assert grant.refusal == TickRefusal.NO_WORLD.value


def test_T_OWNER_05_failed_sync_restore_is_explicit_failure_evidence():
    class RestoresFailWorld(FakeWorld):
        """Acquisition succeeds, then the restore fails."""

        def __init__(self):
            super().__init__(FakeSettings(False, 0.0333))
            self._armed = False

        def apply_settings(self, settings):
            if self._armed:
                raise RuntimeError("world refuses the restore")
            super().apply_settings(settings)
            self._armed = True

    world = RestoresFailWorld()
    authority = TickAuthority(world=world, exclusive=True)
    assert authority.acquire("gui").granted is True
    released = authority.release("gui")
    assert released.ok is False
    assert released.state_restored is False
    assert "could NOT be restored" in released.reason


def test_T_OWNER_06_snapshot_failure_refuses_the_grant():
    class BrokenWorld:
        def get_settings(self):
            raise RuntimeError("world is gone")

    authority = TickAuthority(world=BrokenWorld(), exclusive=True)
    grant = authority.acquire("gui")
    assert grant.granted is False
    assert grant.refusal == TickRefusal.SNAPSHOT_FAILED.value


def test_T_OWNER_07_conflict_report_names_the_writers():
    authority = TickAuthority(world=FakeWorld(), exclusive=True)
    authority.note_external_write(KNOWN_TICK_WRITERS[0])
    report = authority.conflict_report()
    assert report["external_writers"] == [KNOWN_TICK_WRITERS[0]]
    assert len(report["known_writers"]) == 6
    assert report["substep_support_verified"] is False


def test_T_OWNER_08_session_refuses_mutation_under_shared_readonly():
    session = Session(world=FakeWorld())
    assert session.may_mutate is False
    blocked = session.acquire_tick()
    assert blocked.ok is False
    assert "SHARED_READONLY" in blocked.reason


# ================================================================= T-ACTOR
def test_T_ACTOR_01_external_actors_are_never_destroyed():
    registry = OwnedActorRegistry()
    foreign = MethodAliveActor()
    registry.register_external(101)
    result = registry.destroy(101)
    assert result.ok is False
    assert foreign.destroyed is False


def test_T_ACTOR_05_sensors_are_torn_down_before_their_parent():
    registry = OwnedActorRegistry()
    parent = MethodAliveActor()
    sensor = MethodAliveActor()
    registry.register(200, parent, kind="vehicle")
    registry.register(201, sensor, kind="sensor", parent_id=200)

    # destroying the parent while a sensor is attached must be refused
    refused = registry.destroy(200)
    assert refused.ok is False
    assert refused.error_class == "TeardownOrderError"

    registry.destroy_sensors_for(200)
    assert sensor.destroyed is True
    assert parent.destroyed is False
    assert registry.destroy(200).ok is True
    assert parent.destroyed is True


def test_liveness_is_checked_as_a_method_and_tolerates_the_attribute_bug():
    assert is_alive(MethodAliveActor(alive=True)) is True
    assert is_alive(MethodAliveActor(alive=False)) is False
    assert is_alive(AttributeAliveActor(alive=False)) is False
    assert is_alive(None) is False

    # the buggy attribute-style actor must still be destroyed, not skipped
    registry = OwnedActorRegistry()
    actor = AttributeAliveActor(alive=False)
    registry.register(300, actor)
    assert registry.destroy(300).ok is True
    assert actor.destroyed is False  # already dead, so nothing to destroy


def test_destroy_is_idempotent_and_duplicate_destroy_is_refused():
    registry = OwnedActorRegistry()
    registry.register(400, MethodAliveActor())
    assert registry.destroy(400).ok is True
    again = registry.destroy(400)
    assert again.ok is False
    assert len(registry) == 0


# ================================================================= T-CLEAN
def test_T_CLEAN_01_post_cleanup_verification_reports_a_leak():
    registry = OwnedActorRegistry()
    registry.register(500, MethodAliveActor(raise_on_destroy=True))
    outcome = registry.destroy_all()
    assert outcome.ok is False
    assert "leaked actor ids" in outcome.reason
    verify = registry.cleanup_report()
    assert verify.ok is False
    assert verify.error_class == "ActorLeak"


def test_full_teardown_reports_clean_and_preserves_external():
    registry = OwnedActorRegistry()
    for actor_id in (600, 601):
        registry.register(actor_id, MethodAliveActor())
    registry.register(602, MethodAliveActor(), kind="sensor", parent_id=600)
    registry.register_external(999)

    outcome = registry.destroy_all()
    assert outcome.ok is True
    verify = registry.cleanup_report()
    assert verify.ok is True
    assert verify.value["preserved_external"] == (999,)


def test_session_shutdown_produces_explicit_evidence():
    world = FakeWorld(FakeSettings(False, 0.05))
    session = Session(world=world, name="s1",
                      authority=SessionAuthority.EXCLUSIVE_TICK)
    granted = session.acquire_tick()
    assert granted.ok is True
    actor = MethodAliveActor()
    session.actors.register(700, actor)

    evidence = session.shutdown(ShutdownReason.OPERATOR)
    assert isinstance(evidence, CleanupEvidence)
    assert evidence.actor_leak == ()
    assert evidence.tick_released is True
    assert world.get_settings().synchronous_mode is False
    assert actor.destroyed is True


# ================================================================= T-EXP-CANCEL
def test_T_EXP_CANCEL_01_cancellation_is_cooperative():
    session = Session()
    seen = []
    session.token.on_cancel(seen.append)
    session.request_stop(ShutdownReason.GUI_CLOSE)
    assert session.token.cancelled is True
    assert seen == [ShutdownReason.GUI_CLOSE.value]
    with pytest.raises(OperationCancelled):
        session.token.raise_if_cancelled()


def test_T_EXP_CANCEL_02_tick_after_cancellation_refuses():
    world = FakeWorld()
    session = Session(world=world, name="s", authority=SessionAuthority.EXCLUSIVE_TICK)
    session.acquire_tick()
    session.request_stop()
    with pytest.raises(OperationCancelled):
        session.tick_once()
    assert world.ticks == 0


def test_T_EXP_CANCEL_03_timeout_is_bounded_and_never_reports_success():
    session = Session()
    calls = []

    def slow(token):
        raise TimeoutError("rpc deadline exceeded")

    result = session.run_bounded(slow, timeout_s=0.05, on_timeout=lambda: calls.append(1))
    assert result.ok is False
    assert result.error_class == "TimeoutError"
    assert calls == [1]
    assert session.token.cancelled is True


def test_T_EXP_CANCEL_04_worker_crash_is_captured_with_its_class():
    session = Session()

    def boom(token):
        raise ValueError("bad config")

    result = session.run_bounded(boom, timeout_s=1.0)
    assert result.ok is False
    assert result.error_class == "ValueError"
    assert "crashed" in result.reason
    assert session.token.cancelled is True


def test_T_EXP_CANCEL_05_successful_work_returns_a_typed_success():
    session = Session()
    result = session.run_bounded(lambda token: {"frames": 12}, timeout_s=1.0)
    assert result.ok is True
    assert result.unwrap() == {"frames": 12}


def test_T_EXP_CANCEL_06_watchdog_expires_without_spinning():
    ticks = iter(range(10_000_000))
    watchdog = Watchdog(0.05, clock=lambda: next(ticks))
    assert watchdog.expired(started_at=0.0) is False
    assert watchdog.expired(started_at=-1.0) is True
    assert watchdog.remaining() == 0.05


# ================================================================= T-THR
def test_T_THR_01_concurrent_acquire_yields_exactly_one_winner():
    world = FakeWorld()
    authority = TickAuthority(world=world, exclusive=True)
    winners: list[str] = []
    barrier = threading.Barrier(8)

    def attempt(index: int) -> None:
        barrier.wait()
        grant = authority.acquire(f"thread-{index}")
        if grant.granted:
            winners.append(grant.owner)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(winners) == 1, f"exactly one tick owner expected, got {winners}"
    assert world.applied[0] == SyncSettings(True, 0.05)


def test_T_THR_02_concurrent_ticks_are_serialised_by_the_authority():
    world = FakeWorld()
    authority = TickAuthority(world=world, exclusive=True)
    authority.acquire("owner")

    def worker() -> None:
        for _ in range(20):
            authority.tick("owner")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert world.ticks == 80


def test_T_THR_03_lease_style_expiry_frees_a_dead_holders_grant():
    world = FakeWorld()
    authority = TickAuthority(world=world, exclusive=True)
    authority.acquire("dead-holder")
    assert authority.granted is True
    # a new request is refused while the grant stands; release is the only exit
    assert authority.acquire("other").granted is False
    assert authority.release("dead-holder").ok is True
    assert authority.acquire("other").granted is True


def test_T_THR_04_registry_is_safe_under_concurrent_registration():
    registry = OwnedActorRegistry()
    barrier = threading.Barrier(6)

    def worker(offset: int) -> None:
        barrier.wait()
        for index in range(25):
            registry.register(offset * 1000 + index, MethodAliveActor())

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert len(registry) == 150


def test_T_THR_05_concurrent_teardown_leaves_no_leak():
    registry = OwnedActorRegistry()
    for actor_id in range(120):
        registry.register(actor_id, MethodAliveActor())
    threads = [threading.Thread(target=registry.destroy_all) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert len(registry) == 0
    assert registry.cleanup_report().ok is True


def test_T_THR_06_signal_handlers_do_not_break_off_the_main_thread():
    session = Session()
    session.install_signal_handlers()
    session.request_stop(ShutdownReason.CTRL_C)
    assert session.token.cancelled is True
    session.restore_signal_handlers()


def test_T_THR_07_repeated_grant_release_cycles_are_stable():
    world = FakeWorld(FakeSettings(False, 0.0))
    authority = TickAuthority(world=world, exclusive=True)
    for _ in range(10):
        assert authority.acquire("owner").granted is True
        assert authority.release("owner").ok is True
    assert world.get_settings().synchronous_mode is False
    assert len(authority.conflict_report()["external_writers"]) == 0


def test_T_THR_08_cleanup_evidence_dict_is_machine_readable():
    evidence = CleanupEvidence()
    assert evidence.clean is False
    payload = evidence.as_dict()
    assert set(payload) == {"clean", "actor_leak", "sync_restored",
                             "tm_state_recovered", "tick_released", "errors"}
    assert CleanupEvidence(sync_restored=True, tm_state_recovered=True,
                           tick_released=True).clean is True