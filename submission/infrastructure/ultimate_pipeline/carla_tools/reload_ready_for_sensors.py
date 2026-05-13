from __future__ import annotations

import importlib
import os
import socket
import time
from typing import Any, Optional


def _probe_port(host: str, port: int, timeout_s: float = 1.0) -> bool:
    """Return True if TCP port is open."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout_s)
        r = s.connect_ex((host, port))
        s.close()
        return r == 0
    except Exception:
        return False


def _wait_for_streaming_port(
    host: str = "127.0.0.1",
    port: int = 2001,
    wait_s: float = 120.0,
    poll_interval_s: float = 1.0,
    required_successes: int | None = None,
) -> bool:
    """
    Poll streaming port until it opens or timeout.
    Returns True if port opened, False if timed out.
    Streaming port 2001 restarts after every load_world/generate_opendrive_world.
    Sensor spawn hangs if we proceed before streaming is ready.
    """
    deadline = time.monotonic() + wait_s
    if required_successes is None:
        try:
            required_successes = int(os.getenv("UP_STREAM_READY_SUCCESS_STREAK", "5"))
        except Exception:
            required_successes = 5
    required_successes = max(1, int(required_successes))
    consecutive_successes = 0
    while time.monotonic() < deadline:
        if _probe_port(host, port, timeout_s=1.0):
            consecutive_successes += 1
            if consecutive_successes >= required_successes:
                return True
        else:
            consecutive_successes = 0
        time.sleep(poll_interval_s)
    return False


def _reload_ready_for_sensors(
    client: Any,
    *,
    map_name: str | None = None,
    xodr_string: str | None = None,
    tm_port: int = 8000,
    fixed_dt: float = 0.05,
    async_warmup_frames: int = 5,
    sync_warmup_frames: int = 5,
    timeout: float = 30.0,
    xodr_generation_params: Optional[Any] = None,
    streaming_host: str = "127.0.0.1",
    streaming_port: int = 2001,
    wait_for_streaming: bool = True,
    streaming_wait_s: float = 120.0,
) -> Any:
    carla = importlib.import_module("carla")
    # Allow env-var override for slow machines (e.g. Grid0828/Grid0821 first-load delay).
    try:
        _env_wait = os.getenv("UP_THESIS_STREAMING_RECOVERY_WAIT_S")
        if _env_wait is not None:
            streaming_wait_s = float(_env_wait)
    except (TypeError, ValueError):
        pass
    client.set_timeout(timeout)
    old_world = client.get_world()
    try:
        client.get_trafficmanager(tm_port).set_synchronous_mode(False)
    except Exception:
        pass
    try:
        s = old_world.get_settings()
        s.synchronous_mode = False
        s.fixed_delta_seconds = None
        old_world.apply_settings(s)
    except Exception:
        pass

    if xodr_string is not None:
        params = (
            xodr_generation_params
            if xodr_generation_params is not None
            else carla.OpendriveGenerationParameters()
        )
        world = client.generate_opendrive_world(xodr_string, params)
    elif map_name is not None:
        try:
            world = client.load_world(map_name, reset_settings=True)
        except TypeError:
            world = client.load_world(map_name)
    else:
        try:
            world = client.reload_world(reset_settings=True)
        except TypeError:
            world = client.reload_world()

    # Wait for streaming port to recover after world load.
    # load_world/generate_opendrive_world restarts CARLA streaming server (port 2001).
    # spawn_actor(attach_to=ego) hangs if streaming is not yet ready.
    if wait_for_streaming:
        streaming_ok = _wait_for_streaming_port(
            host=streaming_host,
            port=streaming_port,
            wait_s=streaming_wait_s,
        )
        if not streaming_ok:
            print(
                f"[reload_ready] WARNING: streaming port {streaming_port} did not "
                f"open within {streaming_wait_s}s — proceeding anyway "
                f"(use --skip-stream-check to suppress sensor spawn errors)"
            )

    for _ in range(async_warmup_frames):
        try:
            world.wait_for_tick(seconds=timeout)
        except Exception:
            break

    try:
        s = world.get_settings()
        s.synchronous_mode = True
        s.fixed_delta_seconds = fixed_dt
        world.apply_settings(s)
    except Exception:
        pass
    try:
        client.get_trafficmanager(tm_port).set_synchronous_mode(True)
    except Exception:
        pass

    for _ in range(sync_warmup_frames):
        try:
            world.tick(seconds=timeout)
        except Exception:
            break
    return world
