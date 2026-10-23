#!/usr/bin/env python3
"""
P0-3 executable negative controls for the governed capture transaction.

Fault injection at EVERY critical boundary, asserting:
* no residual owned actors
* no leaked listeners
* verified restoration (readback), or explicit UNOBSERVABLE
* a failed restoration invalidates the capture

Uses synthetic fakes only. No CARLA import.
"""

from typing import Any, Dict, List, Optional

import pytest

from ultimate_pipeline.perception.capture_transaction import (
    CRITICAL_STAGES,
    READBACK_FAILED,
    READBACK_VERIFIED,
    UNOBSERVABLE,
    CaptureTransaction,
    run_governed_capture,
)


class FakeWorld:
    def __init__(self):
        self.settings: Dict[str, Any] = {
            "synchronous_mode": False,
            "fixed_delta_seconds": 0.0,
        }
        self.applied: List[Dict[str, Any]] = []

    def apply_settings(self, settings: Any) -> None:
        payload = dict(getattr(settings, "_payload", {}))
        self.settings.update(payload)
        self.applied.append(payload)

    def snapshot(self) -> Dict[str, Any]:
        return dict(self.settings)

    def readback(self) -> Dict[str, Any]:
        return dict(self.settings)


class FakeTM:
    def __init__(self):
        self.synchronous_mode = False
        self.calls: List[bool] = []

    def set_synchronous_mode(self, enabled: bool) -> None:
        self.synchronous_mode = bool(enabled)
        self.calls.append(bool(enabled))

    def snapshot(self) -> Dict[str, Any]:
        return {"synchronous_mode": self.synchronous_mode}

    def readback(self) -> Dict[str, Any]:
        return {"synchronous_mode": self.synchronous_mode}


class FakeActor:
    def __init__(self, aid: str):
        self.aid = aid
        self.destroyed = False


class FakeSensor:
    def __init__(self, sid: str):
        self.sid = sid
        self.listeners: List[str] = []


def _txn(world=None, tm=None, destroy_ok=True, detach_ok=True, quarantine=True,
         readback_settings=True, readback_weather=True, readback_tm=True):
    world = world or FakeWorld()
    tm = tm or FakeTM()
    destroyed: List[FakeActor] = []
    detached: List[str] = []
    quarantined: List[bool] = []

    def destroy(actor: Any) -> None:
        if not destroy_ok:
            raise RuntimeError("destroy refused")
        actor.destroyed = True
        destroyed.append(actor)

    def detach(sensor: Any, callback_id: str) -> None:
        if not detach_ok:
            raise RuntimeError("detach refused")
        if callback_id in sensor.listeners:
            sensor.listeners.remove(callback_id)
        detached.append(callback_id)

    def quarantine() -> None:
        quarantined.append(True)

    txn = CaptureTransaction(
        world=world,
        traffic_manager=tm,
        get_weather=lambda: "WEATHER_BEFORE",
        set_weather=lambda w: setattr(world, "weather", w),
        destroy_actor=destroy,
        detach_listener=detach,
        quarantine_staging=quarantine,
        readback_settings=world.readback if readback_settings else None,
        readback_weather=(lambda: getattr(world, "weather", None)) if readback_weather else None,
        readback_tm=tm.readback if readback_tm else None,
        settings_snapshot=world.snapshot,
        tm_snapshot=tm.snapshot,
        weather_snapshot=lambda: "WEATHER_BEFORE",
    )
    return txn, world, tm, destroyed, detached, quarantined


def _stages(txn, world, tm, fault_at=None, extra=None):
    """Build the standard stage map, optionally faulting at one stage."""
    ego = FakeActor("ego")
    sensor_a = FakeSensor("cam_a")
    sensor_b = FakeSensor("cam_b")
    stages: Dict[str, Any] = {}

    def fault(name):
        if fault_at == name:
            raise RuntimeError(f"injected fault at {name}")

    def s_world():
        fault("world_settings")
        txn.apply_world_settings({"synchronous_mode": True, "fixed_delta_seconds": 0.05})

    def s_weather():
        fault("weather")
        txn.apply_weather("WEATHER_AFTER")

    def s_tm():
        fault("traffic_manager")
        txn.apply_traffic_manager(synchronous_mode=True)

    def s_ego():
        fault("ego_spawn")
        txn.own_actor(ego, "ego", "vehicle")

    def s_sensor1():
        fault("first_sensor_spawn")
        txn.own_actor(sensor_a, "cam_a", "sensor")

    def s_sensor2():
        fault("second_sensor_spawn")
        txn.own_actor(sensor_b, "cam_b", "sensor")

    def s_listener():
        fault("listener_attachment")
        sensor_a.listeners.append("cb_a")
        txn.own_listener(sensor_a, "cb_a")

    def s_tick():
        fault("first_tick")

    def s_write():
        fault("dataset_write")

    def s_teardown():
        fault("teardown")

    stages.update({
        "world_settings": s_world,
        "weather": s_weather,
        "traffic_manager": s_tm,
        "ego_spawn": s_ego,
        "first_sensor_spawn": s_sensor1,
        "second_sensor_spawn": s_sensor2,
        "listener_attachment": s_listener,
        "first_tick": s_tick,
        "dataset_write": s_write,
        "teardown": s_teardown,
    })
    if extra:
        stages.update(extra)
    return stages


def _assert_clean(result, world, tm, destroyed, detached, quarantined):
    """No residual owned actors, no leaked listeners, restoration verified."""
    assert result.rolled_back is True, "rollback did not run"
    assert all(a.destroyed for a in result.actors), f"residual actors: {result.actors}"
    assert all(l.detached for l in result.listeners), f"leaked listeners: {result.listeners}"
    assert result.staging_quarantined is True, "staging not quarantined"
    assert result.rollback_errors == [], f"rollback errors: {result.rollback_errors}"
    assert result.authoritative is False, "failed capture must not be authoritative"
    # readback verification
    if "world_settings" in result.restorations:
        ws = result.restorations["world_settings"]
        assert ws.readback == READBACK_VERIFIED, ws.to_dict()
        assert ws.restored is True
    assert tm.synchronous_mode is False, "TM not restored"


def test_success_path_is_authoritative():
    txn, world, tm, destroyed, detached, quarantined = _txn()
    result = run_governed_capture(txn, _stages(txn, world, tm))
    assert result.authoritative is True
    assert result.failed_stage is None
    assert result.rolled_back is False
    print("PASS: transaction_success_path_authoritative")


@pytest.mark.parametrize("stage", [
    "world_settings", "weather", "traffic_manager", "ego_spawn",
    "first_sensor_spawn", "second_sensor_spawn", "listener_attachment",
    "first_tick", "dataset_write", "teardown",
])
def test_rollback_at_every_critical_boundary(stage):
    txn, world, tm, destroyed, detached, quarantined = _txn()
    result = run_governed_capture(txn, _stages(txn, world, tm, fault_at=stage))
    assert result.failed_stage == stage, result.to_dict()
    _assert_clean(result, world, tm, destroyed, detached, quarantined)
    print(f"PASS: rollback_at_{stage}")


def test_restoration_readback_mismatch_invalidates():
    """A world whose readback disagrees with the pre-state invalidates."""
    world = FakeWorld()

    def bad_readback():
        d = dict(world.settings)
        d["fixed_delta_seconds"] = 0.033  # not what we set
        return d

    txn, world, tm, destroyed, detached, quarantined = _txn(world=world)
    txn._readback_settings = bad_readback
    result = run_governed_capture(txn, _stages(txn, world, tm, fault_at="first_tick"))
    assert result.rolled_back is True
    ws = result.restorations["world_settings"]
    assert ws.readback == READBACK_FAILED
    assert result.authoritative is False
    assert any("readback" in r for r in result.invalidating_reasons), result.invalidating_reasons
    print("PASS: restoration_readback_mismatch_invalidates")


def test_unobservable_restoration_is_not_claimed_restored():
    """No snapshot capability -> UNOBSERVABLE, not silently 'restored'."""
    txn, world, tm, destroyed, detached, quarantined = _txn()
    txn._settings_snapshot = None
    result = run_governed_capture(txn, _stages(txn, world, tm, fault_at="first_tick"))
    ws = result.restorations["world_settings"]
    assert ws.readback == UNOBSERVABLE
    assert ws.restored is False
    assert result.authoritative is False
    assert "world_settings_unobservable" in result.invalidating_reasons
    print("PASS: unobservable_restoration_not_claimed_restored")


def test_no_readback_capability_is_unobservable():
    txn, world, tm, destroyed, detached, quarantined = _txn(readback_settings=False)
    result = run_governed_capture(txn, _stages(txn, world, tm, fault_at="first_tick"))
    ws = result.restorations["world_settings"]
    assert ws.readback == UNOBSERVABLE
    assert result.authoritative is False
    print("PASS: no_readback_capability_unobservable")


def test_listener_leak_is_detected():
    txn, world, tm, destroyed, detached, quarantined = _txn(detach_ok=False)
    result = run_governed_capture(txn, _stages(txn, world, tm, fault_at="first_tick"))
    assert result.rollback_errors, "detach failure must be recorded"
    assert result.authoritative is False
    print("PASS: listener_leak_detected")


def test_residual_actor_is_detected():
    txn, world, tm, destroyed, detached, quarantined = _txn(destroy_ok=False)
    result = run_governed_capture(txn, _stages(txn, world, tm, fault_at="first_tick"))
    assert result.rollback_errors, "destroy failure must be recorded"
    assert result.authoritative is False
    print("PASS: residual_actor_detected")


def test_weather_restoration_readback():
    txn, world, tm, destroyed, detached, quarantined = _txn()
    result = run_governed_capture(txn, _stages(txn, world, tm, fault_at="first_tick"))
    w = result.restorations["weather"]
    assert w.readback == READBACK_VERIFIED, w.to_dict()
    print("PASS: weather_restoration_readback")


def test_tm_restoration_readback():
    txn, world, tm, destroyed, detached, quarantined = _txn()
    result = run_governed_capture(txn, _stages(txn, world, tm, fault_at="first_tick"))
    t = result.restorations["traffic_manager"]
    assert t.readback == READBACK_VERIFIED, t.to_dict()
    print("PASS: tm_restoration_readback")


def test_all_critical_stages_enumerated():
    for stage in ("world_settings", "weather", "traffic_manager", "ego_spawn",
                  "first_sensor_spawn", "second_sensor_spawn",
                  "listener_attachment", "first_tick", "dataset_write",
                  "teardown", "restoration"):
        assert stage in CRITICAL_STAGES, f"missing critical stage {stage}"
    print("PASS: all_critical_stages_enumerated")


if __name__ == "__main__":
    test_success_path_is_authoritative()
    for stage in ("world_settings", "weather", "traffic_manager", "ego_spawn",
                  "first_sensor_spawn", "second_sensor_spawn",
                  "listener_attachment", "first_tick", "dataset_write", "teardown"):
        test_rollback_at_every_critical_boundary(stage)
    test_restoration_readback_mismatch_invalidates()
    test_unobservable_restoration_is_not_claimed_restored()
    test_no_readback_capability_is_unobservable()
    test_listener_leak_is_detected()
    test_residual_actor_is_detected()
    test_weather_restoration_readback()
    test_tm_restoration_readback()
    test_all_critical_stages_enumerated()
    print("\n=== P0-3 TRANSACTION ROLLBACK SUMMARY ===")
    print("Verified: rollback at 10 critical boundaries + restoration readback")
    print("mismatch, unobservable fields, listener leaks, residual actors.")
