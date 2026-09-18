#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Safe TileSpawnProbe (2025 Edition)

Robust spawn-point validation for CARLA tile maps.

Features:
- Auto-restart CARLA when port dies
- Fallback geoReference when missing or malformed
- Spectator camera pinned overhead (debug-friendly)
- Clean actor cleanup (no destroy-errors)
- Stable even on heavy maps
"""

from __future__ import annotations

import time
import os
import json
import math
import re
from typing import List, Dict, Any, TYPE_CHECKING

# Import-safety: this module is often imported by tooling even when CARLA isn't installed.
try:  # pragma: no cover
    import carla  # type: ignore
    _CARLA_AVAILABLE = True
except Exception:  # pragma: no cover
    carla = None  # type: ignore
    _CARLA_AVAILABLE = False

if TYPE_CHECKING:  # pragma: no cover
    import carla as carla_type  # noqa: F401

from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

from ultimate_pipeline.core.carla_utils import (
    _port_open as _carla_port_open,
    ensure_carla_ready,
)


class TileSpawnProbe:
    def __init__(
        self,
        client: carla.Client,
        tiles_dir: str,
        tile_names: List[str],
        out_dir: str,
        max_spawns_per_tile: int = 25,
        offset_m: float = 1.3,
        host: str = "127.0.0.1",
        port: int = 2000,
    ) -> None:

        self.client = client
        self.tiles_dir = tiles_dir
        self.tile_names = tile_names
        self.out_dir = out_dir
        self.max_spawns_per_tile = max_spawns_per_tile
        self.offset_m = offset_m
        self.host = host
        self.port = port

        self.results: Dict[str, Any] = {"tiles": {}}

    # ------------------------------------------------------------
    # Offset transform
    # ------------------------------------------------------------
    def _offset_transform(self, tr: carla.Transform) -> carla.Transform:
        if self.offset_m <= 0:
            return tr

        yaw = math.radians(tr.rotation.yaw)
        dx = self.offset_m * math.cos(yaw)
        dy = self.offset_m * math.sin(yaw)

        return carla.Transform(
            carla.Location(
                x=tr.location.x + dx,
                y=tr.location.y + dy,
                z=tr.location.z,
            ),
            tr.rotation,
        )

    # ------------------------------------------------------------
    # Set spectator camera for debugging
    # ------------------------------------------------------------
    def _set_spectator_overhead(self, world: carla.World):
        try:
            spectator = world.get_spectator()
            tf = carla.Transform(
                carla.Location(z=90.0),
                carla.Rotation(pitch=-90.0)
            )
            spectator.set_transform(tf)
        except Exception:
            # Non-fatal
            pass

    # ------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------
    def run(self) -> None:
        print("▶ TileSpawnProbe starting…")

        for tile_name in self.tile_names:

            tile_path = os.path.join(self.tiles_dir, tile_name)
            if not os.path.exists(tile_path):
                print(f"⚠ Tile not found: {tile_path}")
                continue

            print(f"\n▶ Probing {tile_name}")

            # CARLA must be alive before loading a new tile.
            if not _carla_port_open(self.host, self.port):
                print("❌ CARLA offline before probe. Restarting…")
                self.client = _ensure_carla_ready_compat(self.host, self.port)

            try:
                tile_result = self._probe_tile(tile_path)
            except Exception as e:
                print(f"❌ Spawn-probe crash: {e}")
                print("🔧 Restarting CARLA…")
                self.client = _ensure_carla_ready_compat(self.host, self.port)
                continue

            self.results["tiles"][tile_name] = tile_result

        out_path = os.path.join(self.out_dir, "tile_spawn_probe.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2)

        print(f"\n💾 Saved TileSpawnProbe report → {out_path}")

    # ------------------------------------------------------------
    # Probe a single tile
    # ------------------------------------------------------------
    def _probe_tile(self, tile_path: str) -> Dict[str, Any]:

        if not _carla_port_open(self.host, self.port):
            raise RuntimeError("CARLA offline during tile load")

        with open(tile_path, encoding="utf-8") as f:
            xodr = f.read()

        # Fallback geoReference patch (prevents many CARLA warnings)
        # Insert into <header ...> if missing.
        if "<geoReference" not in xodr:
            m_hdr = re.search(r"<header[^>]*>", xodr)
            if m_hdr:
                hdr_tag = m_hdr.group(0)
                geo = (
                    "<geoReference>+proj=tmerc +lat_0=0 +lon_0=0 "
                    "+k=1 +x_0=0 +y_0=0 +units=m +no_defs</geoReference>"
                )
                xodr = xodr.replace(hdr_tag, hdr_tag + "\n" + geo)

        params = carla.OpendriveGenerationParameters()
        params.map_layers = carla.MapLayer.NONE

        # Generate tile world
        world = load_opendrive_world(
            self.client,
            xodr,
            params=params,
            timeout_s=180.0,
            retries=2,
            do_reload=True,
        )
        self._set_spectator_overhead(world)

        c_map = world.get_map()
        spawns = c_map.get_spawn_points()

        if not spawns:
            print("❌ No spawn points in tile")
            return {
                "num_spawn_points": 0,
                "tested": 0,
                "success": 0,
                "fail": 0,
                "details": [],
            }

        bps = world.get_blueprint_library().filter("vehicle.*")
        if not bps:
            print("⚠ No vehicle blueprints available")
            return {
                "num_spawn_points": len(spawns),
                "tested": 0,
                "success": 0,
                "fail": 0,
                "details": [],
            }

        bp = bps[0]

        tested = success = fail = 0
        details = []

        for idx, base_tr in enumerate(spawns):
            if tested >= self.max_spawns_per_tile:
                break

            tr = self._offset_transform(base_tr)

            record = {
                "index": idx,
                "base": {"x": base_tr.location.x, "y": base_tr.location.y, "z": base_tr.location.z},
                "offset": {"x": tr.location.x, "y": tr.location.y, "z": tr.location.z},
                "yaw": tr.rotation.yaw,
            }

            if not _carla_port_open(self.host, self.port):
                raise RuntimeError("CARLA died during spawn-probe")

            tested += 1

            actor = world.try_spawn_actor(bp, tr)
            if actor is None:
                record["status"] = "spawn_failed"
                fail += 1
                details.append(record)
                continue

            # Tick world to stabilize actor; avoids many “blocked spawn” false positives
            world.tick()

            loc = actor.get_location()
            record["spawned"] = {
                "x": loc.x,
                "y": loc.y,
                "z": loc.z,
            }
            record["status"] = "ok"
            success += 1
            details.append(record)

            # Clean destroy
            try:
                if actor.is_alive:
                    actor.destroy()
            except RuntimeError:
                # CARLA often already destroyed it internally → safe to ignore
                pass

        print(f"Tested {tested} → ok={success}, fail={fail}")

        return {
            "num_spawn_points": len(spawns),
            "tested": tested,
            "success": success,
            "fail": fail,
            "details": details,
        }



def stress_test_tile(world, seconds=10):
    actors = []
    try:
        amap = world.get_map()
        spawn_points = amap.get_spawn_points()

        if not spawn_points:
            return {"ok": False, "reason": "no_spawn_points"}

        bp = world.get_blueprint_library().filter("vehicle.*")[0]
        vehicle = world.spawn_actor(bp, spawn_points[0])
        actors.append(vehicle)

        vehicle.set_autopilot(True)

        t0 = time.time()
        while time.time() - t0 < seconds:
            world.tick()

        return {"ok": True}

    except Exception as e:
        return {"ok": False, "error": str(e)}

    finally:
        for a in actors:
            a.destroy()
