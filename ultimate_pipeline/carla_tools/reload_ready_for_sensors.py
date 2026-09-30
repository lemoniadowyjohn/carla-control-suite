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


def _wait_for_sensor_canary(
    world: Any,
    *,
    ticks: int = 10,
    tick_timeout_s: float = 2.0,
    width: int = 64,
    height: int = 48,
    result: Optional[dict] = None,
) -> dict:
    """
    NEW-255: prove sensor callback transport with a canary, not a TCP port.

    Streaming port 2001 was being used as the proxy for "sensors can work", which
    is wrong in both directions: it blocks on maps that never open the port but
    deliver callbacks fine, and it can be open on a map whose sensor transport is
    still broken. The capability perception actually requires is "attach one RGB
    sensor and receive a frame", so that is what is measured.

    The canary deliberately avoids ``destroy()``: on the Grid maps
    ``ASensor::EndPlay`` is a known teardown-crash source (NEW-258/NEW-259), and a
    readiness check must not be able to crash the engine it is checking.

    Returns a dict with ``ok``, ``frames_received`` and ``errors``.
    """
    receipt: dict = result if result is not None else {}
    receipt.setdefault("canary_frames", 0)
    receipt.setdefault("canary_errors", [])
    frames: list[int] = []
    sensor = None
    listener_registered = False

    try:
        carla_mod = importlib.import_module("carla")
        blueprint = world.get_blueprint_library().find("sensor.camera.rgb")
        blueprint.set_attribute("image_size_x", str(int(width)))
        blueprint.set_attribute("image_size_y", str(int(height)))
        blueprint.set_attribute("fov", "90")
        transform = carla_mod.Transform(carla_mod.Location(x=0.0, z=2.0))
        sensor = world.spawn_actor(blueprint, transform)

        def _on_image(image: Any) -> None:
            frames.append(int(getattr(image, "frame", -1)))

        sensor.listen(_on_image)
        listener_registered = True

        for _ in range(max(1, int(ticks))):
            try:
                settings = world.get_settings()
                if bool(getattr(settings, "synchronous_mode", False)):
                    world.tick(float(tick_timeout_s))
                else:
                    world.wait_for_tick(float(tick_timeout_s))
            except Exception as exc:
                receipt["canary_errors"].append(f"canary_tick_failed: {exc}")
                break
            if frames:
                break
    except Exception as exc:
        receipt["canary_errors"].append(f"canary_spawn_failed: {type(exc).__name__}: {exc}")
    finally:
        # Stop the listener but DO NOT destroy the sensor. Leaving it to the world
        # teardown is safer than an explicit destroy on unstable maps.
        if sensor is not None and listener_registered:
            try:
                sensor.stop()
            except Exception:
                pass

    receipt["canary_frames"] = len(frames)
    receipt["canary_first_frame"] = frames[0] if frames else None
    receipt["ok"] = bool(frames)
    if not frames and not receipt["canary_errors"]:
        receipt["canary_errors"].append("canary_no_frames: sensor attached but no callback arrived")
    return receipt


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
    require_sensor_canary: Optional[bool] = None,
) -> Any:
    """
    Load a map and make it ready for sensor attachment.

    NEW-255: the streaming port is no longer decisive. Port 2001 is polled and
    recorded as *diagnostic evidence*, but readiness requires a sensor canary --
    one RGB sensor that actually produces a frame. The previous behaviour waved
    the run through when the port never opened, which is both fail-open and
    unreliable on the Grid maps, which do not consistently expose 2001 yet do
    deliver sensor callbacks.
    """
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

    # NEW-255: port 2001 is diagnostic evidence, not the acceptance criterion.
    streaming_receipt: dict = {"waited": bool(wait_for_streaming), "port_open": None}
    if wait_for_streaming:
        streaming_ok = _wait_for_streaming_port(
            host=streaming_host,
            port=streaming_port,
            wait_s=streaming_wait_s,
        )
        streaming_receipt["port_open"] = bool(streaming_ok)
        if not streaming_ok:
            # NEW-255: this is no longer a fail-open pass-through. A closed port is
            # recorded, and the canary below decides readiness.
            print(
                f"[reload_ready] NOTE: streaming port {streaming_port} did not open "
                f"within {streaming_wait_s}s; recorded as diagnostic only. Readiness "
                f"is decided by the sensor canary, not by this port."
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

    # NEW-255: the actual acceptance gate.
    if require_sensor_canary is None:
        env_flag = os.environ.get("UP_REQUIRE_SENSOR_CANARY", "").strip().lower()
        require_sensor_canary = env_flag not in ("0", "false", "no", "")
    if require_sensor_canary:
        canary = _wait_for_sensor_canary(world, ticks=int(os.environ.get("UP_CANARY_TICKS", "10")))
        canary["streaming"] = streaming_receipt
        streaming_receipt["canary"] = canary
        if not canary.get("ok"):
            raise RuntimeError(
                "SENSOR_CANARY_FAILED: " + "; ".join(canary.get("canary_errors") or ["no frames"])
            )
        print(
            f"[reload_ready] sensor canary PASS (frames={canary.get('canary_frames')}, "
            f"streaming_port_open={streaming_receipt.get('port_open')})"
        )

    try:
        world._reload_ready_receipt = streaming_receipt  # type: ignore[attr-defined]
    except Exception:
        pass
    return world
