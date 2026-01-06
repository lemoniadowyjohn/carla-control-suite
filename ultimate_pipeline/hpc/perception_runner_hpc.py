#!/usr/bin/env python3

import os
import json
import math
from datetime import datetime

import carla

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.carla_tools.tile_world_runner import TileWorldRunner


class HPCPerceptionRunner:

    def __init__(self, client: carla.Client):
        self.client = client
        self.world = client.get_world()
        self.map = self.world.get_map()

        self.output_dir = os.path.join(
            SETTINGS.output_dir(),
            "perception_hpc_" + datetime.now().strftime("%H%M%S")
        )
        os.makedirs(self.output_dir, exist_ok=True)

        self.results = []

    def _spawn_ego(self):
        bp = self.world.get_blueprint_library().find("vehicle.tesla.model3")
        bp.set_attribute("role_name", "ego")
        return self.world.try_spawn_actor(bp, self.map.get_spawn_points()[0])

    def _detect_defect(self, ego):
        vel = ego.get_velocity()
        speed = 3.6 * math.sqrt(vel.x ** 2 + vel.y ** 2 + vel.z ** 2)
        loc = ego.get_location()
        tr = ego.get_transform()

        pitch = abs(tr.rotation.pitch)
        roll = abs(tr.rotation.roll)
        road_id = self.map.get_waypoint(loc).road_id
        s = self.map.get_waypoint(loc).s

        if speed < 0.1:
            return ("stuck", loc, road_id, s)
        if pitch > 20 or roll > 20:
            return ("instability", loc, road_id, s)
        return None

    def _resolve_tile_path(self, tile_id: str) -> str:
        """Resolve a tile identifier to a .xodr path.

        Accepts either:
        - an absolute/relative filesystem path
        - a bare filename (searched in the latest tiles directory)
        """
        if os.path.exists(tile_id):
            return tile_id

        # Best-effort: locate latest tiles dir created by the pipeline
        try:
            from ultimate_pipeline.utils.output_discovery import find_latest_tiles_dir

            tiles_dir = find_latest_tiles_dir(SETTINGS.BASE_OUTPUT_DIR)
        except Exception:
            tiles_dir = None

        if tiles_dir:
            cand = os.path.join(tiles_dir, tile_id)
            if not cand.endswith(".xodr"):
                cand += ".xodr"
            if os.path.exists(cand):
                return cand

        # Last resort: append .xodr and hope the caller has CWD set
        return tile_id if tile_id.endswith(".xodr") else tile_id + ".xodr"

    def run_tile(self, tile_id: str) -> None:
        runner = TileWorldRunner(self.client)
        tile_path = self._resolve_tile_path(tile_id)
        res = runner.load(tile_path)
        if not res.ok:
            raise RuntimeError(f"Failed to load tile {tile_path}: {res.reason}")

        # Refresh handles after world reload
        self.world = self.client.get_world()
        self.map = self.world.get_map()

        ego = self._spawn_ego()
        ego.set_autopilot(True)

        for _ in range(200):
            self.world.tick()
            defect = self._detect_defect(ego)
            if defect:
                kind, loc, rid, s = defect
                entry = {
                    "tile": tile_id,
                    "event": kind,
                    "x": loc.x,
                    "y": loc.y,
                    "z": loc.z,
                    "road_id": rid,
                    "s": s
                }
                self.results.append(entry)

        ego.destroy()
        runner.unload()

    def run_all_tiles(self, tile_ids):
        for t in tile_ids:
            print(f"Evaluating tile {t}…")
            self.run_tile(t)

        with open(os.path.join(self.output_dir, "defects_all_tiles.json"), "w") as f:
            json.dump(self.results, f, indent=2)

        print("HPC perception completed.")
