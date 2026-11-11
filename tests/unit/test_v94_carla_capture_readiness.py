"""V94 read-only capture readiness tests. No live CARLA, no GPU, no ports."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from ultimate_pipeline.perception import run_capture_end2end as capture


class World:
    def get_map(self):
        return SimpleNamespace(name="OpenDriveMap")

    def get_settings(self):
        return SimpleNamespace(synchronous_mode=True)

    def get_snapshot(self):
        raise AssertionError("readiness is not the capture/tick owner")

    def tick(self, *args, **kwargs):
        raise AssertionError("external tick prohibited")


class Client:
    instances = []
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.timeouts = []
        self.__class__.instances.append(self)

    def set_timeout(self, seconds):
        self.timeouts.append(float(seconds))

    def get_world(self):
        return World()


def test_synchronous_world_passes_rpc_readiness_without_frames(monkeypatch):
    Client.instances.clear()
    monkeypatch.setattr(capture, "_try_import_carla", lambda: (SimpleNamespace(Client=Client), None))
    result = capture._ready_probe("127.0.0.1", 2000, timeout_s=0.2, sleep_s=0.0)
    assert result["ok"] is True, result
    assert result["status"] == "RPC_MAP_READY_FRAMES_UNVERIFIED"
    assert result["attempts"][0]["sync_world"] is True
    assert result["attempts"][0]["tick_ok"] is None
    assert Client.instances
    assert 0 < min(Client.instances[0].timeouts) <= 0.2


def test_client_timeout_is_capped_to_deadline(monkeypatch):
    class InspectClient(Client):
        pass

    InspectClient.instances.clear()
    monkeypatch.setenv("UP_CARLA_CLIENT_TIMEOUT_S", "180")
    monkeypatch.setattr(capture, "_try_import_carla", lambda: (SimpleNamespace(Client=InspectClient), None))
    result = capture._ready_probe("127.0.0.1", 2222, timeout_s=0.05, sleep_s=0.0)
    assert result["ok"] is True
    assert InspectClient.instances
    assert all(0 < t <= 0.05 for t in InspectClient.instances[0].timeouts)


def test_failing_rpc_bounded_under_transport_timeout(monkeypatch):
    class FailingClient(Client):
        def get_world(self):
            # Model an RPC client that honors set_timeout; the deadline must
            # shrink on each attempt instead of resetting to 180s.
            time.sleep(min(0.004, self.timeouts[-1]))
            raise TimeoutError("injected stalled RPC")

    FailingClient.instances.clear()
    monkeypatch.setenv("UP_CARLA_CLIENT_TIMEOUT_S", "180")
    monkeypatch.setattr(capture, "_try_import_carla", lambda: (SimpleNamespace(Client=FailingClient), None))
    started = time.monotonic()
    result = capture._ready_probe("127.0.0.1", 2000, timeout_s=0.05, sleep_s=0.004)
    elapsed = time.monotonic() - started
    assert result["ok"] is False
    assert result["status"] == "RPC_READINESS_TIMEOUT"
    assert "stalled RPC" in result["last_error"]
    assert len(result["attempts"]) >= 1
    assert elapsed < 0.4, elapsed
    assert all(0 < timeout <= 0.05
               for client in FailingClient.instances for timeout in client.timeouts)


def test_invalid_port_fails_without_false_positive(monkeypatch):
    class InvalidPort:
        def __init__(self, host, port):
            raise ConnectionRefusedError("bad port")
    monkeypatch.setattr(capture, "_try_import_carla", lambda: (SimpleNamespace(Client=InvalidPort), None))
    result = capture._ready_probe("127.0.0.1", 0, timeout_s=0.02, sleep_s=0)
    assert result["ok"] is False
    assert result["status"] == "RPC_READINESS_TIMEOUT"
    assert result["attempts"]


@pytest.mark.parametrize("timeout_s,sleep_s", [
    (0, 0), (-1, 0), (float("nan"), 0), (float("inf"), 0),
    (1, -0.1), (1, float("nan")),
])
def test_invalid_input_fails_closed_before_network(monkeypatch, timeout_s, sleep_s):
    monkeypatch.setattr(capture, "_try_import_carla",
                        lambda: (_ for _ in ()).throw(AssertionError("network import prohibited")))
    result = capture._ready_probe("127.0.0.1", 2000, timeout_s=timeout_s, sleep_s=sleep_s)
    assert result["ok"] is False
    assert result["last_error"].startswith("invalid_")


def test_import_failure_is_not_a_ready_session(monkeypatch):
    monkeypatch.setattr(capture, "_try_import_carla", lambda: (None, "module not installed"))
    result = capture._ready_probe("127.0.0.1", 2000, timeout_s=0.1)
    assert result["ok"] is False
    assert "carla_import_failed" in result["last_error"]


def test_invalid_client_timeout_environment_fails_closed(monkeypatch):
    monkeypatch.setenv("UP_CARLA_CLIENT_TIMEOUT_S", "nan")
    monkeypatch.setattr(capture, "_try_import_carla",
                        lambda: (_ for _ in ()).throw(AssertionError("network import prohibited")))
    result = capture._ready_probe("127.0.0.1", 2000, timeout_s=1)
    assert result["ok"] is False
    assert result["last_error"] == "invalid_client_timeout"
