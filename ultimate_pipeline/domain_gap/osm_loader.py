# ultimate_pipeline/domain_gap/osm_loader.py

from __future__ import annotations

import json
from typing import List, Tuple, Any

from ultimate_pipeline.domain_gap.map_stats_osm import OSMRoad

XY = Tuple[float, float]


class OSMLoader:
    """
    Lightweight OSM road loader for domain-gap analysis.

    Input format (JSON):
    [
      {
        "polyline": [[x1, y1], [x2, y2], ...],
        "highway": "residential",
        "lanes": 2,
        "maxspeed": 50
      },
      ...
    ]

    Notes:
      - Geometry is assumed to be projected (meters), not lat/lon.
      - This loader is deterministic and CARLA-independent.
      - Designed to be replaced by a real .osm/.pbf parser later.
    """

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------

    @staticmethod
    def load_from_json(path: str) -> List[OSMRoad]:
        """
        Load OSM roads from a JSON file.

        Invalid entries are skipped (with best-effort parsing).
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("OSM JSON must be a list of road objects")

        roads: List[OSMRoad] = []

        for idx, item in enumerate(data):
            try:
                road = OSMLoader._parse_road(item)
                if road is not None:
                    roads.append(road)
            except Exception as e:
                # Fail-soft: skip broken entries
                print(f"[OSMLoader] ⚠ Skipping road #{idx}: {e}")

        return roads

    # --------------------------------------------------
    # Internal helpers
    # --------------------------------------------------

    @staticmethod
    def _parse_road(item: Any) -> OSMRoad | None:
        """
        Parse and validate a single road entry.
        """

        if not isinstance(item, dict):
            return None

        poly_raw = item.get("polyline")
        if not isinstance(poly_raw, list) or len(poly_raw) < 2:
            return None

        poly: List[XY] = []
        for p in poly_raw:
            if (
                isinstance(p, (list, tuple))
                and len(p) == 2
                and OSMLoader._is_number(p[0])
                and OSMLoader._is_number(p[1])
            ):
                poly.append((float(p[0]), float(p[1])))

        if len(poly) < 2:
            return None

        highway = str(item.get("highway", "") or "")
        lanes = OSMLoader._safe_int(item.get("lanes"))
        maxspeed = OSMLoader._safe_float(item.get("maxspeed"))
        # turn:lanes uses a colon which is not a valid Python identifier; read via dict key
        turn_lanes_raw = item.get("turn:lanes") or item.get("turn_lanes")
        turn_lanes = str(turn_lanes_raw).strip() if turn_lanes_raw else None

        traffic_sign_raw = item.get("traffic_sign")
        traffic_sign = str(traffic_sign_raw).strip().lower() if traffic_sign_raw else None

        return OSMRoad(
            polyline=poly,
            highway=highway,
            lanes=lanes,
            maxspeed=maxspeed,
            turn_lanes=turn_lanes,
            traffic_sign=traffic_sign,
        )

    @staticmethod
    def _safe_int(val: Any) -> int | None:
        try:
            return int(val)
        except Exception:
            return None

    @staticmethod
    def _safe_float(val: Any) -> float | None:
        try:
            return float(val)
        except Exception:
            return None

    @staticmethod
    def _is_number(val: Any) -> bool:
        return isinstance(val, (int, float))
