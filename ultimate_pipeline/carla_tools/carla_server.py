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
    """Refuse the retired image-wide shutdown API.

    An executable name does not identify a launch owner, run or port. Callers
    must use their own subprocess handle for cleanup. The parameter remains
    accepted for API compatibility but never selects a process to terminate.
    """
    raise RuntimeError(
        "Unsafe CARLA image-wide kill is disabled; close only a launch-owned "
        "subprocess handle, or obtain explicit operator approval."
    )


def _stop_owned_server(proc: subprocess.Popen) -> None:
    """Best-effort cleanup of the Popen handle from *this* launch attempt."""
    try:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[carla] Unable to reap launch-owned process: {exc}")


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
    """Read-only RPC/map handshake: never steal the synchronous tick owner.

    Each CARLA RPC timeout is capped to the remaining monotonic budget. CARLA's
    transport must honor set_timeout; hard-kill supervision is a separate gate.
    """
    client_timeout_s = _env_float("UP_CARLA_CLIENT_TIMEOUT_S", 180.0)
    ready_timeout_s = _env_float("UP_CARLA_READY_TIMEOUT_S", 180.0)
    if not 0 < ready_timeout_s < float("inf"):
        raise ValueError("UP_CARLA_READY_TIMEOUT_S must be positive and finite")
    if not 0 < client_timeout_s < float("inf"):
        raise ValueError("UP_CARLA_CLIENT_TIMEOUT_S must be positive and finite")
    carla = _lazy_carla()
    deadline = time.monotonic() + ready_timeout_s
    last_error = None
    while time.monotonic() < deadline:
        try:
            client = carla.Client(host, int(port))
            for rpc in ("get_world", "get_map", "get_settings"):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("readiness budget exhausted")
                client.set_timeout(min(client_timeout_s, remaining))
                if rpc == "get_world":
                    world = client.get_world()
                elif rpc == "get_map":
                    _ = world.get_map()
                else:
                    _ = world.get_settings()
            return  # A synchronous world can be healthy without advancing.
        except Exception as exc:
            last_error = str(exc)
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.3, remaining))
    raise RuntimeError(
        f"CARLA readiness RPC timed out after {ready_timeout_s}s (last_error={last_error})"
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
    attach_existing: bool = True,
    stdout_path: Optional[Path | str] = None,
    stderr_path: Optional[Path | str] = None,
) -> Optional[subprocess.Popen]:
    """Start a new launch-owned server, or explicitly attach to a listener.

    `attach_existing=False` forbids accidental mutation of another operator's
    CARLA world. The default preserves legacy callers' external-attach mode.
    """
    if kill_stale:
        kill_stale_carla()  # Refuse regardless of current port occupancy.
    if wait_for_port(host, port, timeout_s=3.0):
        if not attach_existing:
            raise RuntimeError(
                f"CARLA port {host}:{port} already occupied; refusing unowned attachment"
            )
        _handshake_carla_ready(host=host, port=port)
        return None

    flags: List[str] = list(extra_flags or DEFAULT_FLAGS)
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
    try:
        ok = wait_for_port(host, port, timeout_s=timeout_s)
        if not ok:
            raise RuntimeError(f"CARLA did not come up on {host}:{port} within {timeout_s}s")
        _handshake_carla_ready(host=host, port=port)
        return proc
    except BaseException:
        # Only the exact child handle started above may be terminated.
        _stop_owned_server(proc)
        raise

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
