"""Task 05 acceptance tests: connection ladder, TM ledger, weather, actors/routes.

Covers T-CONN-01..08, T-TM-01..06, T-WX-01..04, T-OWNER-* and T-ACTOR-*.

Offline: the CARLA world object is a fake; ``carla`` is never imported because
``apply_weather`` imports it lazily only when a real world is written.
"""

from __future__ import annotations

import pytest

from ultimate_pipeline.gui.runtime.actors import ActorCatalog, RouteSpec, SpawnPoint
from ultimate_pipeline.gui.runtime.connection import (
    ConnectStage,
    ConnectionProfile,
    confirm_destructive,
    connect,
)
from ultimate_pipeline.gui.runtime.traffic_manager import (
    AUTOPILOT_NOTE,
    TM_DECLARED_ONLY,
    TM_READABLE,
    TM_SETTERS,
    TrafficManagerLedger,
    WriteState,
    apply_global,
    apply_vehicle,
    detach_autopilot,
)
from ultimate_pipeline.gui.runtime.weather import (
    READBACK_TOLERANCE,
    WEATHER_GOVERNED_FIELDS,
    WEATHER_RANGES,
    apply_weather,
)
from ultimate_pipeline.gui.session.actor_registry import OwnedActorRegistry


# ---------------------------------------------------------------- fakes
class FakeMaps:
    def __init__(self, state, value=None, reason=""):
        self.state, self.value, self.reason = state, value, reason


class FakeBackend:
    def __init__(self, *, version="0.9.16", probe_ok=True, maps=None,
                 version_raises=False, has_canary=True):
        self.version = version
        self.probe_ok = probe_ok
        self.maps = maps if maps is not None else FakeMaps("AVAILABLE", ["Town01"])
        self.version_raises = version_raises
        if not has_canary:
            self.attach_sensor = None

    def probe(self, host, port, timeout_s):
        from ultimate_pipeline.gui.results import Result
        return Result.success("ok") if self.probe_ok else Result.failure("refused")

    def server_version(self):
        if self.version_raises:
            raise RuntimeError("swallowed upstream")
        return self.version

    def available_maps(self):
        from ultimate_pipeline.gui.results import Tri
        if self.maps.state == "AVAILABLE":
            return Tri.available_value(self.maps.value)
        if self.maps.state == "EMPTY":
            return Tri.empty(self.maps.reason)
        return Tri.unsupported(self.maps.reason)


class FakeTM:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __getattr__(self, name):
        if name.startswith("set_") or name in ("auto_lane_change", "ignore_lights",
                                               "ignore_signs", "ignore_walkers",
                                               "randomize_seed"):
            def call(*args):
                if name in self.fail:
                    raise RuntimeError(f"{name} refused")
                self.calls.append((name, args))
            return call
        raise AttributeError(name)


class FakeActor:
    def __init__(self):
        self.destroyed = False

    def is_alive(self):
        return not self.destroyed

    def destroy(self):
        self.destroyed = True


class Readback:
    def __init__(self, **kw):
        for key, value in kw.items():
            setattr(self, key, value)


# ================================================================= T-CONN
def test_T_CONN_01_full_ladder_succeeds_and_reports_all_five_stages():
    result = connect(FakeBackend(), tick_authority=None)
    assert result.ok is True
    stages = [s["stage"] for s in result.unwrap()["stages"]]
    assert stages == [s.value for s in ConnectStage]
    assert result.unwrap()["connected"] is True


def test_T_CONN_02_rpc_port_failure_blocks_the_ladder():
    result = connect(FakeBackend(probe_ok=False))
    assert result.ok is False
    assert "RPC port" in result.reason


def test_T_CONN_03_version_mismatch_is_a_gate_not_a_swallowed_warning():
    result = connect(FakeBackend(version="0.9.15"),
                     ConnectionProfile(allow_version_mismatch=False))
    assert result.ok is False
    assert result.error_class == "BlockedExternal"
    assert "version mismatch" in result.reason.lower()


def test_T_CONN_04_version_mismatch_can_be_accepted_explicitly():
    result = connect(FakeBackend(version="0.9.15"),
                     ConnectionProfile(allow_version_mismatch=True))
    assert result.ok is True
    api = [s for s in result.unwrap()["stages"] if s["stage"] == "API_VERSION"][0]
    assert api["requires_confirmation"] is True


def test_T_CONN_05_missing_version_is_never_treated_as_a_pass():
    raising = connect(FakeBackend(version_raises=True))
    assert raising.ok is False
    empty = connect(FakeBackend(version=None))
    assert empty.ok is False
    assert "no version" in empty.reason.lower()


def test_T_CONN_06_map_identity_empty_blocks_and_unsupported_is_not_a_pass():
    empty = connect(FakeBackend(maps=FakeMaps("EMPTY", reason="no maps")))
    assert empty.ok is False and "no maps" in empty.reason

    unsupported = connect(FakeBackend(maps=FakeMaps("PROBE_UNSUPPORTED", reason="stub backend")))
    assert unsupported.ok is True  # connection continues
    stage = [s for s in unsupported.unwrap()["stages"] if s["stage"] == "MAP_IDENTITY"][0]
    assert stage["unsupported"] is True and stage["ok"] is False


def test_T_CONN_07_tick_authority_readiness_is_reported():
    class SharedOnly:
        may_mutate = False

    result = connect(FakeBackend(), tick_authority=SharedOnly())
    stage = [s for s in result.unwrap()["stages"] if s["stage"] == "TICK_AUTHORITY"][0]
    assert stage["ok"] is False
    assert "SHARED_READONLY" in stage["detail"]


def test_T_CONN_08_destructive_actions_require_typed_confirmation():
    ok, unconfirmed = confirm_destructive(["kill_stuck_carla", "rmtree_carlaue4_dirs"])
    assert ok is True and unconfirmed == []
    ok2, unconfirmed2 = confirm_destructive(["rmtree_everything"])
    assert ok2 is False and unconfirmed2 == ["rmtree_everything"]

    refused = connect(FakeBackend(), destructive_confirmed=["rmtree_everything"])
    assert refused.ok is False


# ================================================================= T-TM
def test_T_TM_01_eleven_setters_and_only_five_are_readable():
    assert len(TM_SETTERS) == 11
    assert len(TM_READABLE) == 5
    assert len(TM_DECLARED_ONLY) == 3


def test_T_TM_02_global_write_without_port_ownership_is_declined():
    ledger = TrafficManagerLedger()
    result = apply_global(ledger, FakeTM(), {"auto_lane_change": True})
    assert result.ok is False
    assert ledger.by_state(WriteState.DECLINED)
    assert "ownership" in result.reason


def test_T_TM_03_ledger_never_reports_confirmed():
    ledger = TrafficManagerLedger(owner_token="gui", port=8000)
    apply_global(ledger, FakeTM(), {
        "auto_lane_change": True,
        "set_distance_to_leading_vehicle": 3.5,
        "set_percentage_speed_difference": 20.0,
    })
    assert ledger.confirmed_count() == 0
    states = {r.state for r in ledger.records}
    assert states <= {WriteState.REQUESTED, WriteState.WRITE_ONLY,
                      WriteState.UNVERIFIED, WriteState.FAILED}
    assert WriteState.REQUESTED != "CONFIRMED"
    assert "no getter" in ledger.provenance()


def test_T_TM_04_failed_setter_is_recorded_as_failed_not_silently_dropped():
    ledger = TrafficManagerLedger(owner_token="gui")
    result = apply_global(ledger, FakeTM(fail={"auto_lane_change"}), {"auto_lane_change": True})
    assert result.ok is True  # the call itself completed
    assert ledger.by_state(WriteState.FAILED)
    assert ledger.records[0].detail.startswith("RuntimeError")


def test_T_TM_05_per_vehicle_is_actor_scoped_and_refuses_unowned_actors():
    ledger = TrafficManagerLedger(owner_token="gui")
    tm = FakeTM()
    refused = apply_vehicle(ledger, tm, 999, {"auto_lane_change": True}, owned_actor_ids=[1])
    assert refused.ok is False
    assert ledger.by_state(WriteState.DECLINED)

    ok = apply_vehicle(ledger, tm, 1, {"auto_lane_change": True}, owned_actor_ids=[1])
    assert ok.ok is True
    assert any(r.scope == "vehicle" and r.target == "1" for r in ledger.records)


def test_T_TM_06_autopilot_detach_is_not_tm_global_restore():
    ledger = TrafficManagerLedger(owner_token="gui")
    tm = FakeTM()
    result = detach_autopilot(tm, 7, owned_actor_ids=[7])
    assert result.ok is True
    assert "NOT a restore" in result.unwrap()["note"]
    assert "cannot be read back" in AUTOPILOT_NOTE
    assert detach_autopilot(tm, 8, owned_actor_ids=[7]).ok is False


# ================================================================= T-WX
def test_T_WX_01_fourteen_governed_fields_are_defined():
    assert len(WEATHER_GOVERNED_FIELDS) == 14
    assert len(set(WEATHER_GOVERNED_FIELDS)) == 14


def test_T_WX_02_unknown_field_is_refused_not_ignored():
    result = apply_weather(object(), {"not_a_field": 1})
    assert result.ok is False
    assert "not governed" in result.reason


def test_T_WX_03_out_of_range_values_are_rejected_and_they_never_reach_the_world():
    class ExplodingWorld:
        def set_weather(self, params):
            raise AssertionError("world must not be written with invalid values")

    result = apply_weather(ExplodingWorld(), {"cloudiness": 500.0})
    assert result.ok is False
    statuses = result.value["fields"]
    assert statuses[0]["status"] == "OUT_OF_RANGE"
    assert "outside [0.0, 100.0]" in statuses[0]["detail"]


def test_T_WX_04_readback_mismatch_is_reported_not_called_applied():
    class FakeWorld:
        def __init__(self):
            self.written = None

        def set_weather(self, parameters):
            self.written = parameters

    world = FakeWorld()
    requested = {"cloudiness": 40.0, "fog_density": 5.0}
    # exact readback -> applied
    exact = Readback(cloudiness=40.0, fog_density=5.0)
    ok = apply_weather(world, requested, readback=exact, parameters_factory=dict)
    assert ok.ok is True
    assert world.written == requested

    # mismatch -> failure, never success
    off = Readback(cloudiness=41.0, fog_density=5.0)
    bad = apply_weather(world, requested, readback=off, parameters_factory=dict)
    assert bad.ok is False
    assert bad.error_class == "WeatherReadbackMismatch"
    statuses = {s["field"]: s for s in bad.value["fields"]}
    assert statuses["cloudiness"]["status"] == "READBACK_MISMATCH"

    # within tolerance -> still applied
    tiny = Readback(cloudiness=40.0 + READBACK_TOLERANCE / 2, fog_density=5.0)
    assert apply_weather(world, requested, readback=tiny, parameters_factory=dict).ok is True


# ================================================================= actors / routes
def test_spawn_preview_reports_conflicts_and_never_mutates():
    catalog = ActorCatalog(OwnedActorRegistry())
    point = SpawnPoint(10.0, 20.0, 0.5)
    occupied = [(1, SpawnPoint(10.0, 20.0, 0.5)), (2, SpawnPoint(10.5, 20.0, 0.5))]
    preview = catalog.preview_spawn("vehicle.tesla.model3", point, occupied)
    assert preview.safe is False
    assert preview.occupied_by == 1
    assert 2 in preview.too_close_to
    assert len(catalog.registry) == 0, "preview must not spawn anything"

    clear = catalog.preview_spawn("vehicle.tesla.model3", SpawnPoint(100.0, 100.0, 0.0), occupied)
    assert clear.safe is True


def test_routes_are_refused_for_unowned_actors():
    registry = OwnedActorRegistry()
    catalog = ActorCatalog(registry)
    spec = RouteSpec((SpawnPoint(0, 0, 0), SpawnPoint(1, 1, 0)))
    assigned = []
    refused = catalog.assign_route(spec, [42], lambda *a: assigned.append(a))
    assert refused.ok is False
    assert assigned == []

    registry.register(7, FakeActor())
    ok = catalog.assign_route(spec, [7], lambda *a: assigned.append(a))
    assert ok.ok is True
    assert assigned and assigned[0][0] == 7


def test_external_actors_are_preserved_through_the_catalog():
    registry = OwnedActorRegistry()
    registry.register_external(999)
    catalog = ActorCatalog(registry)
    assert catalog.external_catalog() == [999]
    assert catalog.owned_catalog() == []
    assert registry.destroy(999).ok is False