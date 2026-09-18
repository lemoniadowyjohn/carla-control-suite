#!/usr/bin/env python3
# ultimate_pipeline/carla_tools/tile_world_runner.py

"""TileWorldRunner

This module provides small utilities to load OpenDRIVE tiles (.xodr) into CARLA
for debugging and HPC evaluation.

It is imported by some runners (e.g., perception_runner_hpc.py), so it must
stay light and deterministic.
"""

from __future__ import annotations

import glob
import os
import random
import time
import importlib
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import carla

from ultimate_pipeline.config.settings import SETTINGS

from ultimate_pipeline.core.carla_utils import ensure_carla_ready
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world, hard_reset_world


def _lazy_carla():
    return importlib.import_module("carla")


@dataclass
class TileLoadResult:
    tile_path: str
    ok: bool
    reason: Optional[str] = None


class TileWorldRunner:
    """Small helper to load/unload a tile world on an existing client."""

    def __init__(self, client: "carla.Client", timeout: float = 60.0):
        self.client = client
        self.client.set_timeout(timeout)
        self._last_tile_path: Optional[str] = None

    @property
    def last_tile_path(self) -> Optional[str]:
        return self._last_tile_path

    def load(self, tile_path: str, *, reset_world: bool = True, sleep_sec: float = 1.0) -> TileLoadResult:
        """Load a tile from an absolute path."""
        if not os.path.exists(tile_path):
            return TileLoadResult(tile_path=tile_path, ok=False, reason="tile_not_found")

        try:
            with open(tile_path, "r", encoding="utf-8") as f:
                xodr = f.read()

            carla_mod = _lazy_carla()
            params = carla_mod.OpendriveGenerationParameters()
            params.map_layers = carla_mod.MapLayer.NONE

            # load_opendrive_world handles optional reload and readiness checks
            world = load_opendrive_world(
                self.client,
                xodr,
                params=params,
                timeout_s=180.0,
                retries=2,
                do_reload=bool(reset_world),
                fallback_enabled=getattr(SETTINGS, "CARLA_ENABLE_MAP_FALLBACK", False),
                fallback_maps=getattr(SETTINGS, "CARLA_FALLBACK_MAPS", None),
            )
            
            # Verify if fallback happened
            loaded_map = world.get_map().name
            if "Town" in loaded_map and "tile" not in tile_path.lower():
                 print(f"[WARN] TileWorldRunner: loaded map '{loaded_map}' does not appear to be requested tile '{tile_path}'")

            if sleep_sec > 0:
                time.sleep(sleep_sec)

            self._last_tile_path = tile_path
            return TileLoadResult(tile_path=tile_path, ok=True)

        except Exception as e:
            return TileLoadResult(tile_path=tile_path, ok=False, reason=str(e))

    def unload(self) -> None:
        """Best-effort reset (keeps same map, but clears transient state)."""
        try:
            hard_reset_world(self.client, timeout_s=30.0)
        except Exception:
            pass


def load_random_tile(
    tiles_dir: str,
    carla_host: str = "127.0.0.1",
    carla_port: int = 2000,
    timeout: float = 60.0,
) -> str:
    """Pick a random .xodr tile from tiles_dir and load as an OpenDRIVE world."""

    tile_paths = sorted(glob.glob(os.path.join(tiles_dir, "*.xodr")))
    if not tile_paths:
        raise RuntimeError(f"No .xodr tiles found in {tiles_dir}")

    tile_path = random.choice(tile_paths)

    carla_mod = _lazy_carla()
    client = carla_mod.Client(carla_host, carla_port)
    client.set_timeout(timeout)
    runner = TileWorldRunner(client, timeout=timeout)

    res = runner.load(tile_path)
    if not res.ok:
        raise RuntimeError(f"Failed to load tile {tile_path}: {res.reason}")

    return tile_path


def load_tiles_sequentially(
    tiles_dir: str,
    carla_host: str = "127.0.0.1",
    carla_port: int = 2000,
    timeout: float = 60.0,
    dwell_sec: float = 10.0,
) -> None:
    """Load each tile for a few seconds (manual inspection)."""

    tile_paths = sorted(glob.glob(os.path.join(tiles_dir, "*.xodr")))
    if not tile_paths:
        raise RuntimeError(f"No .xodr tiles found in {tiles_dir}")

    carla_mod = _lazy_carla()
    client = carla_mod.Client(carla_host, carla_port)
    client.set_timeout(timeout)
    runner = TileWorldRunner(client, timeout=timeout)

    for tile_path in tile_paths:
        print(f"\n🌍 Loading tile: {os.path.basename(tile_path)}")
        res = runner.load(tile_path)
        if not res.ok:
            print(f"❌ Failed: {res.reason}")
            continue
        print("👁 Inspect the tile in CARLA now.")
        time.sleep(max(0.0, float(dwell_sec)))


if __name__ == "__main__":
    from ultimate_pipeline.utils.output_discovery import find_latest_tiles_dir

    base_out = SETTINGS.BASE_OUTPUT_DIR
    tiles_dir = find_latest_tiles_dir(base_out)

    if not tiles_dir:
        raise RuntimeError(
            f"No tiles found under {base_out}. Did you run the pipeline with ENABLE_TILING=True?"
        )

    print(f"📦 Using tiles directory: {tiles_dir}")
    load_random_tile(tiles_dir)
