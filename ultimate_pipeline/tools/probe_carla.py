#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnostic tool: probe CARLA connectivity and world loading.

Works on Windows PowerShell (no heredocs required).

Usage:
    python -m ultimate_pipeline.tools.probe_carla
    python -m ultimate_pipeline.tools.probe_carla --town Grid0821
    python -m ultimate_pipeline.tools.probe_carla --host 127.0.0.1 --port 2000 --timeout 3
"""
from __future__ import annotations

import argparse
import socket
import sys
import time


from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
def check_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check if TCP port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def check_rpc(host: str, port: int, timeout: float = 3.0) -> tuple[bool, str]:
    """Check if CARLA RPC responds. Returns (success, version_or_error)."""
    try:
        import carla
        client = carla.Client(host, port)
        client.set_timeout(timeout)
        version = client.get_server_version()
        return True, version
    except Exception as e:
        return False, str(e)


def get_current_world_info(host: str, port: int, timeout: float = 5.0) -> dict:
    """Get info about currently loaded world."""
    import carla
    client = carla.Client(host, port)
    client.set_timeout(timeout)

    try:
        world = client.get_world()
        carla_map = world.get_map()
        spawn_points = carla_map.get_spawn_points()
        return {
            "success": True,
            "map_name": carla_map.name,
            "spawn_count": len(spawn_points),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def try_load_world(host: str, port: int, town: str, timeout: float = 60.0) -> dict:
    """Attempt to load a world by name."""
    import carla
    client = carla.Client(host, port)
    client.set_timeout(timeout)

    try:
        print(f"[LOAD] Loading world '{town}'...")
        _reload_ready_for_sensors(client, map_name=town, tm_port=8000)

        # Wait for world to be ready
        for i in range(30):
            try:
                world = client.get_world()
                if world:
                    carla_map = world.get_map()
                    if carla_map:
                        spawn_points = carla_map.get_spawn_points()
                        return {
                            "success": True,
                            "map_name": carla_map.name,
                            "spawn_count": len(spawn_points),
                        }
            except Exception:
                pass
            time.sleep(0.5)

        return {"success": False, "error": "World loaded but not ready after 15s"}
    except Exception as e:
        # Check if CARLA crashed
        if not check_tcp(host, port, timeout=2.0):
            return {
                "success": False,
                "error": f"CARLA likely crashed during load (port closed). Original: {e}",
                "crashed": True,
            }
        return {"success": False, "error": str(e)}


def get_available_maps(host: str, port: int, timeout: float = 3.0) -> list[str]:
    """Get available maps (best-effort, short timeout)."""
    try:
        import carla
        client = carla.Client(host, port)
        client.set_timeout(timeout)
        return client.get_available_maps()
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser(description="Probe CARLA connectivity and world loading")
    parser.add_argument("--host", default="127.0.0.1", help="CARLA host")
    parser.add_argument("--port", type=int, default=2000, help="CARLA port")
    parser.add_argument("--timeout", type=float, default=3.0, help="RPC timeout in seconds")
    parser.add_argument("--town", help="Optional: attempt to load this world")
    parser.add_argument("--list-maps", action="store_true", help="List available maps")
    args = parser.parse_args()

    print(f"=== CARLA Probe: {args.host}:{args.port} ===\n")

    # Stage 1: TCP check
    print("[TCP] Checking port...", end=" ")
    tcp_ok = check_tcp(args.host, args.port, timeout=2.0)
    if tcp_ok:
        print("OK (port open)")
    else:
        print("FAILED (port closed)")
        print("\nCARLA is not running or not listening on this port.")
        print("Start CARLA first:")
        print(r"  E:\CARLA\CARLA_0.9.16\CarlaUE4.exe")
        return 1

    # Stage 2: RPC check
    print(f"[RPC] Checking get_server_version (timeout={args.timeout}s)...", end=" ")
    rpc_ok, rpc_result = check_rpc(args.host, args.port, timeout=args.timeout)
    if rpc_ok:
        print(f"OK (version: {rpc_result})")
    else:
        print(f"FAILED")
        print(f"  Error: {rpc_result}")
        print("\nPort is open but CARLA RPC is not responding.")
        print("CARLA may be starting up, hung, or crashed.")
        return 2

    # Stage 3: Current world info
    print("[WORLD] Getting current world info...", end=" ")
    world_info = get_current_world_info(args.host, args.port)
    if world_info["success"]:
        print(f"OK")
        print(f"  Map: {world_info['map_name']}")
        print(f"  Spawn points: {world_info['spawn_count']}")
    else:
        print(f"FAILED: {world_info.get('error', 'unknown')}")

    # Optional: list available maps
    if args.list_maps:
        print("[MAPS] Getting available maps...", end=" ")
        maps = get_available_maps(args.host, args.port)
        if maps:
            print(f"OK ({len(maps)} maps)")
            for m in maps:
                print(f"  - {m}")
        else:
            print("FAILED or no maps found")

    # Optional: try loading a world
    if args.town:
        print(f"\n[LOAD] Attempting to load '{args.town}'...")
        load_result = try_load_world(args.host, args.port, args.town, timeout=60.0)
        if load_result["success"]:
            print(f"  SUCCESS")
            print(f"  Map: {load_result['map_name']}")
            print(f"  Spawn points: {load_result['spawn_count']}")
        else:
            print(f"  FAILED: {load_result['error']}")
            if load_result.get("crashed"):
                return 3
            return 4

    print("\n=== Probe complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
