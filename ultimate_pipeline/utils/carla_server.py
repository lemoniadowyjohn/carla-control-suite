from __future__ import annotations

import importlib
import socket
import subprocess
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, TYPE_CHECKING

from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
if TYPE_CHECKING:  # pragma: no cover
    import carla


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
    """Kill any leftover CARLA processes to avoid port conflicts."""
    names = list(process_names)
    for name in names:
        try:
            subprocess.run(["taskkill", "/F", "/IM", name], check=False, capture_output=True)
        except Exception:
            continue


def wait_for_port(host: str, port: int, timeout_s: float = 60.0) -> bool:
    """Wait until TCP port is connectable."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except Exception:
            time.sleep(1.0)
    return False


def start_carla(carla_exe: Path | str, extra_flags: Optional[Sequence[str]] = None) -> subprocess.Popen:
    exe = Path(carla_exe)
    if not exe.exists():
        raise FileNotFoundError(f"CARLA executable not found: {exe}")
    flags: List[str] = list(extra_flags) if extra_flags else []
    cmd = [str(exe), *flags]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_carla_server(
    *,
    host: str,
    port: int,
    carla_exe: Path | str,
    extra_flags: Optional[Sequence[str]] = None,
    timeout_s: float = 120.0,
) -> subprocess.Popen:
    """Kill stale CARLA, start a new server with safe flags, and wait until it responds."""
    kill_stale_carla()
    proc = start_carla(carla_exe, extra_flags or DEFAULT_FLAGS)
    ok = wait_for_port(host, port, timeout_s=timeout_s)
    if not ok:
        raise RuntimeError(f"CARLA did not come up on {host}:{port} within {timeout_s}s")
    return proc


def available_map_names(client: "carla.Client") -> list[str]:
    """Normalize CARLA map names (strip /Game/ prefix)."""
    maps = []
    for m in client.get_available_maps():
        if "/" in m:
            maps.append(m.split("/")[-1])
        else:
            maps.append(m)
    return maps


def ensure_maps_available(client: "carla.Client", expected: Sequence[str]) -> list[str]:
    """Return the subset of expected maps found on the server; raise if any missing."""
    available = available_map_names(client)
    missing = [m for m in expected if m not in available]
    if missing:
        raise RuntimeError(f"Missing CARLA maps: {missing}. Available: {available}")
    return available


def load_map_with_timeout(client: "carla.Client", map_name: str, *, timeout_s: float = 300.0) -> "carla.World":
    """Load a map with an extended timeout (Windows-safe)."""
    client.set_timeout(float(timeout_s))
    world = _reload_ready_for_sensors(client, map_name=map_name, tm_port=8000)
    try:
        # CARLA 0.9.16: must use positional float, not keyword arg
        world.wait_for_tick(2.0)
    except Exception:
        pass
    return world


def enable_no_rendering(world: "carla.World") -> None:
    """Enable no_rendering_mode to reduce GPU load during capture."""
    settings = world.get_settings()
    settings.no_rendering_mode = True
    world.apply_settings(settings)
