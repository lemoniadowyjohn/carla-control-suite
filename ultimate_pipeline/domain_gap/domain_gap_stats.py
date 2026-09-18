#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
domain_gap_stats.py

Purpose
-------
Compute descriptive statistical domain-gap characteristics between:
    - synthetic CARLA-generated maps (tiles)
    - manual reference map
    - auxiliary artifacts (IoU logs, elevation stats)

This module is intentionally:
    - offline (no CARLA dependency)
    - descriptive (no optimization)
    - reproducible
    - complementary to run_full_domain_gap.py

It characterizes distributions that influence learning and generalization,
not absolute error metrics.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Any, List

import numpy as np
from shapely.geometry import Polygon

from ultimate_pipeline.domain_gap.curvature_gap import CurvatureGap

IOU_REJECTION_THRESHOLD = 0.2


# =============================================================================
# Domain Gap Statistics
# =============================================================================

class DomainGapStats:
    """
    Compute distributional statistics over synthetic vs manual maps.

    base_dir must point to:
        <pipeline_out>/domain_gap/
    """

    def __init__(self, base_dir: str):
        self.base = base_dir

        self.tiles_json = os.path.join(base_dir, "tiles.json")
        self.metadata_json = os.path.join(base_dir, "map_metadata.json")
        self.elev_json = os.path.join(base_dir, "elevation_stats.json")
        self.seam_json = os.path.join(base_dir, "seam_metrics.json")
        self.manual_xodr = os.path.join(base_dir, "reference_map.xodr")

        self.stats: Dict[str, Any] = {}

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """
        Execute full descriptive domain-gap analysis.
        """

        self.stats["curvature"] = self._curvature_stats()
        self.stats["lane_widths"] = self._lane_width_stats()
        self.stats["road_types"] = self._road_type_frequency()
        self.stats["elevation"] = self._elevation_distribution()
        self.stats["junctions"] = self._junction_complexity()
        self.stats["traffic_lights"] = self._traffic_light_density()
        self.stats["buildings"] = self._building_density()
        self.stats["structural_similarity"] = self._map_similarity()
        self.stats["geometry_qc"] = self._geometry_qc_stats()
        self.stats["tile_iou"] = self._tile_iou_stats()

        # provenance
        self.stats["_meta"] = {
            "source_dir": self.base,
            "iou_rejection_threshold": IOU_REJECTION_THRESHOLD,
            "note": "Descriptive statistics only; not used for optimization",
        }

        out = os.path.join(self.base, "domain_gap_stats.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, indent=2)

        print(f"✓ domain_gap_stats.json written → {out}")
        return self.stats

    # -------------------------------------------------------------------------
    # Curvature (consistent with CurvatureGap)
    # -------------------------------------------------------------------------

    def _curvature_stats(self) -> Dict[str, float]:
        """
        Curvature distribution for synthetic tiles vs manual reference.
        Uses the same definition as CurvatureGap to avoid metric drift.
        """

        synthetic_vals: List[float] = []

        if os.path.exists(self.tiles_json):
            with open(self.tiles_json, "r") as f:
                tj = json.load(f)

            assert isinstance(tj.get("tiles", []), list), "tiles.json malformed"

            for tile in tj.get("tiles", []):
                try:
                    res = CurvatureGap.compute(tile, tile)
                    if res.get("mean_manual") is not None:
                        synthetic_vals.append(res["mean_manual"])
                except Exception:
                    continue

        manual_val = 0.0
        if os.path.exists(self.manual_xodr):
            try:
                res = CurvatureGap.compute(self.manual_xodr, self.manual_xodr)
                manual_val = res.get("mean_manual") or 0.0
            except Exception:
                manual_val = 0.0

        return {
            "synthetic_mean": float(np.mean(synthetic_vals)) if synthetic_vals else 0.0,
            "synthetic_std": float(np.std(synthetic_vals)) if synthetic_vals else 0.0,
            "manual": float(manual_val),
        }

    # -------------------------------------------------------------------------
    # Lane width distribution (approximate, documented)
    # -------------------------------------------------------------------------

    def _lane_width_stats(self) -> Dict[str, float]:
        """
        Lane width statistics for synthetic tiles.

        Width is approximated at mid-lane:
            w ≈ a + 0.5*b
        """

        if not os.path.exists(self.tiles_json):
            return {"mean": 0.0, "std": 0.0}

        with open(self.tiles_json, "r") as f:
            tj = json.load(f)

        widths: List[float] = []

        for tile in tj.get("tiles", []):
            widths.extend(self._extract_lane_widths(tile))

        if not widths:
            return {"mean": 0.0, "std": 0.0}

        arr = np.array(widths, dtype=float)

        return {
            "mean": float(arr.mean()),
            "std": float(arr.std()),
            "min": float(arr.min()),
            "max": float(arr.max()),
            "note": "Width approximated at s≈0.5",
        }

    @staticmethod
    def _extract_lane_widths(xodr_path: str) -> List[float]:
        if not os.path.exists(xodr_path):
            return []

        vals: List[float] = []

        with open(xodr_path, "r", encoding="utf-8") as f:
            for line in f:
                if "<width" in line:
                    try:
                        a = float(line.split('a="')[1].split('"')[0])
                        b = float(line.split('b="')[1].split('"')[0]) if 'b="' in line else 0.0
                        vals.append(a + 0.5 * b)
                    except Exception:
                        continue
        return vals

    # -------------------------------------------------------------------------
    # Road type frequency
    # -------------------------------------------------------------------------

    def _road_type_frequency(self) -> Dict[str, int]:
        if not os.path.exists(self.tiles_json):
            return {}

        with open(self.tiles_json, "r") as f:
            tj = json.load(f)

        freq: Dict[str, int] = {}

        for tile in tj.get("tiles", []):
            with open(tile, "r", encoding="utf-8") as f:
                for line in f:
                    if "<type" in line and 'type="' in line:
                        t = line.split('type="')[1].split('"')[0]
                        freq[t] = freq.get(t, 0) + 1

        return freq

    # -------------------------------------------------------------------------
    # Elevation distribution
    # -------------------------------------------------------------------------

    def _elevation_distribution(self) -> Dict[str, float]:
        if not os.path.exists(self.elev_json):
            return {}

        with open(self.elev_json, "r") as f:
            data = json.load(f)

        vals: List[float] = []
        for _, v in data.items():
            vals.extend(v)

        if not vals:
            return {}

        arr = np.array(vals, dtype=float)

        return {
            "mean": float(arr.mean()),
            "std": float(arr.std()),
            "min": float(arr.min()),
            "max": float(arr.max()),
        }

    # -------------------------------------------------------------------------
    # Junction complexity
    # -------------------------------------------------------------------------

    def _junction_complexity(self) -> Dict[str, int]:
        if not os.path.exists(self.tiles_json):
            return {}

        with open(self.tiles_json, "r") as f:
            tj = json.load(f)

        junctions = 0
        connections = 0

        for tile in tj.get("tiles", []):
            with open(tile, "r", encoding="utf-8") as f:
                for line in f:
                    if "<junction" in line:
                        junctions += 1
                    if "<connection" in line:
                        connections += 1

        return {
            "junction_count": junctions,
            "connections": connections,
        }

    # -------------------------------------------------------------------------
    # Traffic light density
    # -------------------------------------------------------------------------

    def _traffic_light_density(self) -> Dict[str, int]:
        if not os.path.exists(self.tiles_json):
            return {}

        with open(self.tiles_json, "r") as f:
            tj = json.load(f)

        count = 0
        for tile in tj.get("tiles", []):
            with open(tile, "r", encoding="utf-8") as f:
                for line in f:
                    if "<controller" in line and "signal" in line:
                        count += 1

        return {"count": count}

    # -------------------------------------------------------------------------
    # Building density (semantic clarification)
    # -------------------------------------------------------------------------

    def _building_density(self) -> Dict[str, Any]:
        """
        Reports total OSM building area once.
        Manual vs synthetic are identical by construction.
        """

        if not os.path.exists(self.metadata_json):
            return {"available": False}

        with open(self.metadata_json, "r") as f:
            meta = json.load(f)

        bld_path = meta.get("buildings")
        if not bld_path or not os.path.exists(bld_path):
            return {"available": False}

        try:
            import geojson
            with open(bld_path, "r") as f:
                gj = geojson.load(f)

            polys = [
                Polygon(feat["geometry"]["coordinates"][0])
                for feat in gj["features"]
                if feat["geometry"]["type"] == "Polygon"
            ]

            area = float(sum(p.area for p in polys))

            return {
                "available": True,
                "total_building_area": area,
                "note": "OSM-based buildings identical for manual and synthetic maps",
            }

        except Exception:
            return {"available": False}

    # -------------------------------------------------------------------------
    # Structural similarity summary
    # -------------------------------------------------------------------------

    def _map_similarity(self) -> Dict[str, float]:
        curv = self.stats.get("curvature") or self._curvature_stats()

        diff = abs(curv.get("synthetic_mean", 0.0) - curv.get("manual", 0.0))

        road_freq = self._road_type_frequency()
        total = sum(road_freq.values()) + 1e-9

        entropy = -sum(
            (v / total) * np.log(v / total + 1e-9)
            for v in road_freq.values()
        )

        return {
            "curvature_difference": float(diff),
            "road_type_entropy": float(entropy),
        }

    # -------------------------------------------------------------------------
    # Geometry QC (heuristic only)
    # -------------------------------------------------------------------------

    def _geometry_qc_stats(self) -> Dict[str, Any]:
        """
        Heuristic geometry sanity indicators.
        Polygons are non-physical; results must not be over-interpreted.
        """

        if not os.path.exists(self.tiles_json):
            return {"enabled": False}

        with open(self.tiles_json, "r") as f:
            tj = json.load(f)

        total = 0
        invalid = 0
        areas: List[float] = []

        for tile in tj.get("tiles", []):
            try:
                coords = []
                with open(tile, "r", encoding="utf-8") as f:
                    for line in f:
                        if "<geometry" in line and "x=" in line and "y=" in line:
                            x = float(line.split("x=")[1].split('"')[1])
                            y = float(line.split("y=")[1].split('"')[1])
                            coords.append((x, y))

                if len(coords) >= 3:
                    poly = Polygon(coords)
                    total += 1
                    if not poly.is_valid:
                        invalid += 1
                    else:
                        areas.append(poly.area)

            except Exception:
                continue

        return {
            "enabled": True,
            "total_polygons": total,
            "invalid_polygons": invalid,
            "invalid_ratio": float(invalid / (total + 1e-9)),
            "area_mean": float(np.mean(areas)) if areas else 0.0,
            "area_std": float(np.std(areas)) if areas else 0.0,
            "interpretation": "heuristic_only",
        }

    # -------------------------------------------------------------------------
    # Tile IoU statistics (logged only)
    # -------------------------------------------------------------------------

    def _tile_iou_stats(self) -> Dict[str, Any]:
        iou_vals = os.path.join(self.base, "iou_values.npy")
        iou_hist = os.path.join(self.base, "iou_histogram.png")

        if not os.path.exists(iou_vals):
            return {
                "enabled": False,
                "note": "IoU not computed or stored in this run",
            }

        try:
            vals = np.load(iou_vals)
            rejected = int((vals < IOU_REJECTION_THRESHOLD).sum())

            return {
                "enabled": True,
                "mean": float(vals.mean()),
                "std": float(vals.std()),
                "min": float(vals.min()),
                "rejection_threshold": IOU_REJECTION_THRESHOLD,
                "tiles_below_threshold": rejected,
                "rejection_ratio": float(rejected / (len(vals) + 1e-9)),
                "histogram_path": iou_hist if os.path.exists(iou_hist) else None,
            }

        except Exception:
            return {"enabled": False}
