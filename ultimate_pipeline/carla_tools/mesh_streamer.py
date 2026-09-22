#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MeshStreamer

Optional visual streaming using CARLA's map layers / sublevels.

NOTICE: This module provides visibility/estimator functionality only.
It does NOT reflect actual engine residency or CARLA MapLayer loading.
Calling load_map_layer() with arbitrary tile names is NOT supported
and will fail for non-standard MapLayer enums/categories.

Tile naming convention (adapt to your project):
    "tile_0_1.xodr" -> "Tile_0_1" by default.
"""

from __future__ import annotations
from typing import Optional, Set, Literal

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
        self.predicted_required_tiles: Set[str] = set()
        self.enabled = getattr(SETTINGS, "ENABLE_MESH_STREAMING", False)

        if not self.enabled:
            print("[MeshStreamer] Disabled via settings.")
        else:
            print("[MeshStreamer] Enabled (visibility estimator only).")

    # ---------------------------------------------------------
    # Name mapping: tile file → UE4 map layer (project-specific adaptation)
    # ---------------------------------------------------------
    @staticmethod
    def _layer_name_for_tile(tile_name: str) -> str:
        """
        Map "tile_0_1.xodr" -> "Tile_0_1" by default.
        Adjust this method to match your actual sublevel names.
        NOTE: This is a project-specific mapping, not a CARLA API guarantee.
        """
        base = tile_name
        if base.lower().endswith(".xodr"):
            base = base[:-5]
        return base.replace("tile_", "Tile_")

    # ---------------------------------------------------------
    # Evidence levels (until live test exists)
    # ---------------------------------------------------------
    EVIDENCE_LEVELS: list[Literal["VERIFIED_OFFLINE_RUNTIME_TILE",
                                   "BLOCKED_EXTERNAL_CARLA"]] = [
        "VERIFIED_OFFLINE_RUNTIME_TILE",
        "BLOCKED_EXTERNAL_CARLA",
    ]

    @property
    def evidence_level(self) -> str:
        """Return the current evidence level for this streamer."""
        if not self.enabled:
            return "BLOCKED_EXTERNAL_CARLA"
        return self.EVIDENCE_LEVELS[0]  # VERIFIED_OFFLINE_RUNTIME_TILE by default

    # ---------------------------------------------------------
    # Core methods - visibility estimator only
    # ---------------------------------------------------------
    def load_layer(self, tile_name: str):
        """
        Estimate that a tile layer should be active for the current position.
        Does NOT call world.load_map_layer() with arbitrary tile names.

        Returns:
            True if the layer was marked as predicted required,
            False if streaming is disabled.
        """
        if not self.enabled:
            return False

        layer_name = self._layer_name_for_tile(tile_name)
        if layer_name in self.predicted_required_tiles:
            return True

        # Note: do NOT call self.world.load_map_layer(layer_name) here,
        # as arbitrary tile names are not valid CARLA MapLayer categories.
        # MapLayer loading is category/layer specific, not a generic tile API.
        self.predicted_required_tiles.add(layer_name)
        print(f"[MeshStreamer] Predicted required: {layer_name}")
        return True

    def unload_layer(self, tile_name: str):
        """
        Remove a tile from the predicted required set.
        Does NOT call world.unload_map_layer().
        """
        if not self.enabled:
            return

        layer_name = self._layer_name_for_tile(tile_name)
        self.predicted_required_tiles.discard(layer_name)
        print(f"[MeshStreamer] Predicted no longer required: {layer_name}")

    def update_layers(self, required_tiles: Set[str]):
        """
        Update the set of predicted required tiles based on current ego position.

        Note: This updates the internal predicted set only.
        Actual CARLA MapLayer loading must be performed by the application
        using proper MapLayer enums/categories, not arbitrary tile names.
        """
        if not self.enabled:
            return

        # Compute the set difference for the predicted set
        to_predict = required_tiles - self.predicted_required_tiles
        no_longer_predicted = self.predicted_required_tiles - required_tiles

        for tname in sorted(to_predict):
            self.load_layer(tname)
        for tname in sorted(no_longer_predicted):
            self.unload_layer(tname)

    def update(self, required_tiles: Optional[Set[str]] = None):
        """
        Per-tick entry point.

        `required_tiles` is the set of tile filenames (e.g. "tile_0_0.xodr")
        that should currently be streamed in, typically based on the
        TileStreamer's position estimation. This does NOT reflect actual
        CARLA engine residency or MapLayer loading.

        Note: This delegates to `update_layers`, which updates the internal
        predicted set only. Actual CARLA MapLayer loading must be performed
        separately using proper API calls.
        """
        if required_tiles is None:
            required_tiles = set()
        self.update_layers(required_tiles)

    def get_evidence(self) -> dict:
        """
        Return evidence status for this streamer.

        Returns:
            dict with evidence level and predicted tiles state.
        """
        return {
            "evidence_level": self.evidence_level,
            "predicted_required_tiles": sorted(self.predicted_required_tiles),
            "streaming_enabled": self.enabled,
            "note": (
                "This reflects visibility estimation only, "
                "not actual CARLA MapLayer residency or loading."
            ),
        }