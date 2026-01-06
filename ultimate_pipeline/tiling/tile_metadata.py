#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tile Metadata Generator
Offline-only module.
MUST NOT import carla, tile_validation, or carla_tools.
-----------------------

Creates tile_metadata.json containing:

- tile filename
- tile index (i, j)
- bounding box (min_x, min_y, max_x, max_y)
- tile center (cx, cy)
- number of roads
- driving-lane counts (XML + semantic)
- drivable-in-full-map semantics (authoritative)

This metadata is used by:
- TileStreamer
- CARLA tile inspection / streaming
- Domain-gap per-tile analysis
"""

from __future__ import annotations

import os
import json
import xml.etree.ElementTree as ET
from typing import Dict, Tuple


# ==============================================================
# SETTINGS SNAPSHOT (offline-safe, reproducibility-critical)
# ==============================================================

def _settings_snapshot() -> dict:
    """
    Capture tiling-related settings for reproducibility.
    SAFE to call offline.
    """
    try:
        from ultimate_pipeline.config.settings import SETTINGS
        return {
            "TILE_BUFFER_M": getattr(SETTINGS, "TILE_BUFFER_M", None),
            "ENABLE_HIGHWAY_AWARE_TILE_BUFFER": getattr(
                SETTINGS, "ENABLE_HIGHWAY_AWARE_TILE_BUFFER", None
            ),
            "HIGHWAY_TILE_BUFFER_ALPHA": getattr(
                SETTINGS, "HIGHWAY_TILE_BUFFER_ALPHA", None
            ),
            "PRESERVE_GLOBAL_LANE_TYPES_IN_TILES": getattr(
                SETTINGS, "PRESERVE_GLOBAL_LANE_TYPES_IN_TILES", None
            ),
            "ALLOW_SUCCESSOR_OUTSIDE_TILE": getattr(
                SETTINGS, "ALLOW_SUCCESSOR_OUTSIDE_TILE", None
            ),
        }
    except Exception:
        return {}


# ==============================================================
# TILE METADATA
# ==============================================================

class TileMetadata:

    # ---------------- Geometry helpers ----------------

    @staticmethod
    def _extract_bbox_from_root(root: ET.Element) -> Tuple[float, float, float, float]:
        min_x, min_y = float("inf"), float("inf")
        max_x, max_y = float("-inf"), float("-inf")

        for geo in root.findall(".//planView/geometry"):
            try:
                x = float(geo.get("x"))
                y = float(geo.get("y"))
            except Exception:
                continue

            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)

        if min_x == float("inf"):
            return 0.0, 0.0, 0.0, 0.0

        return min_x, min_y, max_x, max_y

    # ---------------- Structural counters ----------------

    @staticmethod
    def _count_roads(root: ET.Element) -> int:
        return len(root.findall("road"))

    @staticmethod
    def _count_driving_lanes_xml(root: ET.Element) -> int:
        return len(root.findall(".//lane[@type='driving']"))

    @staticmethod
    def _count_driving_lanes_semantic(root: ET.Element) -> int:
        """
        Semantic driving lanes:
        - XML type='driving'
        - OR preserved global semantics via was_driving="true"
        """
        count = 0
        for lane in root.findall(".//lane"):
            if lane.get("type") == "driving" or lane.get("was_driving") == "true":
                count += 1
        return count

    # ---------------- Diagnostics helpers (non-gating) ----------------

    @staticmethod
    def _has_spawn_candidate(root: ET.Element, min_width: float = 2.5) -> bool:
        for lane in root.findall(".//lane"):
            if lane.get("type") != "driving" and lane.get("was_driving") != "true":
                continue
            for w in lane.findall("width"):
                try:
                    if float(w.get("a", "0")) >= min_width:
                        return True
                except Exception:
                    continue
        return False

    @staticmethod
    def _has_local_successor(root: ET.Element) -> bool:
        for lane in root.findall(".//lane"):
            if lane.find("link/successor") is not None:
                return True
        return False

    # ---------------- Tile index ----------------

    @staticmethod
    def _parse_tile_index(filename: str) -> Tuple[int, int]:
        """
        Input: 'tile_2_3.xodr'
        Output: (2, 3)
        """
        name = os.path.splitext(filename)[0]
        parts = name.split("_")
        if len(parts) >= 3:
            try:
                return int(parts[1]), int(parts[2])
            except Exception:
                pass
        return 0, 0

    # ---------------- Public API ----------------

    @staticmethod
    def load_metadata(path: str) -> Dict[str, dict]:
        """
        Loads tile_metadata.json and normalizes keys so BOTH are supported:
          - "tile_0_0.xodr"
          - "tile_0_0"
        This prevents key-mismatch bugs in STEP 10 / tools.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {}

        # Add alias keys without ".xodr" for robustness.
        # Keep original keys intact.
        for k, v in list(data.items()):
            if isinstance(k, str) and k.endswith(".xodr") and isinstance(v, dict):
                base = k[:-5]  # remove ".xodr"
                data.setdefault(base, v)

        return data


    @staticmethod
    def generate_metadata(tiles_dir: str, output_json: str) -> Dict[str, dict]:
        """
        Scan tiles directory and write tile_metadata.json.

        IMPORTANT SEMANTIC POLICY:
        - is_drivable is based on *global semantics*, not standalone routability.
        """
        if not os.path.isdir(tiles_dir):
            raise FileNotFoundError(f"Tiles directory not found: {tiles_dir}")

        metadata: Dict[str, dict] = {"_settings_snapshot": _settings_snapshot()}

        for fname in sorted(os.listdir(tiles_dir)):
            if not fname.endswith(".xodr"):
                continue

            path = os.path.join(tiles_dir, fname)
            root = ET.parse(path).getroot()

            i, j = TileMetadata._parse_tile_index(fname)
            min_x, min_y, max_x, max_y = TileMetadata._extract_bbox_from_root(root)
            cx = 0.5 * (min_x + max_x)
            cy = 0.5 * (min_y + max_y)

            num_roads = TileMetadata._count_roads(root)
            driving_xml = TileMetadata._count_driving_lanes_xml(root)
            driving_sem = TileMetadata._count_driving_lanes_semantic(root)

            is_drivable = (num_roads > 0 and driving_sem > 0)

            metadata[fname] = {
                "file": fname,
                "path": path,
                "i": i,
                "j": j,

                "bbox": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
                "bounds": [min_x, min_y, max_x, max_y],   # TileStreamer compatibility
                "center": {"x": cx, "y": cy},

                "num_roads": num_roads,
                "num_driving_lanes_xml": driving_xml,
                "num_driving_lanes_semantic": driving_sem,

                "is_drivable": is_drivable,
                "drivable_in_full_map": is_drivable,

                "spawn_candidate": TileMetadata._has_spawn_candidate(root),
                "has_local_successor": TileMetadata._has_local_successor(root),
            }

        os.makedirs(os.path.dirname(output_json) or ".", exist_ok=True)
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        print(f"🧭 Tile metadata saved → {output_json}")
        print(f"   Tiles processed: {len(metadata) - 1}")  # minus _settings_snapshot
        return metadata

    @staticmethod
    def write_from_health(
        tiles_dir: str,
        tile_health: dict,
        output_json: str,
    ) -> Dict[str, dict]:
        """
        Legacy compatibility: write tile_metadata.json from TileExtractor.tile() output.
        Also stores _settings_snapshot.
        """
        tiles_dir = os.path.abspath(tiles_dir)
        out: Dict[str, dict] = {"_settings_snapshot": _settings_snapshot()}

        for tile_id, h in tile_health.items():
            # tile_id like "tile_2_3"
            try:
                parts = tile_id.split("_")
                i = int(parts[1]) if len(parts) > 1 else 0
                j = int(parts[2]) if len(parts) > 2 else 0
            except Exception:
                i, j = 0, 0

            bounds = None
            try:
                core = h.get("bounds", {}).get("core", {})
                bounds = [core["xmin"], core["ymin"], core["xmax"], core["ymax"]]
            except Exception:
                bounds = None

            out[f"{tile_id}.xodr"] = {
                "file": f"{tile_id}.xodr",
                "path": os.path.join(tiles_dir, f"{tile_id}.xodr"),
                "i": i,
                "j": j,

                "num_roads": int(h.get("num_roads", 0)),
                "num_driving_lanes_xml": int(h.get("num_driving_lanes_xml", 0)),
                "num_driving_lanes_semantic": int(h.get("num_driving_lanes_semantic", 0)),

                "is_drivable": bool(h.get("is_drivable", False)),
                "drivable_in_full_map": bool(h.get("is_drivable", False)),

                "bounds": bounds,  # TileStreamer compatibility
            }

        os.makedirs(os.path.dirname(output_json) or ".", exist_ok=True)
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)

        print(f"🧭 Tile metadata written → {output_json}")
        return out
