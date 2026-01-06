# ultimate_pipeline/core/carla_utils.py
raise RuntimeError(
    "Deprecated: use ultimate_pipeline.core.carla_utils instead. "
    "This file must not be imported."
)

import os
import time
import socket
import subprocess
from typing import Optional

import psutil
import carla
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

from config.settings import SETTINGS


# ------------------------------------------------------------
# Helper: check if CARLA port is open
# ------------------------------------------------------------
def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def strip_heavy_xodr_layers(xodr_in: str, xodr_out: str, drop_signals: bool = True) -> None:
    import xml.etree.ElementTree as ET
    tree = ET.parse(xodr_in)
    root = tree.getroot()

    # objects are often huge (buildings/vegetation)
    objs = root.find("objects")
    if objs is not None:
        root.remove(objs)

    # signals can be huge too (traffic lights + refs)
    if drop_signals:
        sigs = root.find("signals")
        if sigs is not None:
            root.remove(sigs)

    tree.write(xodr_out, encoding="utf-8", xml_declaration=True)


# ------------------------------------------------------------
# Start CARLA server (without killing)
# ------------------------------------------------------------
def start_carla() -> bool:
    exe = getattr(SETTINGS, "CARLA_EXE", None)

    if not exe or not os.path.exists(exe):
        print(f"❌ CARLA_EXE invalid: {exe}")
        return False

    print(f"🚀 Launching CARLA server:\n   {exe}")

    subprocess.Popen(
        [
            exe,
            "-carla-server",
            "-RenderOffScreen",
            "-quality-level=Low",
            "-nosound",
            "-windowed", "-ResX=800", "-ResY=600",
            f"-world-port={SETTINGS.CARLA_PORT}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    return True


# ------------------------------------------------------------
# Restart CARLA fully
# ------------------------------------------------------------
def restart_carla() -> bool:
    print("💀 Restarting CARLA process…")

    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] and ("CarlaUE4" in proc.info["name"]):
                proc.kill()
        except:
            pass

    time.sleep(2)

    if not start_carla():
        print("❌ Could not start CARLA.exe")
        return False

    # Wait for port to open
    for i in range(60):
        if _port_open(SETTINGS.CARLA_HOST, SETTINGS.CARLA_PORT):
            print("✅ CARLA restarted.")
            return True
        time.sleep(1)

    print("❌ CARLA restart timed out.")
    return False


# ------------------------------------------------------------
# Verify CARLA responds to get_world()
# ------------------------------------------------------------
def ensure_carla_ready(client: carla.Client, retries: int = 20, delay: float = 1.0) -> bool:

    # Fast 3-ping
    for _ in range(3):
        try:
            client.get_world()
            print("🚗 CARLA ready (fast check).")
            return True
        except Exception:
            time.sleep(0.5)

    # Slow retries
    for i in range(1, retries + 1):
        try:
            client.get_world()
            print(f"🚗 CARLA ready (attempt {i}/{retries})")
            return True
        except Exception as e:
            print(f"⏳ Waiting for CARLA… ({i}/{retries}) → {e}")
            time.sleep(delay)

    print("❌ CARLA not responding.")
    return False


# ------------------------------------------------------------
# Ensure CARLA is running (autostart)
# ------------------------------------------------------------
def autostart_carla_if_needed() -> carla.Client:
    host = SETTINGS.CARLA_HOST
    port = SETTINGS.CARLA_PORT

    print("🔎 Checking CARLA availability...")

    # If port closed → start CARLA
    if not _port_open(host, port, timeout=1.0):
        print("⚠ CARLA not reachable — will launch new instance.")

        ok = restart_carla()
        if not ok:
            raise RuntimeError("CARLA could not be launched.")

    # ALWAYS return a client object
    client = carla.Client(host, port)
    client.set_timeout(10.0)

    # Make sure simulator is responsive
    if not ensure_carla_ready(client):
        print("💀 CARLA unresponsive — restarting...")
        ok = restart_carla()
        if not ok:
            raise RuntimeError("CARLA failed to restart.")

        client = carla.Client(host, port)
        client.set_timeout(10.0)

        if not ensure_carla_ready(client):
            raise RuntimeError("CARLA did not become ready after restart.")

    print("🎉 CARLA online and confirmed ready.")
    return client

# ------------------------------------------------------------
# Load XODR into CARLA with auto-restart on crash
# ------------------------------------------------------------
def carla_load_xodr_with_restart(
    client: carla.Client,
    xodr_path: str,
    label: str,
    timeout_sec: float = 60.0,
) -> tuple[bool, carla.Client]:

    print(f"\n🧪 CARLA Load Test: {label}")

    if not os.path.exists(xodr_path):
        print(f"❌ Missing XODR: {xodr_path}")
        return False, client

    def _try_load(c: carla.Client) -> bool:
        with open(xodr_path, "r", encoding="utf-8") as f:
            data = f.read()

        params = carla.OpendriveGenerationParameters()
        params.map_layers = carla.MapLayer.NONE

        try:
            c.set_timeout(timeout_sec)
            load_opendrive_world(
                c,
                data,
                params=params,
                timeout_s=180.0,
                retries=2,
                do_reload=True,
            )
        except Exception as e:
            print(f"❌ CARLA rejected XODR: {e}")
            return False

        t0 = time.time()
        while time.time() - t0 < timeout_sec:
            try:
                w = c.get_world()
                _ = w.get_map()
                print("   ✓ Map loaded successfully.")
                return True
            except:
                time.sleep(1)

        print("   ❌ CARLA never returned a world.")
        return False

    # First load attempt
    try:
        if _try_load(client):
            return True, client
    except Exception as e:
        print(f"⚠ Load attempt crashed: {e}")

    print("💀 CARLA appears broken — restarting…")

    if not restart_carla():
        return False, client

    new_client = carla.Client(SETTINGS.CARLA_HOST, SETTINGS.CARLA_PORT)
    new_client.set_timeout(10.0)

    if not ensure_carla_ready(new_client):
        print("❌ CARLA did not recover.")
        return False, new_client

    # Final retry
    ok = _try_load(new_client)
    return ok, new_client