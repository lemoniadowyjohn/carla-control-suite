#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

# ultimate_pipeline/carla_tools/carla_recovery.py

try:
    import carla  # type: ignore
except ModuleNotFoundError:
    carla = None  # type: ignore

def _require_carla() -> None:
    if carla is None:
        raise ModuleNotFoundError(
            "CARLA Python API is not installed. Install the matching CARLA Python package/egg."
        )


"""
Unified CARLA Recovery Manager
A single, reliable, cross-platform CARLA reset + reconnect + autostart system.

Responsibilities:
- Kill stale CARLA/UE4 processes
- Purge cache/temp folders that cause “time-out while waiting”
- Boot CARLA if not running
- Retry connection until stable
- Offer safe XODR load with restart fallback

This is the only CARLA recovery tool the pipeline should ever call.
"""

import os
import time
import socket
import subprocess
import sys
import shutil
try:
    import psutil  # type: ignore
    _PSUTIL_AVAILABLE = True
except Exception:  # pragma: no cover
    psutil = None  # type: ignore
    _PSUTIL_AVAILABLE = False

from ultimate_pipeline.config.settings import SETTINGS
import json
from datetime import datetime


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except Exception:
        return False


def _env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")


def _streaming_disabled() -> bool:
    return _env_flag("UP_DISABLE_STREAMING", False) or _env_flag("UP_TILE_QA_DISABLE_STREAMING", False)


def probe_streaming_port(
    host: str,
    port: int,
    *,
    timeout_s: float = 0.4,
    max_attempts: int = 1,
) -> dict:
    """
    Best-effort, warn-only streaming port probe.
    Never raises; returns a status payload for logging/reporting.
    """
    status = {
        "port": int(port),
        "optional": True,
        "disabled": False,
        "attempts": 0,
        "status": None,
        "error": None,
    }

    if _streaming_disabled():
        status["disabled"] = True
        status["status"] = "disabled"
        return status

    attempts = max(1, int(max_attempts))
    last_exc = None
    for _ in range(attempts):
        status["attempts"] += 1
        try:
            with socket.create_connection((host, int(port)), timeout=float(timeout_s)):
                status["status"] = "ok"
                return status
        except Exception as exc:
            last_exc = exc

    status["status"] = "refused"
    if last_exc is not None:
        status["error"] = str(last_exc)
    return status
def _wait_for_ports(
    host: str,
    rpc_port: int,
    streaming_port: int,
    timeout_s: float = 30.0,
    *,
    require_streaming: bool = False,
) -> bool:
    """
    Wait until CARLA is reachable.

    By default, streaming is treated as optional and this waits for RPC only.
    If `require_streaming=True`, waits for both RPC and streaming ports.
    """
    deadline = time.time() + float(timeout_s)
    while time.time() < deadline:
        if _port_open(host, rpc_port) and (not require_streaming or _port_open(host, streaming_port)):
            return True
        time.sleep(0.2)
    return False

# --------------------------------------------------------------------------
# Crash persistence
# --------------------------------------------------------------------------
def dump_carla_crash(context: dict):
    """
    Persist CARLA crash context to disk for post-mortem analysis.
    This MUST be safe to call even when CARLA is half-dead.
    """
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "logs", "carla_crashes")
    )
    os.makedirs(base_dir, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(base_dir, f"carla_crash_{ts}.json")

    payload = {
        "timestamp_utc": ts,
        "host": SETTINGS.CARLA_HOST,
        "port": SETTINGS.CARLA_PORT,
        **context,
    }

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"💾 CARLA crash dump written → {out_path}")
    except Exception as e:
        print(f"⚠ Failed to write CARLA crash dump: {e}")

def _kill_stale_processes():
    """Kill leftover Unreal/Carla processes."""
    if not _PSUTIL_AVAILABLE:
        # Soft-fail on environments where psutil isn't installed
        return
    targets = ["CarlaUE4", "UE4Editor", "UE4Editor-Cmd", "CarlaUE4-Win64-Shipping"]

    for proc in psutil.process_iter(["pid", "name"]):
        name = proc.info["name"]
        if not name:
            continue
        if any(t in name for t in targets):
            try:
                proc.kill()
                proc.wait(1)
                print(f"💀 Killed stale CARLA process: {name}")
            except Exception:
                pass


def _purge_temp_dirs():
    """Delete directories that often corrupt CARLA loads."""
    paths = [
        os.path.join(os.getenv("LOCALAPPDATA", ""), "CarlaUE4"),
        os.path.join(os.getenv("APPDATA", ""), "CarlaUE4"),
    ]

    temp = os.getenv("TEMP")
    if temp:
        for entry in os.listdir(temp):
            if "Carla" in entry:
                paths.append(os.path.join(temp, entry))

    for p in paths:
        if os.path.exists(p):
            try:
                shutil.rmtree(p, ignore_errors=True)
                print(f"🧹 Purged CARLA cache directory: {p}")
            except Exception as e:
                print(f"⚠ Could not purge {p}: {e}")


def _start_carla():
    """Start CARLA server in detached mode."""
    exe = SETTINGS.CARLA_SERVER_PATH
    if not exe or not os.path.exists(exe):
        raise RuntimeError(f"CARLA exe missing: {exe}")

    print("🚀 Starting CARLA server…")

    if sys.platform.startswith("win"):
        subprocess.Popen(
            [exe, "-quality-level=Low", "-RenderOffScreen"],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(
            [exe, "-quality-level=Low", "-RenderOffScreen"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def _create_client() -> carla.Client:
    """Try to construct a CARLA client instance."""
    host = SETTINGS.CARLA_HOST
    port = SETTINGS.CARLA_PORT
    c = carla.Client(host, port)
    c.set_timeout(SETTINGS.CARLA_TIMEOUT)
    _ = c.get_world()  # health check
    return c

def restart_carla(
    host: str | None = None,
    port: int | None = None,
    streaming_port: int | None = None,
    startup_wait_s: float | None = None,
    retries: int | None = None,
) -> bool:
    """
    Retry CARLA startup until RPC is open (and streaming too, if enabled).
    """
    h = host or SETTINGS.CARLA_HOST
    p = int(port or SETTINGS.CARLA_PORT)
    sp = int(streaming_port or (p + 1))
    wait_s = float(startup_wait_s or SETTINGS.CARLA_STARTUP_WAIT)
    max_tries = int(retries or SETTINGS.CARLA_CONNECT_RETRIES)

    # Reset CARLA and purge cache
    if SETTINGS.CARLA_KILL_ON_FAIL:
        _kill_stale_processes()
        _purge_temp_dirs()

    _start_carla()

    require_streaming = not _streaming_disabled()

    # Retry connection until RPC (and optionally streaming) port(s) are open
    t0 = time.time()
    for _ in range(max_tries):
        # Give CARLA time to start up
        time.sleep(wait_s)
        if _wait_for_ports(h, p, sp, timeout_s=wait_s, require_streaming=require_streaming):
            return True
        time.sleep(3)  # Allow some time before retrying

    # Final check after retries window
    if _port_open(h, p) and (not require_streaming or _port_open(h, sp)):
        return True

    # If we reach here, the connection failed
    dump_carla_crash({
        "failure_type": "restart_carla_failed",
        "host": h,
        "port": p,
        "streaming_port": sp,
        "require_streaming": require_streaming,
        "elapsed_s": round(time.time() - t0, 2),
    })
    return False


# --------------------------------------------------------------------------
# Unified Public API
# --------------------------------------------------------------------------
def get_reliable_client() -> carla.Client:
    """
    Full recovery pipeline:
    1. Check port
    2. If blocked → kill stale processes
    3. Purge caches
    4. (Re)start CARLA if needed
    5. Retry connection until stable (including streaming port)
    """
    host = SETTINGS.CARLA_HOST
    port = SETTINGS.CARLA_PORT
    streaming_port = getattr(SETTINGS, "CARLA_STREAMING_PORT", None) or (port + 1)
    streaming_status = probe_streaming_port(
        host,
        int(streaming_port),
        timeout_s=0.4,
        max_attempts=1,
    )
    if streaming_status.get("status") in ("refused", "disabled"):
        print(
            f"? Streaming port optional (status={streaming_status.get('status')}, "
            f"port={streaming_status.get('port')}). Continuing with RPC-only."
        )

    attempts = 0
    while attempts < SETTINGS.CARLA_CONNECT_RETRIES:
        attempts += 1

        # If RPC port open -> try to connect (streaming is optional).
        if _port_open(host, port):
            try:
                client = _create_client()
                print(f"?? Connected to CARLA successfully (RPC:{port}, Stream:{streaming_port}).")
                return client
            except Exception:
                print("? CARLA responded but world unavailable - purging + restart")
                if SETTINGS.CARLA_KILL_ON_FAIL:
                    _kill_stale_processes()
                    _purge_temp_dirs()
                time.sleep(2)

        elif SETTINGS.CARLA_KILL_ON_FAIL:
            # Port closed or unusable → kill + purge + start
            _kill_stale_processes()
            _purge_temp_dirs()

        _start_carla()

        print(f"⏳ Waiting {SETTINGS.CARLA_STARTUP_WAIT:.0f}s for CARLA to boot (Attempt {attempts}/{SETTINGS.CARLA_CONNECT_RETRIES})…")
        time.sleep(SETTINGS.CARLA_STARTUP_WAIT)

    dump_carla_crash({
        "failure_type": "connection_failure",
        "attempts": attempts,
        "host": host,
        "port": port,
        "streaming_port": streaming_port,
        "stage": "get_reliable_client_exhausted",
    })

    raise RuntimeError(f"❌ Could not establish CARLA connection (RPC:{port}, Stream:{streaming_port}) after recovery steps.")


def safe_load_xodr(client, xodr_path: str, label: str):
    """
    Load XODR with full recovery fallback.
    If CARLA crashes → restart and retry exactly once.
    """
    from ultimate_pipeline.core.carla_utils import carla_load_xodr_with_restart

    loaded, new_client = carla_load_xodr_with_restart(client, xodr_path, label)
    if loaded:
        return True, new_client

    dump_carla_crash({
        "failure_type": "xodr_load_failure",
        "map_label": label,
        "xodr_path": xodr_path,
        "stage": "safe_load_xodr",
    })

    print(f"⚠ CARLA failed to load {label}, performing full recovery…")
    new_client = get_reliable_client()

    loaded, new_client = carla_load_xodr_with_restart(new_client, xodr_path, label)
    return loaded, new_client
