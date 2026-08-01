# ultimate_pipeline/domain_gap/per_tile_gap.py

from __future__ import annotations

import json
import os
from typing import Dict, List, Any

from .map_stats_xodr import XODRMapStatsExtractor
from .map_stats_osm import OSMMapStatsExtractor, OSMRoad
from .gap_analyzer import DomainGapAnalyzer, DomainGapScores


class PerTileDomainGap:
    """
    Compute domain-gap metrics per tile.

    Each tile compares:
      - synthetic tile OpenDRIVE (tile_x_y.xodr)
      - corresponding OSM-cropped ground truth (list[OSMRoad])

    Outputs:
      - per-tile JSON reports
      - one aggregated summary JSON
    """

    # --------------------------------------------------
    # Single-tile evaluation
    # --------------------------------------------------

    @staticmethod
    def compute_tile_gap(
        xodr_path: str,
        osm_tile_roads: List[OSMRoad],
        out_json: str,
    ) -> DomainGapScores:
        """
        Compute domain gap for a single tile.
        """

        if not os.path.exists(xodr_path):
            raise FileNotFoundError(f"Tile XODR not found: {xodr_path}")

        # Extract stats
        x_stats = XODRMapStatsExtractor.from_file(xodr_path)
        o_stats = OSMMapStatsExtractor.from_osm_roads(osm_tile_roads)

        scores = DomainGapAnalyzer.compare(o_stats, x_stats)

        # Persist per-tile report
        os.makedirs(os.path.dirname(out_json), exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "tile_xodr": xodr_path,
                    "num_osm_roads": len(osm_tile_roads),
                    "scores": scores.to_dict(),
                },
                f,
                indent=2,
            )

        return scores

    # --------------------------------------------------
    # Multi-tile sweep
    # --------------------------------------------------

    @staticmethod
    def compute_all_tiles(
        tiles_dir: str,
        osm_tiles: Dict[str, List[OSMRoad]],
        out_json: str,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Compute per-tile domain gaps for all available tiles.

        Parameters
        ----------
        tiles_dir:
            Directory containing tile_*.xodr files.

        osm_tiles:
            Mapping:
              { "tile_2_3": [OSMRoad, ...], ... }

        out_json:
            Path to aggregated summary JSON.

        Returns
        -------
        Dict[tile_id, result_dict]
        """

        results: Dict[str, Dict[str, Any]] = {}

        # Deterministic iteration (important for HPC)
        for tile_id in sorted(osm_tiles.keys()):
            osm_roads = osm_tiles[tile_id]
            xodr_path = os.path.join(tiles_dir, f"{tile_id}.xodr")
            out_tile_json = os.path.join(tiles_dir, f"{tile_id}_gap.json")

            try:
                scores = PerTileDomainGap.compute_tile_gap(
                    xodr_path=xodr_path,
                    osm_tile_roads=osm_roads,
                    out_json=out_tile_json,
                )

                results[tile_id] = {
                    "status": "ok",
                    "tile_xodr": xodr_path,
                    "num_osm_roads": len(osm_roads),
                    "scores": scores.to_dict(),
                }

            except Exception as e:
                # Fail-soft: one bad tile must not kill the sweep
                results[tile_id] = {
                    "status": "failed",
                    "tile_xodr": xodr_path,
                    "num_osm_roads": len(osm_roads),
                    "error": str(e),
                }

        # Persist aggregated summary
        os.makedirs(os.path.dirname(out_json), exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "tiles_dir": tiles_dir,
                    "num_tiles": len(results),
                    "results": results,
                },
                f,
                indent=2,
            )

        return results
