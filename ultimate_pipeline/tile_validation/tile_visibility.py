#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tile visibility utilities for dynamic streaming.

Pure math module – no hard dependency on CARLA.

Responsibilities:
  * Load tile definitions (tile centers, sizes, paths)
  * Decide which tiles are visible from ego pose (x, y, yaw)
  * Provide load/unload decisions with hysteresis
  * Optional helpers to integrate with CARLA transforms
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TileInfo:
    """
    Description of a single tile.

    Attributes:
        tile_id:    Logical ID, e.g. "tile_2_3"
        path:       Absolute or relative path to tile .xodr
        center_x:   World X coordinate of tile center (meters, CARLA world frame)
        center_y:   World Y coordinate of tile center (meters, CARLA world frame)
        half_size:  Half tile size (meters), used for bounding box checks
    """
    tile_id: str
    path: str
    center_x: float
    center_y: float
    half_size: float


TileIndex = Dict[str, TileInfo]


# ---------------------------------------------------------------------------
# Loading tile definitions
# ---------------------------------------------------------------------------

def load_tile_defs(json_path: str) -> TileIndex:
    """
    Load tile definitions from a JSON file.

    Expected format (proposal):

        {
          "tiles": [
            {
              "id": "tile_0_0",
              "path": "tiles/tile_0_0.xodr",
              "center": [123.4, 567.8],
              "half_size": 600.0
            },
            ...
          ]
        }

    Args:
        json_path: path to tile_defs.json

    Returns:
        dict mapping tile_id -> TileInfo
    """
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Tile defs JSON not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    tiles_raw = data.get("tiles", [])
    index: TileIndex = {}

    for entry in tiles_raw:
        tid = entry.get("id")
        path = entry.get("path")
        center = entry.get("center", [0.0, 0.0])
        half_size = float(entry.get("half_size", 500.0))

        if not tid or not path:
            continue

        # Allow relative paths w.r.t. json file directory
        if not os.path.isabs(path):
            base_dir = os.path.dirname(json_path)
            path = os.path.abspath(os.path.join(base_dir, path))

        ti = TileInfo(
            tile_id=tid,
            path=path,
            center_x=float(center[0]),
            center_y=float(center[1]),
            half_size=half_size,
        )
        index[tid] = ti

    return index


# ---------------------------------------------------------------------------
# Core visibility logic (pure math)
# ---------------------------------------------------------------------------

def _angle_wrap(a: float) -> float:
    """Wrap angle to (-pi, pi]."""
    while a <= -math.pi:
        a += 2.0 * math.pi
    while a > math.pi:
        a -= 2.0 * math.pi
    return a


def _angle_diff(a: float, b: float) -> float:
    """Smallest signed difference between two angles."""
    return _angle_wrap(a - b)


def visible_tiles(
    ego_xy: Tuple[float, float],
    ego_yaw: float,
    tiles: TileIndex,
    max_distance: float = 600.0,
    fov_deg: float = 140.0,
    margin: float = 50.0,
    require_fov: bool = True,
) -> Set[str]:
    """
    Compute visible tiles from ego pose.

    Args:
        ego_xy:       (x, y) in world meters (CARLA map coordinates)
        ego_yaw:      heading in radians (CARLA convention: 0 = +X, CCW)
        tiles:        mapping tile_id -> TileInfo
        max_distance: max visibility distance (meters)
        fov_deg:      field of view (degrees)
        margin:       extra distance margin to avoid chattering at boundary
        require_fov:  if False, only distance is considered

    Returns:
        set of tile_ids that should be considered "visible now"
    """
    ex, ey = ego_xy
    fov_rad = math.radians(fov_deg)
    half_fov = 0.5 * fov_rad

    max_d2 = (max_distance + margin) ** 2
    visible: Set[str] = set()

    for tid, info in tiles.items():
        dx = info.center_x - ex
        dy = info.center_y - ey
        d2 = dx * dx + dy * dy
        if d2 > max_d2:
            continue

        if require_fov:
            angle_to_tile = math.atan2(dy, dx)
            diff = abs(_angle_diff(angle_to_tile, ego_yaw))
            if diff > half_fov:
                continue

        visible.add(tid)

    return visible


def update_visibility(
    ego_xy: Tuple[float, float],
    ego_yaw: float,
    tiles: TileIndex,
    currently_loaded: Iterable[str],
    max_distance: float = 600.0,
    fov_deg: float = 140.0,
    margin: float = 50.0,
    hysteresis: float = 80.0,
) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Compute which tiles to load/unload given current ego pose and already loaded tiles.

    Uses two radii:
      - inner radius  = max_distance          (for loading)
      - outer radius  = max_distance + hysteresis  (for unloading)

    This prevents tiles from being loaded/unloaded constantly while the
    ego vehicle hovers near a boundary.

    Args:
        ego_xy:           (x, y) ego position (meters)
        ego_yaw:          heading (radians)
        tiles:            tile index
        currently_loaded: iterable of tile_ids currently loaded
        max_distance:     base radius for loading
        fov_deg:          FOV angle for loading
        margin:           small distance margin for loading
        hysteresis:       extra distance required before unloading

    Returns:
        (visible_now, to_load, to_unload)

        visible_now: set of tiles that should be logically visible
        to_load:     visible tiles that are not yet loaded
        to_unload:   tiles that are loaded but are now outside (max_distance + hysteresis)
    """
    loaded_set: Set[str] = set(currently_loaded)

    # Visible using inner radius
    visible_now = visible_tiles(
        ego_xy=ego_xy,
        ego_yaw=ego_yaw,
        tiles=tiles,
        max_distance=max_distance,
        fov_deg=fov_deg,
        margin=margin,
        require_fov=True,
    )

    # For unloading, only distance, no FOV, larger radius
    ex, ey = ego_xy
    outer_radius = max_distance + hysteresis
    outer_d2 = outer_radius * outer_radius

    far_away: Set[str] = set()
    for tid in loaded_set:
        info = tiles.get(tid)
        if info is None:
            continue
        dx = info.center_x - ex
        dy = info.center_y - ey
        d2 = dx * dx + dy * dy
        if d2 > outer_d2:
            far_away.add(tid)

    to_load = visible_now - loaded_set
    to_unload = far_away

    return visible_now, to_load, to_unload


# ---------------------------------------------------------------------------
# Optional helpers: CARLA integration (lazy-import)
# ---------------------------------------------------------------------------

def ego_pose_from_carla_vehicle(vehicle) -> Tuple[Tuple[float, float], float]:
    """
    Convert a CARLA vehicle transform to (x, y, yaw) for visibility.

    Args:
        vehicle: carla.Vehicle instance

    Returns:
        ((x, y), yaw_in_radians)
    """
    transform = vehicle.get_transform()
    loc = transform.location
    rot = transform.rotation

    x = float(loc.x)
    y = float(loc.y)
    yaw_rad = math.radians(rot.yaw)

    return (x, y), yaw_rad


def debug_print_visibility(
    visible_now: Set[str],
    to_load: Set[str],
    to_unload: Set[str],
) -> None:
    """
    Small helper to print human-readable visibility decisions.
    """
    print("🔭 Tile visibility update:")
    print(f"   visible_now: {sorted(visible_now)}")
    if to_load:
        print(f"   ➕ to_load:   {sorted(to_load)}")
    if to_unload:
        print(f"   ➖ to_unload: {sorted(to_unload)}")
    if not to_load and not to_unload:
        print("   (no changes)")
