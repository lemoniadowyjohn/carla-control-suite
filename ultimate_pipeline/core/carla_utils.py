import socket
try:
    import psutil  # type: ignore
except Exception:
    psutil = None  # type: ignore

import subprocess
import time
import os
from typing import Tuple
import carla

from ultimate_pipeline.config.settings import SETTINGS


def _env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_carla_log_path() -> str | None:
    # Prefer per-run log path set by pipeline (env var), fallback to settings.
    p = os.environ.get("UP_CARLA_LOG_PATH")
    if p:
        return p
    return getattr(SETTINGS, "CARLA_SERVER_LOG", None)


# ============================================================
# Crash cleanup (NEW)
# ============================================================

def _cleanup_carla_crash_artifacts():
    """
    Remove Unreal Engine crash leftovers before restarting CARLA.
    """
    import shutil

    base = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "CarlaUE4",
        "Saved"
    )

    if not os.path.isdir(base):
        return

    crashes = os.path.join(base, "Crashes")
    if os.path.isdir(crashes):
        try:
            shutil.rmtree(crashes)
            print("🧹 Removed CARLA crash reports.")
        except Exception as e:
            print(f"⚠ Could not remove crash reports: {e}")

    cache = os.path.join(base, "DerivedDataCache")
    if os.path.isdir(cache):
        try:
            shutil.rmtree(cache)
            print("🧹 Removed CARLA derived data cache.")
        except Exception as e:
            print(f"⚠ Could not remove cache: {e}")

    temp = os.path.join(base, "Temp")
    if os.path.isdir(temp):
        try:
            shutil.rmtree(temp)
        except Exception:
            pass


# ============================================================
# Process + port utilities
# ============================================================
def _kill_stuck_carla():
    exe_names = ("CarlaUE4.exe", "CarlaUE4-Win64-Shipping.exe")

    # Preferred: psutil (if installed)
    if psutil is not None:
        for p in psutil.process_iter(["name"]):
            try:
                if p.info.get("name") in exe_names:
                    p.kill()
            except Exception:
                pass
        return

    # Fallback: no psutil installed (Windows taskkill / Linux pkill)
    if os.name == "nt":
        for exe in exe_names:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/IM", exe],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass
    else:
        for exe in exe_names:
            try:
                subprocess.run(
                    ["pkill", "-f", exe],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass



def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_ports(host: str, ports: list[int], timeout_s: float = 60.0) -> bool:
    """Wait until all TCP ports are reachable."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if all(_port_open(host, int(p), timeout=1.0) for p in ports):
            return True
        time.sleep(0.5)
    return False


# Backwards-compat alias (older modules used this name)
_carla_port_open = _port_open


# ============================================================
# Restart logic (SINGLE authority)
# ============================================================

def restart_carla(host: str | None = None, port: int | None = None) -> bool:
    """Restart the CARLA server process.

    Backwards compatible: if host/port are not provided, uses SETTINGS.
    """
    host = host or SETTINGS.CARLA_HOST
    port = int(port or SETTINGS.CARLA_PORT)
    streaming_port = int(getattr(SETTINGS, "CARLA_STREAMING_PORT", port + 1) or (port + 1))

    print("💀 Restarting CARLA server...")

    _cleanup_carla_crash_artifacts()
    _kill_stuck_carla()
    time.sleep(2)

    exe = SETTINGS.CARLA_EXE
    if not os.path.exists(exe):
        print(f"❌ CARLA executable not found at: {exe}")
        return False

    # CARLA uses RPC (control) + Streaming (sensor/actor data). Many failures that look
    # like "streaming client: connection refused" are simply a missing streaming port.
    ports = [port, streaming_port]

    # Try a couple of common flag styles for different CARLA builds.
    launch_variants = [
        [
            exe,
            "-RenderOffScreen",
            "-quality-level=Low",
            "-nosound",
            "-windowed", "-ResX=800", "-ResY=600",
            f"-carla-rpc-port={port}",
            f"-carla-streaming-port={streaming_port}",
        ],
        [
            exe,
            "-RenderOffScreen",
            "-quality-level=Low",
            "-nosound",
            "-windowed", "-ResX=800", "-ResY=600",
            f"-carla-port={port}",
            f"-carla-streaming-port={streaming_port}",
        ],
    ]

    for cmd in launch_variants:
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
        except Exception as e:
            print(f"❌ Failed to start CARLA: {e}")
            continue

        if _wait_for_ports(host, ports, timeout_s=120.0):
            print(f"✅ CARLA restarted and listening on {host}:{port} (streaming {streaming_port})")
            return True

        # If the port(s) never appeared, kill and retry next launch variant.
        _kill_stuck_carla()
        time.sleep(2)

    print("❌ CARLA did not come back after restart.")
    return False


# ============================================================
# Public API
# ============================================================

def ensure_carla_ready(client: carla.Client) -> bool:
    """Check if CARLA responds. No restart here."""
    try:
        client.get_world()
        # Helpful debug: version mismatch can produce weird streaming behavior.
        try:
            sv = client.get_server_version()
            cv = client.get_client_version()
            if sv and cv and sv != cv:
                print(f"⚠ CARLA version mismatch (server={sv}, client={cv}). Consider using matching PythonAPI.")
        except Exception:
            pass
        return True
    except Exception:
        return False


def autostart_carla_if_needed(
    host: str | None = None,
    port: int | None = None,
    *,
    timeout_s: float | None = None,
) -> carla.Client:
    """Return a connected, responsive CARLA client (restarting server if needed).

    Backwards compatible: callers can still use autostart_carla_if_needed() with no args.
    """
    host = host or SETTINGS.CARLA_HOST
    port = int(port or SETTINGS.CARLA_PORT)
    timeout_s = float(timeout_s if timeout_s is not None else getattr(SETTINGS, "CARLA_TIMEOUT", 20.0))

    # ------------------------------------------------------------
    # Worker-safe mode: never restart CARLA from a subprocess.
    # The parent pipeline manages CARLA lifecycle (restart/settle).
    # ------------------------------------------------------------
    if _env_flag("UP_NO_CARLA_AUTOSTART", False):
        if not _port_open(host, port):
            raise RuntimeError(f"CARLA RPC port not reachable ({host}:{port})")

        client = carla.Client(host, port)
        client.set_timeout(timeout_s)

        # In worker mode, only require the RPC side to be responsive.
        # The streaming port can flap briefly on Windows restarts.
        if not ensure_carla_ready(client):
            raise RuntimeError("CARLA not ready (no-autostart mode).")

        streaming_port = int(getattr(SETTINGS, "CARLA_STREAMING_PORT", port + 1) or (port + 1))
        if not _port_open(host, streaming_port):
            print(f"⚠ Streaming port {streaming_port} not open (continuing; no-autostart mode).")

        print("✅ CARLA connection confirmed.")
        return client


    print("🔎 Checking CARLA availability...")

    streaming_port = int(getattr(SETTINGS, "CARLA_STREAMING_PORT", port + 1) or (port + 1))
    if not _port_open(host, port) or not _port_open(host, streaming_port):
        print("⚠ CARLA not reachable — launching.")
        if not restart_carla(host=host, port=port):
            raise RuntimeError("CARLA could not be launched.")

    client = carla.Client(host, port)
    client.set_timeout(timeout_s)

    if not ensure_carla_ready(client) or not _port_open(host, streaming_port):
        print("💀 CARLA unresponsive — restarting.")
        if not restart_carla(host=host, port=port):
            raise RuntimeError("CARLA restart failed.")

        client = carla.Client(host, port)
        client.set_timeout(timeout_s)

        if not ensure_carla_ready(client):
            raise RuntimeError("CARLA never became ready.")

    print("✅ CARLA connection confirmed.")
    return client


# ============================================================
# XODR load with one retry
# ============================================================

def carla_load_xodr_with_restart(
    client: carla.Client,
    xodr_path: str,
    label: str,
    timeout_sec: float = 60.0,
) -> Tuple[bool, carla.Client]:

    print(f"\n🧪 CARLA Load Test: {label}")

    if not os.path.exists(xodr_path):
        print(f"❌ File not found: {xodr_path}")
        return False, client

    def _do_load(c: carla.Client) -> bool:
        with open(xodr_path, encoding="utf-8") as f:
            data = f.read()

        params = carla.OpendriveGenerationParameters()
        params.map_layers = carla.MapLayer.NONE

        from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

        load_opendrive_world(
            c,
            data,
            params=params,
            timeout_s=float(timeout_sec),
            retries=0,
            do_reload=True,
        )
        t0 = time.time()
        while time.time() - t0 < timeout_sec:
            try:
                world = c.get_world()
                world.get_map()
                print("✅ Map loaded and responsive.")
                return True
            except Exception:
                time.sleep(1)

        return False

    try:
        if _do_load(client):
            return True, client
    except Exception as e:
        print(f"⚠ Load failed: {e}")

    print("💀 Retrying after CARLA restart.")

    if not restart_carla():
        return False, client

    new_client = carla.Client(SETTINGS.CARLA_HOST, SETTINGS.CARLA_PORT)
    new_client.set_timeout(getattr(SETTINGS, "CARLA_TIMEOUT", 20.0))

    if not ensure_carla_ready(new_client):
        return False, new_client

    try:
        return _do_load(new_client), new_client
    except Exception:
        return False, new_client