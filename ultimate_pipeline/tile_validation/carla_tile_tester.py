#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CARLA Tile Validation Runner (Hardened)

Validates each OpenDRIVE tile in isolation:
- CARLA load (with restart safety)
- Waypoint generation
- Vehicle spawn sanity
- Lane seam continuity against neighbors

Each tile is tested with a CLEAN CARLA state to prevent
cross-tile simulator corruption.
"""

from __future__ import annotations

import os
import json
import time
from typing import Dict, List

import carla
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.carla_utils import (
    autostart_carla_if_needed,
    restart_carla,
)

from ultimate_pipeline.tile_validation.lane_seam_checker import LaneSeamChecker


# =========================================================
#  Tile Tester
# =========================================================

class CarlaTileTester:
    """
    ENTRY POINT for CARLA tile-level validation.
    """

    def __init__(self):
        # Do NOT create CARLA client here
        # CARLA lifecycle is controlled per-tile
        self.client = None

    # -----------------------------------------------------
    #  Tile Load (isolated)
    # -----------------------------------------------------

    def _load_tile_world(self, tile_path: str) -> carla.World:
        print(f"🌍 Loading tile: {tile_path}")

        with open(tile_path, "r", encoding="utf-8") as f:
            xodr_data = f.read()

        params = carla.OpendriveGenerationParameters()
        params.map_layers = carla.MapLayer.NONE
        params.enable_mesh_visibility = False
        world = load_opendrive_world(
            self.client,
            xodr_data,
            params=params,
            timeout_s=180.0,
            retries=2,
            do_reload=True,
        )
        # Ensure CARLA really produced a usable world
        _ = world.get_map()

        print("   → Map loaded.")
        return world

    # -----------------------------------------------------
    #  Waypoint Test
    # -----------------------------------------------------

    @staticmethod
    def _test_waypoints(world: carla.World) -> int:
        try:
            amap = world.get_map()
            wps = amap.generate_waypoints(2.0)
            count = len(wps)
            print(f"   → Waypoints generated: {count}")
            return count
        except Exception as e:
            print(f"⚠ Waypoint generation failed: {e}")
            return 0

    # -----------------------------------------------------
    #  Spawn Test
    # -----------------------------------------------------

    @staticmethod
    def _test_spawn(world: carla.World) -> bool:
        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            print("⚠ No spawn points found.")
            return False

        bp_lib = world.get_blueprint_library()
        bps = bp_lib.filter("vehicle.*")
        if not bps:
            print("⚠ No vehicle blueprints.")
            return False

        bp = bps[0]
        sp = spawn_points[0]

        actor = world.try_spawn_actor(bp, sp)
        if actor:
            actor.destroy()
            print("   → Vehicle spawn: OK")
            return True

        print("⚠ Direct spawn failed.")
        return False

    # -----------------------------------------------------
    #  Seam Check (offline, safe)
    # -----------------------------------------------------

    @staticmethod
    def _check_seams(tile_path: str, neighbors: List[str]) -> Dict:
        seam_results = {}

        for nb in neighbors:
            print(f"🔍 Seam check: {os.path.basename(tile_path)} ↔ {os.path.basename(nb)}")

            seam = LaneSeamChecker.analyze(
                tile_a=tile_path,
                tile_b=nb,
                border_tol=5.0,
                dist_thresh=2.0,
                hdg_thresh=0.3,
            )

            seam_results[os.path.basename(nb)] = {
                "max_lateral_offset": seam.max_lateral_offset,
                "max_heading_error": seam.max_heading_error,
                "max_elevation_jump": seam.max_elevation_jump,
                "warnings": seam.warnings,
            }

        return seam_results

    # -----------------------------------------------------
    #  SINGLE TILE TEST (authoritative)
    # -----------------------------------------------------

    def _test_single_tile(self, tile_path: str, neighbors: List[str]) -> Dict:
        result = {
            "tile": os.path.basename(tile_path),
            "status": "unknown",
        }

        try:
            # 🔑 SINGLE authority entry
            self.client = autostart_carla_if_needed()

            world = self._load_tile_world(tile_path)

            wps = self._test_waypoints(world)
            spawn_ok = self._test_spawn(world)

            result.update({
                "waypoints": wps,
                "spawn_success": spawn_ok,
                "status": "load_ok" if wps > 0 else "no_waypoints",
            })

            # Seam checks are offline → safe
            result["seams"] = self._check_seams(tile_path, neighbors)

            return result

        except RuntimeError as e:
            print(f"💥 CARLA crash on tile: {e}")
            result["status"] = "carla_crash"
            result["error"] = str(e)
            return result

        finally:
            # 🚨 HARD RESET BETWEEN TILES (non-negotiable)
            try:
                restart_carla()
                time.sleep(2.0)
            except Exception:
                pass

    # -----------------------------------------------------
    #  BATCH ENTRY POINT
    # -----------------------------------------------------

    def validate_tiles(self, tiles_dir: str, adjacency_json: str, out_json: str):
        print(f"📌 Validating tiles in {tiles_dir}")

        with open(adjacency_json, "r", encoding="utf-8") as f:
            adjacency = json.load(f)

        results = {}

        for tile_name, neighbors in adjacency.items():
            tile_path = os.path.join(tiles_dir, tile_name + ".xodr")
            nb_paths = [os.path.join(tiles_dir, n + ".xodr") for n in neighbors]

            # Robustness: skip missing tiles / neighbors
            if not os.path.exists(tile_path):
                print(f"⚠ Missing tile file: {tile_path}")
                results[tile_name] = {"tile": os.path.basename(tile_path), "status": "missing_tile"}
                continue

            nb_paths = [p for p in nb_paths if os.path.exists(p)]

            print("\n==============================")
            print(f"🧪 TILE: {tile_name}")
            print("==============================")

            res = self._test_single_tile(tile_path, nb_paths)
            results[tile_name] = res

        os.makedirs(os.path.dirname(out_json), exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        print("\n📘 Tile validation complete.")
        print(f"Saved results → {out_json}")


# =========================================================
#  CLI
# =========================================================

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", required=True)
    ap.add_argument("--adjacency", required=True)
    ap.add_argument("--out", required=True)

    args = ap.parse_args()

    tester = CarlaTileTester()
    tester.validate_tiles(
        tiles_dir=args.tiles,
        adjacency_json=args.adjacency,
        out_json=args.out,
    )