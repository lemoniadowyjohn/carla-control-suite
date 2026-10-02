#!/usr/bin/env python3
"""CARLA runtime probe: process ownership, port state, RPC handshake.

Establishes PID/exe SHA/creation time/ports/launch command/run ID without
killing any unrelated CARLA instance.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CARLA_EXE = Path(r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe")
PORTS = {"rpc": 2000, "stream": 2001, "secondary": 2002}


def sha256_file(p: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def port_listening(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_carla_pids() -> List[Dict[str, Any]]:
    """Enumerate existing CARLA processes without killing them."""
    out: List[Dict[str, Any]] = []
    try:
        ps = (
            "Get-CimInstance Win32_Process -Filter "
            "\"Name like '%CarlaUE4%'\" | Select-Object ProcessId,Name,CreationDate,"
            "ExecutablePath,CommandLine | ConvertTo-Json -Compress"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        raw = (r.stdout or "").strip()
        if not raw:
            return out
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        for d in data:
            out.append(
                {
                    "pid": d.get("ProcessId"),
                    "name": d.get("Name"),
                    "creation_date": d.get("CreationDate"),
                    "executable_path": d.get("ExecutablePath"),
                    "command_line": d.get("CommandLine"),
                }
            )
    except Exception as e:  # pragma: no cover - diagnostics only
        out.append({"error": f"{type(e).__name__}: {e}"})
    return out


def rpc_probe() -> Dict[str, Any]:
    res: Dict[str, Any] = {
        "client_import_ok": False,
        "get_server_version": None,
        "get_available_maps_count": None,
        "world_get_map": None,
        "snapshot_tick": None,
        "error": "",
    }
    try:
        import carla  # noqa
    except Exception as e:
        res["error"] = f"carla import failed: {type(e).__name__}: {e}"
        return res
    res["client_import_ok"] = True

    client = None
    try:
        client = carla.Client("127.0.0.1", PORTS["rpc"])
        client.set_timeout(20.0)
        res["get_server_version"] = client.get_server_version()
        res["get_available_maps_count"] = len(client.get_available_maps())
        world = client.get_world()
        res["world_get_map"] = world.get_map().name
        snap = world.get_snapshot()
        res["snapshot_tick"] = snap.frame if snap is not None else None
        res["error"] = ""
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            if client is not None:
                client.apply_settings  # noqa - ensure attribute access
        except Exception:
            pass
    return res


def main() -> int:
    run_id = f"carla_probe_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    report: Dict[str, Any] = {
        "schema": "carla_runtime_probe/v1",
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "carla_exe": str(CARLA_EXE),
        "carla_exe_present": CARLA_EXE.is_file(),
        "existing_carla_processes": find_carla_pids(),
        "ports": {
            name: {"port": p, "listening": port_listening(p)} for name, p in PORTS.items()
        },
    }
    if report["carla_exe_present"]:
        report["carla_exe_sha256"] = sha256_file(CARLA_EXE)
        report["carla_exe_bytes"] = CARLA_EXE.stat().st_size

    report["rpc"] = rpc_probe()
    ready = (
        report["rpc"].get("get_server_version") is not None
        and report["rpc"].get("world_get_map") is not None
    )
    report["runtime_ready"] = bool(ready)

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())