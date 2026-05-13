#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CARLA readiness probe (Windows-safe).

Use this script from PowerShell to verify CARLA RPC before running pipelines.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path
from typing import Tuple

from ultimate_pipeline.core.carla_opendrive_loader import (
    ensure_world_ticks,
    load_opendrive_world,
)
from ultimate_pipeline.carla_tools.reload_ready_for_sensors import (
    _reload_ready_for_sensors,
)

_CARLA_EXE_HINT = r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"


def tcp_probe(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def rpc_probe(host: str, port: int, timeout_s: float) -> Tuple[str, object]:
    import carla  # lazy import

    client = carla.Client(host, port)
    client.set_timeout(timeout_s)
    version = client.get_server_version()
    return version, client


def load_town(client, town: str, load_timeout: float) -> Tuple[str, int]:
    client.set_timeout(load_timeout)
    world = _reload_ready_for_sensors(client, map_name=town, tm_port=8000)
    carla_map = world.get_map()
    ensure_world_ticks(
        world,
        n=int(os.environ.get("UP_CARLA_READY_TICKS", "3")),
        timeout_per_tick_s=float(os.environ.get("UP_CARLA_READY_TICK_TIMEOUT_S", "2.0")),
    )
    name = carla_map.name if carla_map else "unknown"
    spawns = carla_map.get_spawn_points() if carla_map else []
    return name, len(spawns)


def load_xodr(client, xodr_path: Path, load_timeout: float) -> Tuple[str, int]:
    xodr_text = xodr_path.read_text(encoding="utf-8", errors="ignore")
    world = load_opendrive_world(
        client,
        xodr_text,
        params=None,
        timeout_s=load_timeout,
        retries=0,
        do_reload=True,
        fallback_enabled=False,
        fallback_maps=None,
    )
    carla_map = world.get_map()
    ensure_world_ticks(
        world,
        n=int(os.environ.get("UP_CARLA_READY_TICKS", "3")),
        timeout_per_tick_s=float(os.environ.get("UP_CARLA_READY_TICK_TIMEOUT_S", "2.0")),
    )
    name = carla_map.name if carla_map else "unknown"
    spawns = carla_map.get_spawn_points() if carla_map else []
    return name, len(spawns)
import random
from typing import Any, Iterable, List, Optional, Tuple

def _spawn_props(
    world: Any,
    ego_tf_or_actor: Any,
    *,
    count: int = 5,
    seed: int = 0,
    blueprint_ids: Optional[List[str]] = None,
    offsets: Optional[List[Tuple[float, float, float]]] = None,
) -> List[Any]:
    """
    Spawn simple static props near the ego (import-safe helper).

    - Must not import carla at module import time.
    - Must not mutate the provided ego transform.
    - Works with Dummy* test classes as well as real CARLA objects.

    Returns list of spawned actors (or empty list if spawning fails).
    """
    rng = random.Random(int(seed))

    # Accept either a transform-like object or an actor-like object.
    base_tf = ego_tf_or_actor.get_transform() if hasattr(ego_tf_or_actor, "get_transform") else ego_tf_or_actor
    base_loc = getattr(base_tf, "location", None)
    base_rot = getattr(base_tf, "rotation", None)

    if base_loc is None or base_rot is None:
        return []

    if blueprint_ids is None:
        blueprint_ids = [
            "static.prop.trafficcone01",
            "static.prop.streetbarrier",
            "static.prop.constructioncone",
            "static.prop.barrier",
        ]

    if offsets is None:
        # (forward, right, up) in *world axes* (good enough for QA + unit tests)
        offsets = [
            (8.0, 0.0, 0.0),
            (10.0, 1.5, 0.0),
            (10.0, -1.5, 0.0),
            (14.0, 0.0, 0.0),
            (18.0, 2.5, 0.0),
        ]

    # --- clone helpers (work for Dummy classes and carla.Location/Rotation/Transform) ---
    def _clone_location(src: Any, *, dx: float, dy: float, dz: float) -> Any:
        cls = type(src)
        x = float(getattr(src, "x", 0.0)) + float(dx)
        y = float(getattr(src, "y", 0.0)) + float(dy)
        z = float(getattr(src, "z", 0.0)) + float(dz)
        # Try common constructor styles
        try:
            return cls(x=x, y=y, z=z)
        except Exception:
            try:
                return cls(x, y, z)
            except Exception:
                obj = cls()
                setattr(obj, "x", x)
                setattr(obj, "y", y)
                setattr(obj, "z", z)
                return obj

    def _clone_rotation(src: Any) -> Any:
        cls = type(src)
        kwargs = {}
        for k in ("pitch", "yaw", "roll"):
            if hasattr(src, k):
                kwargs[k] = float(getattr(src, k))
        # DummyRotation(yaw=...) only supports yaw
        try:
            return cls(**kwargs)
        except Exception:
            try:
                return cls(kwargs.get("yaw", 0.0))
            except Exception:
                obj = cls()
                for k, v in kwargs.items():
                    try:
                        setattr(obj, k, v)
                    except Exception:
                        pass
                return obj

    def _make_transform(loc: Any, rot: Any) -> Any:
        cls = type(base_tf)
        try:
            return cls(loc, rot)
        except Exception:
            try:
                return cls(location=loc, rotation=rot)
            except Exception:
                obj = cls()
                setattr(obj, "location", loc)
                setattr(obj, "rotation", rot)
                return obj

    spawned: List[Any] = []
    bp_lib = world.get_blueprint_library() if hasattr(world, "get_blueprint_library") else None

    for i in range(int(max(0, count))):
        dx, dy, dz = offsets[i % len(offsets)]
        tf = _make_transform(_clone_location(base_loc, dx=dx, dy=dy, dz=dz), _clone_rotation(base_rot))

        bp_id = blueprint_ids[i % len(blueprint_ids)]
        bp = None
        if bp_lib is not None:
            try:
                bp = bp_lib.find(bp_id)
            except Exception:
                bp = None

        if bp is None:
            # Fallback: try filter API if present
            try:
                choices = bp_lib.filter("static.prop.*") if bp_lib is not None else []
                bp = choices[0] if choices else None
            except Exception:
                bp = None

        try:
            actor = world.try_spawn_actor(bp, tf)
        except Exception:
            actor = None

        if actor is not None:
            spawned.append(actor)

    return spawned


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="CARLA TCP/RPC probe and optional map load.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--rpc-timeout", type=float, default=3.0, help="RPC timeout for probe (seconds)")
    ap.add_argument("--load-timeout", type=float, default=60.0, help="Timeout for map load (seconds)")
    ap.add_argument("--town", help="Optional CARLA world to load (e.g., Grid0821, Grid0828)")
    ap.add_argument("--xodr", help="Optional OpenDRIVE .xodr to load")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    host, port = args.host, int(args.port)

    print(f"[TCP] Probing {host}:{port} ...")
    if not tcp_probe(host, port, timeout=2.0):
        print(f"[FAIL] Port {host}:{port} is closed. Start CARLA:\n  {_CARLA_EXE_HINT}")
        return 2
    print("[OK] TCP port is open.")

    try:
        version, client = rpc_probe(host, port, timeout_s=float(args.rpc_timeout))
        print(f"[OK] RPC responsive. Server version: {version}")
    except Exception as e:
        print(f"[FAIL] Port {host}:{port} is reachable but RPC not responding within {args.rpc_timeout}s.")
        print("       CARLA may be starting, hung, crashed, or another process is using this port.")
        print(f"       Error: {e}")
        print(f"       Start/restart CARLA:\n         {_CARLA_EXE_HINT}")
        return 3

    # Optional map loads (best-effort)
    if args.town:
        print(f"[LOAD] Loading town '{args.town}' (timeout {args.load_timeout}s)...")
        try:
            name, spawn_count = load_town(client, args.town, float(args.load_timeout))
            print(f"[OK] Loaded map: {name} | spawn points: {spawn_count}")
        except Exception as e:
            print(f"[FAIL] Town load failed: {e}")
            port_open = tcp_probe(host, port, timeout=2.0)
            if not port_open:
                print("[DIAG] TCP port closed after failure. CARLA likely crashed.")
            else:
                print("[DIAG] TCP still open; RPC hung or map load failed.")
            return 4

    if args.xodr:
        xodr_path = Path(args.xodr)
        print(f"[LOAD] Loading XODR '{xodr_path.name}' (timeout {args.load_timeout}s)...")
        try:
            name, spawn_count = load_xodr(client, xodr_path, float(args.load_timeout))
            print(f"[OK] Loaded map: {name} | spawn points: {spawn_count}")
        except Exception as e:
            print(f"[FAIL] XODR load failed: {e}")
            port_open = tcp_probe(host, port, timeout=2.0)
            if not port_open:
                print("[DIAG] TCP port closed after failure. CARLA likely crashed.")
            else:
                print("[DIAG] TCP still open; RPC hung or map load failed.")
            return 5

    return 0


if __name__ == "__main__":
    sys.exit(main())
