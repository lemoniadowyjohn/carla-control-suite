#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lightweight CARLA connectivity probe.

Run:
  python -m ultimate_pipeline.tools.carla_probe_port --host 127.0.0.1 --port 2000
"""

from __future__ import annotations

import argparse
import socket
from typing import Any, Dict, Tuple


def _tcp_open(host: str, port: int, timeout: float) -> Tuple[bool, str | None]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except Exception as exc:
        return False, str(exc)


def probe_carla(host: str, port: int, *, tcp_timeout: float = 2.0, rpc_timeout: float = 5.0) -> Dict[str, Any]:
    """
    Probe CARLA availability.
    Returns a dict describing TCP status and minimal RPC health.
    """
    result: Dict[str, Any] = {
        "host": host,
        "port": int(port),
        "tcp_open": False,
        "rpc_status": "unknown",
        "error": None,
        "suggestions": [],
    }

    open_ok, err = _tcp_open(host, port, tcp_timeout)
    result["tcp_open"] = open_ok
    if not open_ok:
        result["rpc_status"] = "PORT_CLOSED"
        result["error"] = err
        result["suggestions"].append("Start CARLA (e.g., CARLAUE4.exe -carla-port=2000) or adjust --port.")
        result["suggestions"].append("Check firewall/antivirus allowing TCP on the chosen port.")
        return result

    try:
        import carla  # type: ignore
    except Exception as exc:  # pragma: no cover
        result["rpc_status"] = "OPEN_BUT_CARLA_IMPORT_FAILED"
        result["error"] = str(exc)
        result["suggestions"].append("CARLA egg not on PYTHONPATH or Python version mismatch.")
        return result

    try:
        client = carla.Client(host, int(port))  # type: ignore
        client.set_timeout(float(rpc_timeout))
        _ = client.get_world()
        result["rpc_status"] = "HEALTHY"
    except Exception as exc:
        result["rpc_status"] = "OPEN_BUT_RPC_DEAD"
        result["error"] = str(exc)
        result["suggestions"].append("Start CARLA server or verify it is fully loaded.")
        result["suggestions"].append("If CARLA is running, check matching port and version (e.g., -carla-port).")

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe CARLA port availability.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--tcp-timeout", type=float, default=2.0)
    ap.add_argument("--rpc-timeout", type=float, default=5.0)
    args = ap.parse_args()

    res = probe_carla(args.host, args.port, tcp_timeout=args.tcp_timeout, rpc_timeout=args.rpc_timeout)

    print(f"[CARLA PROBE] host={res['host']} port={res['port']}")
    print(f"  tcp_open: {res['tcp_open']}")
    print(f"  rpc_status: {res['rpc_status']}")
    if res.get("error"):
        print(f"  error: {res['error']}")
    if res.get("suggestions"):
        print("  suggestions:")
        for s in res["suggestions"]:
            print(f"    - {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
