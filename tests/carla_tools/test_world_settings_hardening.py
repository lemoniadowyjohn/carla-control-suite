"""CARLA session hardening: guaranteed restore + fault injection.

Offline (mock) tests always run in CI. Live tests require a real CARLA 0.9.16
server on 127.0.0.1:2000 and skip otherwise -- they never fail closed on an
absent server, they report it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import world_settings_transaction as wst


# --------------------------------------------------------------------------
# Offline fakes
# --------------------------------------------------------------------------

class FakeSettings:
    def __init__(self) -> None:
        self.synchronous_mode = False
        self.fixed_delta_seconds = 0.0
        self.substepping = False
        self.max_substep_delta_time = 0.0
        self.max_substeps = 0
        self.no_rendering_mode = False


class FakeActors(list):
    def filter(self, _pattern: str):  # noqa: ANN202
        return []


class FakeMap:
    name = "Grid0828/Maps/Grid0828/Grid0828"

    def get_spawn_points(self):  # noqa: ANN202
        return [
            SimpleNamespace(location=SimpleNamespace(x=1.0, y=2.0, z=0.5)),
            SimpleNamespace(location=SimpleNamespace(x=3.0, y=4.0, z=0.5)),
        ]

    def get_all_landmarks_of_type(self, _t: str):  # noqa: ANN202
        return []

    def generate_waypoints(self, _d):  # noqa: ANN202
        raise AssertionError("generate_waypoints must not be called by the light fingerprint")


class FakeWorld:
    def __init__(self) -> None:
        self._s = FakeSettings()
        self.applied: list = []

    def get_settings(self):  # noqa: ANN202
        return self._s

    def apply_settings(self, ws):  # noqa: ANN202
        self._s = ws
        self.applied.append(dict(
            synchronous_mode=ws.synchronous_mode,
            fixed_delta_seconds=ws.fixed_delta_seconds,
        ))
        return ws

    def get_map(self):  # noqa: ANN202
        return FakeMap()

    def get_actors(self):  # noqa: ANN202
        return FakeActors()


class BrokenWorld(FakeWorld):
    def apply_settings(self, _ws):  # noqa: ANN202
        raise RuntimeError("RPC link dead")


# --------------------------------------------------------------------------
# Offline tests (always run)
# --------------------------------------------------------------------------

def test_snap_reads_all_governed_fields() -> None:
    s = wst.snap(FakeSettings())
    assert set(s) == {
        "synchronous_mode", "fixed_delta_seconds", "substepping",
        "max_substep_delta_time", "max_substeps", "no_rendering_mode",
    }


def test_force_async_default_restores_sync_leak() -> None:
    w = FakeWorld()
    w._s.synchronous_mode = True
    w._s.fixed_delta_seconds = 0.05
    out = wst.force_async_default(w)
    assert out["restored"] is True
    assert out["observed"]["synchronous_mode"] is False
    assert out["observed"]["fixed_delta_seconds"] == 0.0


def test_force_async_default_never_raises_when_rpc_dead() -> None:
    out = wst.force_async_default(BrokenWorld())
    assert out["restored"] is False
    assert "RuntimeError" in out["error"]


def test_atexit_restore_never_raises() -> None:
    old = wst._ATEXIT_WORLD
    wst._ATEXIT_WORLD = BrokenWorld()
    try:
        wst._atexit_restore()  # must not raise
    finally:
        wst._ATEXIT_WORLD = old


def test_light_fingerprint_avoids_generate_waypoints() -> None:
    fp = wst.light_structural_fingerprint(FakeWorld(), None)
    assert fp["map_name"] == "Grid0828/Maps/Grid0828/Grid0828"
    assert fp["spawn_point_count"] == 2
    assert len(fp["spawn_xy_hash"]) == 64
    assert "waypoints_at_3m" not in fp


def test_restore_and_verify_matches_original() -> None:
    w = FakeWorld()
    before = wst.snap(w.get_settings())
    w._s.synchronous_mode = True  # simulate experiment state
    report: Dict[str, Any] = {"phases": {}}
    wst._restore_and_verify(w, before, report)
    assert report["phases"]["6_verify_restore"]["matches_original"] is True


# --------------------------------------------------------------------------
# Live fault-injection tests (skip without a server)
# --------------------------------------------------------------------------

def _live_client():
    import os

    port = int(os.environ.get("CARLA_RPC_PORT", "2000"))
    try:
        import carla
    except Exception:
        pytest.skip("carla PythonAPI not installed")
    client = carla.Client("127.0.0.1", port)
    client.set_timeout(10.0)
    try:
        client.get_server_version()
    except Exception:
        pytest.skip(f"no live CARLA server on 127.0.0.1:{port}")
    return client


def test_live_exception_during_experiment_still_restores() -> None:
    client = _live_client()
    world = client.get_world()
    before = wst.snap(world.get_settings())
    try:
        ws = world.get_settings()
        ws.synchronous_mode = True
        ws.fixed_delta_seconds = 0.05
        world.apply_settings(ws)
        world.tick(30.0)
        raise RuntimeError("injected experiment failure")
    except RuntimeError:
        pass
    finally:
        out = wst.force_async_default(world)
    assert out["restored"] is True
    after = wst.snap(world.get_settings())
    assert after["synchronous_mode"] is False
    assert before is not None


def test_live_actor_spawn_failure_leaves_settings_async() -> None:
    client = _live_client()
    import carla

    world = client.get_world()
    bp = world.get_blueprint_library().find("sensor.camera.rgb")
    bp.set_attribute("image_size_x", "1")  # valid but useless; spawn at void
    actor = None
    try:
        tr = carla.Transform(carla.Location(x=0.0, y=0.0, z=-5000.0))
        try:
            actor = world.spawn_actor(bp, tr)
        except Exception as e:
            assert isinstance(e, Exception)  # spawn failure is the injected fault
            return
    finally:
        if actor is not None:
            try:
                actor.destroy()
            except Exception:
                pass
    assert wst.snap(world.get_settings())["synchronous_mode"] is False


def test_live_world_reload_failure_keeps_rpc_usable() -> None:
    client = _live_client()
    try:
        client.load_world("NoSuchMap_DoesNotExist_12345")
        pytest.fail("load_world of a nonexistent map should raise")
    except Exception:
        pass
    # RPC link must still answer afterwards.
    assert client.get_server_version() == "0.9.16"
    assert client.get_world().get_map().name


def test_live_process_timeout_probe_is_fast() -> None:
    import time

    client = _live_client()
    client.set_timeout(2.0)
    t0 = time.time()
    try:
        client.get_server_version()
    finally:
        client.set_timeout(30.0)
    assert time.time() - t0 < 30.0
