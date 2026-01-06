#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unified TileStreamer for CARLA tile-based streaming.

Important:
- This version is *logging-only*: it NEVER reloads maps or resets the CARLA world.
- Designed to be safe for use together with:
  - main_pipeline validation
  - LocalPerceptionRunner
  - Pygame-based interactive simulator

Features:
- Bounding-box tile lookup (from tile_metadata.json)
- Adjacency-based radius expansion (tile_adjacency.json)
- Optional FOV + distance visibility filtering
- Manual spectator jump to a specific tile for visual inspection
"""

from __future__ import annotations

import os
import json
import time
import math
from typing import Dict, Set, List, Optional

import carla

from ultimate_pipeline.config.settings import SETTINGS


def _dist_xy(a: carla.Location, b: carla.Location) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


class TileStreamer:
    """
    Unified TileStreamer that merges:
    - old bounding-box metadata streaming
    - adjacency/FOV-based visibility streaming

    All actions are "soft":
    - we compute which tiles *should* be loaded/unloaded
    - we only LOG these decisions
    - we do NOT call world.reset() or world.load_world()
    """

    def __init__(
        self,
        client: carla.Client,
        tiles_dir: Optional[str] = None,
        adjacency_json: Optional[str] = None,
        metadata_json: Optional[str] = None,
        stream_radius_tiles: Optional[int] = None,
    ):
        self.client = client
        self.world = client.get_world()
        self.client.set_timeout(SETTINGS.CARLA_TIMEOUT)

        self.tiles_dir = tiles_dir or getattr(SETTINGS, "TILES_DIR", "")

        adj_path = adjacency_json or getattr(SETTINGS, "TILE_ADJ_JSON_FULL", None)
        self.graph: Dict = self._load_json(adj_path)

        meta_path = metadata_json or getattr(SETTINGS, "TILE_METADATA_JSON_FULL", None)
        self.meta: Dict = self._load_json(meta_path)

        self.R: int = stream_radius_tiles or getattr(
            SETTINGS, "TILE_STREAM_RADIUS", 1
        )

        # Current set of tiles that we *consider* loaded
        self.loaded_tiles: Set[str] = set()
        self.required_tiles: Set[str] = set()

        print("[TileStreamer] Initialized.")
        print(f"   tiles_dir = {self.tiles_dir}")
        print(f"   graph     = {adj_path}")
        print(f"   meta      = {meta_path}")
        print(f"   radius    = {self.R}")

    # ------------------------------------------------------------------
    # JSON helper
    # ------------------------------------------------------------------
    def _load_json(self, path: Optional[str]):
        if not path:
            print("[TileStreamer] WARNING: no JSON path provided.")
            return {}
        if not os.path.exists(path):
            print(f"[TileStreamer] WARNING: missing JSON: {path}")
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[TileStreamer] Failed to load JSON {path}: {e}")
            return {}

    # ------------------------------------------------------------------
    # Old-style bounding-box detection
    # meta[tile_name]["bounds"] = [minx, miny, maxx, maxy]
    # ------------------------------------------------------------------
    def get_tile_for_location(self, loc: carla.Location) -> Optional[str]:
        """
        Returns the tile containing the given location using bounding boxes.
        """
        if not self.meta:
            return None

        x, y = loc.x, loc.y
        for tile_name, info in self.meta.items():
            bounds = info.get("bounds", None)
            if not bounds or len(bounds) != 4:
                continue

            minx, miny, maxx, maxy = bounds
            if minx <= x <= maxx and miny <= y <= maxy:
                return tile_name

        return None

    # ------------------------------------------------------------------
    # Tile center (index-based, from adjacency graph)
    # ------------------------------------------------------------------
    def _tile_center(self, tile_name: str) -> carla.Location:
        meta = self.graph.get(tile_name, {})
        idx = meta.get("index", [0, 0])
        i, j = idx
        return carla.Location(
            x=(i + 0.5) * getattr(SETTINGS, "TILE_SIZE", 100.0),
            y=(j + 0.5) * getattr(SETTINGS, "TILE_SIZE", 100.0),
            z=0.0,
        )

    # ------------------------------------------------------------------
    # FOV-based visibility
    # ------------------------------------------------------------------
    def _visible_by_fov(self, tile_name: str, ego_tf: carla.Transform) -> bool:
        """
        Returns True if tile is visible by FOV + distance.
        """
        if tile_name not in self.graph:
            return False

        tile_center = self._tile_center(tile_name)
        ego_loc = ego_tf.location

        d = _dist_xy(ego_loc, tile_center)

        unload_range = getattr(SETTINGS, "UNLOAD_RANGE_M", 400.0)
        vis_range = getattr(SETTINGS, "VIS_RANGE_M", 150.0)
        fov_deg = getattr(SETTINGS, "FOV_DEGREES", 120.0)

        # Always unload far beyond UNLOAD_RANGE_M
        if d > unload_range:
            return False

        # Always keep tiles very close within VIS_RANGE_M
        if d < vis_range:
            return True

        # FOV check
        yaw = math.radians(ego_tf.rotation.yaw)
        forward = carla.Vector3D(math.cos(yaw), math.sin(yaw), 0.0)
        to_tile = carla.Vector3D(
            tile_center.x - ego_loc.x,
            tile_center.y - ego_loc.y,
            0.0,
        )

        dot = forward.x * to_tile.x + forward.y * to_tile.y
        n1 = math.hypot(forward.x, forward.y)
        n2 = math.hypot(to_tile.x, to_tile.y)
        if n1 == 0 or n2 == 0:
            return True

        cosang = max(-1.0, min(1.0, dot / (n1 * n2)))
        ang = math.degrees(math.acos(cosang))
        return ang < (fov_deg / 2.0)

    # ------------------------------------------------------------------
    # Compute set of tiles to load
    # ------------------------------------------------------------------
    def compute_stream_set(self, ego_tf: carla.Transform) -> Set[str]:
        """
        Hybrid strategy:
        1) Use bounding-box tile lookup for center tile
        2) Expand by adjacency radius R
        3) Optionally apply FOV visibility filter
        """
        loc = ego_tf.location
        center_tile = self.get_tile_for_location(loc)

        if center_tile is None:
            print("[TileStreamer] WARNING: ego outside map bounds.")
            return set()

        if center_tile not in self.meta:
            # At least load the tile we are in
            return {center_tile}

        info = self.meta[center_tile]
        i = int(info.get("i", 0))
        j = int(info.get("j", 0))
        needed: Set[str] = set()
        for di in range(-self.R, self.R + 1):
            for dj in range(-self.R, self.R + 1):
                t = f"tile_{i + di}_{j + dj}.xodr"
                if t in self.meta:
                    needed.add(t)

        if getattr(SETTINGS, "ENABLE_FOV_FILTERING", False):
            visible = {t for t in needed if self._visible_by_fov(t, ego_tf)}
            return visible

        return needed

    # ------------------------------------------------------------------
    # "Soft" load / unload hooks (logging-only)
    # ------------------------------------------------------------------
    def _load_tile(self, tile_name: str):
        print(f"[TileStreamer] ▶ Would load tile: {tile_name}")
        # Intentionally no CARLA map loading here.

    def _unload_tile(self, tile_name: str):
        print(f"[TileStreamer] ⏭ Would unload tile: {tile_name}")
        # Intentionally no CARLA map unloading here.

    # ------------------------------------------------------------------
    # Static API for compatibility with older runners
    # ------------------------------------------------------------------
    def load_tiles(self, tiles: Optional[List[str]] = None, radius: Optional[int] = None):
        """
        Compatibility layer for callers that want a static tile set.

        Example:
            tile_streamer.load_tiles(["tile_1_1.xodr", "tile_1_2.xodr"], radius=1)
        """
        if tiles is None:
            return

        self.R = radius or self.R
        self.required_tiles = set(tiles)
        self.loaded_tiles = set(self.required_tiles)

        # Make sure meta and graph are loaded
        if not self.meta:
            meta_path = getattr(SETTINGS, "TILE_METADATA_JSON_FULL", None)
            self.meta = self._load_json(meta_path)

        if not self.graph:
            adj_path = getattr(SETTINGS, "TILE_ADJ_JSON_FULL", None)
            self.graph = self._load_json(adj_path)

        print("[TileStreamer] Static mode enabled.")
        print(f"   Required tiles: {self.required_tiles}")
        print(f"   Radius:         {self.R}")

    # ------------------------------------------------------------------
    # Main streaming step
    # ------------------------------------------------------------------
    def stream_once(self, ego_vehicle: carla.Vehicle) -> None:
        """
        Computes which tiles *should* be loaded/unloaded around ego.

        Safe:
        - Does NOT reset or reload CARLA world.
        - Only logs load/unload intentions.
        """
        if not self.meta:
            # Nothing to do if no metadata
            return

        ego_tf = ego_vehicle.get_transform()
        needed = self.compute_stream_set(ego_tf)

        to_load = needed - self.loaded_tiles
        to_unload = self.loaded_tiles - needed

        for t in sorted(to_load):
            self._load_tile(t)

        for t in sorted(to_unload):
            self._unload_tile(t)

        self.loaded_tiles = needed

    # ------------------------------------------------------------------
    # Continuous streaming loop (optional)
    # ------------------------------------------------------------------
    def run_streaming_loop(self, ego_vehicle: carla.Vehicle):
        """
        Optional standalone streaming loop.
        Normally you call stream_once() from your own tick loop.
        """
        print("[TileStreamer] Starting streaming loop. Ctrl+C to stop.")
        try:
            while True:
                if ego_vehicle.is_alive:
                    self.stream_once(ego_vehicle)
                else:
                    print("[TileStreamer] Ego destroyed → stopping.")
                    break
                time.sleep(getattr(SETTINGS, "TILE_STREAMER_UPDATE_RATE", 0.5))
        except KeyboardInterrupt:
            print("[TileStreamer] Streaming loop stopped by user.")

    # ------------------------------------------------------------------
    # Manual spectator jump for visual inspection
    # ------------------------------------------------------------------
    def jump_spectator_to_tile(self, tile_name: str, altitude: float = 250.0):
        """
        Moves spectator camera above the given tile for visual inspection.

        This is manual and not called automatically from stream_once().
        """
        try:
            spectator = self.world.get_spectator()
        except Exception:
            print("[TileStreamer] Could not access spectator camera.")
            return

        if not self.meta or tile_name not in self.meta:
            print(f"[TileStreamer] No metadata for tile {tile_name}")
            return

        info = self.meta[tile_name]

        # Support both "bounds"=[minx,miny,maxx,maxy] and "bbox" dict
        if "bounds" in info:
            minx, miny, maxx, maxy = info["bounds"]
            cx = 0.5 * (minx + maxx)
            cy = 0.5 * (miny + maxy)
        elif "bbox" in info:
            bbox = info["bbox"]
            cx = 0.5 * (bbox["min_x"] + bbox["max_x"])
            cy = 0.5 * (bbox["min_y"] + bbox["max_y"])
        else:
            print(f"[TileStreamer] Tile {tile_name} has no 'bounds' or 'bbox'")
            return

        location = carla.Location(x=cx, y=cy, z=altitude)
        rotation = carla.Rotation(pitch=-90.0)  # look straight down

        spectator.set_transform(carla.Transform(location, rotation))
        print(f"[TileStreamer] 👁 Spectator moved above {tile_name} at z={altitude}")

    # ------------------------------------------------------------------
    # Debug helper
    # ------------------------------------------------------------------
    def debug_print_state(self):
        print("[TileStreamer] State dump:")
        print(f"   loaded_tiles: {sorted(list(self.loaded_tiles))}")
        print(f"   meta tiles:   {len(self.meta)}")
        print(f"   graph tiles:  {len(self.graph)}")
