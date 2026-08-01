from __future__ import annotations
from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
# Verification (PowerShell):
# python -m ultimate_pipeline.perception.run_capture_end2end --town Grid0828 --carla-exe "E:\CARLA\CARLA_0.9.16\CarlaUE4.exe" --kill-stale --out-dir .\datasets\smoke\grid0828 --duration 10 --fps 10 --low-mem

import importlib
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    import carla

# Safe defaults for low-VRAM Windows laptops
DEFAULT_FLAGS: Sequence[str] = (
    "-d3d11",
    "-nosound",
    "-quality-level=Low",
    "-windowed",
    "-ResX=1280",
    "-ResY=720",
)

def _lazy_carla():
    return importlib.import_module("carla")

def kill_stale_carla(process_names: Iterable[str] = ("CarlaUE4.exe", "CarlaUE4-Win64-Shipping.exe")) -> None:
    """Kill leftover CARLA processes to avoid port conflicts."""
    for name in process_names:
        try:
            subprocess.run(["taskkill", "/F", "/IM", name], check=False, capture_output=True)
        except Exception:
            continue

def wait_for_port(host: str, port: int, timeout_s: float = 60.0) -> bool:
    """Wait until TCP port is reachable."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except Exception:
            time.sleep(1.0)
    return False

def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)

def _handshake_carla_ready(*, host: str, port: int) -> None:
    """
    Readiness handshake that correctly handles CARLA 0.9.16 sync tick semantics:
      - sync: world.tick() returns int frame_id, NOT WorldSnapshot
      - async: world.wait_for_tick() returns WorldSnapshot
    """
    carla = _lazy_carla()
    client_timeout_s = _env_float("UP_CARLA_CLIENT_TIMEOUT_S", 180.0)
    ready_timeout_s = _env_float("UP_CARLA_READY_TIMEOUT_S", 180.0)
    tick_timeout_s = _env_float("UP_CARLA_READY_TICK_TIMEOUT_S", 5.0)

    client = carla.Client(host, int(port))
    client.set_timeout(float(client_timeout_s))
    world = client.get_world()
    _ = world.get_map()

    t0 = time.time()
    last_frame = None
    last_elapsed = None
    last_error = None
    while time.time() - t0 < float(ready_timeout_s):
        try:
            settings = world.get_settings()
            sync = bool(getattr(settings, "synchronous_mode", False))
        except Exception:
            sync = True

        try:
            if sync:
                frame_id = world.tick()  # int
                snap = world.get_snapshot()
                frame = int(getattr(snap, "frame", frame_id))
                ts = getattr(snap, "timestamp", None)
                elapsed = float(getattr(ts, "elapsed_seconds", -1.0)) if ts is not None else -1.0
            else:
                # CARLA 0.9.16: positional float only
                snap = world.wait_for_tick(float(tick_timeout_s))
                frame = int(getattr(snap, "frame", -1))
                ts = getattr(snap, "timestamp", None)
                elapsed = float(getattr(ts, "elapsed_seconds", -1.0)) if ts is not None else -1.0
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.5)
            continue

        if last_frame is not None:
            if frame != last_frame or (elapsed is not None and last_elapsed is not None and elapsed > last_elapsed):
                return

        last_frame = frame
        last_elapsed = elapsed
        time.sleep(0.2)

    raise RuntimeError(
        f"CARLA readiness handshake timed out after {ready_timeout_s}s (last_error={last_error})"
    )

def start_carla(
    carla_exe: Path | str,
    extra_flags: Optional[Sequence[str]] = None,
    *,
    stdout_path: Optional[Path | str] = None,
    stderr_path: Optional[Path | str] = None,
) -> subprocess.Popen:
    exe = Path(carla_exe)
    if not exe.exists():
        raise FileNotFoundError(f"CARLA executable not found: {exe}")
    flags: List[str] = list(extra_flags) if extra_flags else []
    cmd = [str(exe), *flags]
    stdout_handle = None
    stderr_handle = None
    try:
        if stdout_path is not None:
            stdout_handle = open(Path(stdout_path), "a", encoding="utf-8", errors="replace", buffering=1)
        if stderr_path is not None:
            stderr_handle = open(Path(stderr_path), "a", encoding="utf-8", errors="replace", buffering=1)
        return subprocess.Popen(
            cmd,
            stdout=stdout_handle if stdout_handle is not None else subprocess.DEVNULL,
            stderr=stderr_handle if stderr_handle is not None else subprocess.DEVNULL,
        )
    except Exception:
        if stdout_handle is not None:
            try:
                stdout_handle.close()
            except Exception:
                pass
        if stderr_handle is not None:
            try:
                stderr_handle.close()
            except Exception:
                pass
        raise

def ensure_carla_server(
    *,
    host: str,
    port: int,
    carla_exe: Path | str,
    extra_flags: Optional[Sequence[str]] = None,
    timeout_s: float = 120.0,
    kill_stale: bool = False,
    stdout_path: Optional[Path | str] = None,
    stderr_path: Optional[Path | str] = None,
) -> subprocess.Popen:
    """
    Kill stale CARLA, start a new server with safe flags, and wait until it responds.
    If CARLA is already reachable on the port, do nothing.
    """
    if wait_for_port(host, port, timeout_s=3.0):
        _handshake_carla_ready(host=host, port=port)
        return None  # type: ignore[return-value]

    flags: List[str] = list(extra_flags or DEFAULT_FLAGS)
    if kill_stale:
        kill_stale_carla()
    if not any(str(f).startswith("-carla-rpc-port") for f in flags):
        flags.append(f"-carla-rpc-port={int(port)}")
    if not any(str(f).startswith("-carla-streaming-port") for f in flags):
        flags.append(f"-carla-streaming-port={int(port)+1}")
    proc = start_carla(
        carla_exe,
        flags,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    ok = wait_for_port(host, port, timeout_s=timeout_s)
    if not ok:
        raise RuntimeError(f"CARLA did not come up on {host}:{port} within {timeout_s}s")
    _handshake_carla_ready(host=host, port=port)
    return proc

def get_carla_client(host: str, port: int, *, timeout_s: float = 300.0) -> "carla.Client":
    carla = _lazy_carla()
    client = carla.Client(host, port)
    client.set_timeout(float(timeout_s))
    return client

def available_map_names(client: "carla.Client") -> list[str]:
    maps = []
    for m in client.get_available_maps():
        if "/" in m:
            maps.append(m.split("/")[-1])
        else:
            maps.append(m)
    return maps

def ensure_maps_available(client: "carla.Client", expected: Sequence[str]) -> list[str]:
    available = available_map_names(client)
    missing = [m for m in expected if m not in available]
    if missing:
        raise RuntimeError(f"Missing CARLA maps: {missing}. Available: {available}")
    return available

def load_map_with_timeout(client: "carla.Client", map_name: str, *, timeout_s: float = 300.0) -> "carla.World":
    client.set_timeout(float(timeout_s))
    world = _reload_ready_for_sensors(client, map_name=map_name, tm_port=8000)
    try:
        world.wait_for_tick(2.0)
    except Exception:
        pass
    return world

def enable_no_rendering(world: "carla.World") -> None:
    settings = world.get_settings()
    settings.no_rendering_mode = True
    world.apply_settings(settings)
