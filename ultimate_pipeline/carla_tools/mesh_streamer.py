#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MeshStreamer

Optional visual streaming using CARLA's map layers / sublevels.

Assumes each tile has a corresponding map layer name, e.g.:
    "tile_0_0.xodr" → "Tile_0_0"

If your UE4 map uses different layer names, adapt `_layer_name_for_tile`.
"""

from __future__ import annotations
from typing import Optional, Set

try:  # pragma: no cover
    import carla  # type: ignore
    _CARLA_AVAILABLE = True
except Exception:  # pragma: no cover
    carla = None  # type: ignore
    _CARLA_AVAILABLE = False
from ultimate_pipeline.config.settings import SETTINGS


class MeshStreamer:
    def __init__(self, world: carla.World):
        if not _CARLA_AVAILABLE:
            raise RuntimeError(
                "CARLA PythonAPI not found on PYTHONPATH. "
                "Install/activate CARLA PythonAPI before using MeshStreamer."
            )
        self.world = world
        self.loaded_layers: Set[str] = set()
        self.enabled = getattr(SETTINGS, "ENABLE_MESH_STREAMING", False)

        if not self.enabled:
            print("[MeshStreamer] Disabled via settings.")
        else:
            print("[MeshStreamer] Enabled.")

    # ---------------------------------------------------------
    # Name mapping: tile file → UE4 map layer
    # ---------------------------------------------------------
    @staticmethod
    def _layer_name_for_tile(tile_name: str) -> str:
        """
        Map "tile_0_1.xodr" → "Tile_0_1" by default.
        Adjust this method to match your actual sublevel names.
        """
        base = tile_name
        if base.lower().endswith(".xodr"):
            base = base[:-5]
        return base.replace("tile_", "Tile_")

    # ---------------------------------------------------------
    # Core methods
    # ---------------------------------------------------------
    def load_layer(self, tile_name: str):
        if not self.enabled:
            return

        layer_name = self._layer_name_for_tile(tile_name)
        if layer_name in self.loaded_layers:
            return

        try:
            self.world.load_map_layer(layer_name)
            self.loaded_layers.add(layer_name)
            print(f"[MeshStreamer] Loaded layer: {layer_name}")
        except RuntimeError as e:
            print(f"[MeshStreamer] FAILED to load layer {layer_name}: {e}")

    def unload_layer(self, tile_name: str):
        if not self.enabled:
            return

        layer_name = self._layer_name_for_tile(tile_name)
        if layer_name not in self.loaded_layers:
            return

        try:
            self.world.unload_map_layer(layer_name)
            self.loaded_layers.remove(layer_name)
            print(f"[MeshStreamer] Unloaded layer: {layer_name}")
        except RuntimeError as e:
            print(f"[MeshStreamer] FAILED to unload layer {layer_name}: {e}")

    def update_layers(self, required_tiles: Set[str]):
        if not self.enabled:
            return

        # Which layers should be active?
        required_layers = {self._layer_name_for_tile(t) for t in required_tiles}
        to_load = required_layers - self.loaded_layers
        to_unload = self.loaded_layers - required_layers

        for lname in sorted(to_load):
            try:
                self.world.load_map_layer(lname)
                self.loaded_layers.add(lname)
                print(f"[MeshStreamer] Loaded layer: {lname}")
            except RuntimeError as e:
                print(f"[MeshStreamer] FAILED to load layer {lname}: {e}")

        for lname in sorted(to_unload):
            try:
                self.world.unload_map_layer(lname)
                self.loaded_layers.remove(lname)
                print(f"[MeshStreamer] Unloaded layer: {lname}")
            except RuntimeError as e:
                print(f"[MeshStreamer] FAILED to unload layer {lname}: {e}")

    def update(self, required_tiles: Optional[Set[str]] = None):
        """
        Per-tick entry point (mirrors TileStreamer.stream_once / ActorStreamManager.update).

        `required_tiles` is the set of tile filenames (e.g. "tile_0_0.xodr")
        that should currently be streamed in, typically the sibling
        TileStreamer's `loaded_tiles` for the current ego position. Delegates
        to `update_layers`, which already does the load/unload diffing.
        """
        self.update_layers(required_tiles or set())
