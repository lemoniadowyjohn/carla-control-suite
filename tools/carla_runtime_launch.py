#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Launch CARLA 0.9.16 server with explicit process ownership tracking.

Establishes: PID, exe SHA256, creation time, RPC port, streaming port, launch
command, run ID. Never performs a global taskkill -- only ever terminates the
exact PID this module started, and only when explicitly asked to.

Exit codes:
  0  runtime ready (client.get_server_version + world.get_map + snapshot/tick all OK)
  2  BLOCKED_ENVIRONMENT (launch or RPC failed; diagnostics preserved)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CARLA_EXE = Path(r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe")
LOG_DIR = Path("reports/carla_runtime")


def sha256_file(p: Path) -> str:
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


def wait_port(port: int, deadline_s: float, host: str = "127.0.0.1") -> bool:
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        if port_listening(port, host, timeout=1.0):
            return True
        time.sleep(1.0)
    return False


def existing_carla_pids() -> List[int]:
    """Enumerate (do not kill) pre-existing CARLA instances."""
    pids: List[int] = []
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process -Name 'CarlaUE4*' -ErrorAction SilentlyContinue "
                "| Select-Object -ExpandProperty Id",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
    except Exception:
        pass
    return pids


def rpc_probe(timeout: float = 25.0, port: int = 2000) -> Dict[str, Any]:
    res: Dict[str, Any] = {
        "client_import_ok": False,
        "get_server_version": None,
        "get_available_maps_count": None,
        "world_get_map": None,
        "snapshot_frame": None,
        "snapshot_timestamp": None,
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
        client = carla.Client("127.0.0.1", port)
        client.set_timeout(timeout)
        res["get_server_version"] = client.get_server_version()
        res["get_available_maps_count"] = len(client.get_available_maps())
        world = client.get_world()
        res["world_get_map"] = world.get_map().name
        snap = world.get_snapshot()
        if snap is not None:
            res["snapshot_frame"] = snap.frame
            res["snapshot_timestamp"] = float(snap.timestamp.elapsed_seconds)
        res["error"] = ""
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Launch and qualify CARLA 0.9.16 runtime")
    ap.add_argument("--wait-port-seconds", type=float, default=180.0)
    ap.add_argument("--rpc-timeout", type=float, default=25.0)
    ap.add_argument(
        "--extra-args",
        nargs="*",
        default=[
            "-RenderOffScreen",
            "-quality-level=Low",
            "-nosound",
        ],
    )
    ap.add_argument("--no-launch", action="store_true", help="probe only, do not start")
    ap.add_argument("--rpc-port", type=int, default=2000,
                    help="isolated server lease: CARLA -carla-rpc-port (default 2000)")
    ap.add_argument("--streaming-port", type=int, default=2001,
                    help="isolated server lease: CARLA -carla-streaming-port (default 2001)")
    args = ap.parse_args()

    run_id = f"carla_run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout_log = LOG_DIR / f"{run_id}_stdout.log"
    stderr_log = LOG_DIR / f"{run_id}_stderr.log"

    pre_existing = existing_carla_pids()
    report: Dict[str, Any] = {
        "schema": "carla_runtime_launch/v2",
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "carla_exe": str(CARLA_EXE),
        "carla_exe_present": CARLA_EXE.is_file(),
        "carla_version_target": "0.9.16",
        "pre_existing_carla_pids": pre_existing,
        "pre_existing_not_killed": True,
        "rpc_port": args.rpc_port,
        "streaming_port": args.streaming_port,
        "owned_pid": None,
        "owned_pid_creation_time": None,
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
    }

    if not report["carla_exe_present"]:
        report["verdict"] = "BLOCKED_ENVIRONMENT"
        report["blocker"] = f"CARLA executable not present at {CARLA_EXE}"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    report["carla_exe_sha256"] = sha256_file(CARLA_EXE)
    report["carla_exe_bytes"] = CARLA_EXE.stat().st_size

    proc: Optional[subprocess.Popen] = None
    if not args.no_launch:
        cmd = [
            str(CARLA_EXE),
            f"-carla-rpc-port={args.rpc_port}",
            f"-carla-streaming-port={args.streaming_port}",
            *args.extra_args,
        ]
        report["launch_command"] = " ".join(cmd)
        out_fh = stdout_log.open("w", encoding="utf-8", errors="replace")
        err_fh = stderr_log.open("w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            cwd=str(CARLA_EXE.parent),
            stdout=out_fh,
            stderr=err_fh,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        report["owned_pid"] = proc.pid
        report["owned_pid_creation_time_utc"] = datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )

        listening = wait_port(args.rpc_port, args.wait_port_seconds)
        report["rpc_port_listening"] = listening
        report["port_wait_seconds"] = round(args.wait_port_seconds, 1)
        if not listening:
            report["verdict"] = "BLOCKED_ENVIRONMENT"
            report["blocker"] = (
                f"CARLA RPC port {args.rpc_port} did not become listenable within "
                f"{args.wait_port_seconds:.0f}s after launching PID {proc.pid}"
            )
            report["stdout_tail"] = stdout_log.read_text(
                encoding="utf-8", errors="replace"
            )[-4000:]
            report["stderr_tail"] = stderr_log.read_text(
                encoding="utf-8", errors="replace"
            )[-4000:]
            print(json.dumps(report, indent=2, sort_keys=True))
            return 2
        report["streaming_port_listening"] = port_listening(args.streaming_port)
    else:
        report["rpc_port_listening"] = port_listening(args.rpc_port)
        report["streaming_port_listening"] = port_listening(args.streaming_port)
        report["launch_command"] = None
        report["probe_only"] = True

    report["rpc"] = rpc_probe(args.rpc_timeout, port=args.rpc_port)
    ready = (
        report["rpc"].get("get_server_version") is not None
        and report["rpc"].get("world_get_map") is not None
        and report["rpc"].get("snapshot_frame") is not None
    )
    report["runtime_ready"] = bool(ready)
    report["verdict"] = "RUNTIME_READY" if ready else "BLOCKED_ENVIRONMENT"
    if not ready:
        report["blocker"] = report["rpc"].get("error") or "RPC probe incomplete"

    out_path = LOG_DIR / f"{run_id}_REPORT.json"
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nreport: {out_path}")
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())