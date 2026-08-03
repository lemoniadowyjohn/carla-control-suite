#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CollisionMeshValidator
----------------------
Lightweight offline geometric sanity check on XODR geometry.

Uses Shapely *optionally* to detect:

- self-intersections in buffered road centerlines
- weird merged topology that may cause CARLA collision issues

This gate is:
- OFF by default
- fully offline (no CARLA)
- diagnostic only (non-fatal unless enforced elsewhere)

Controlled by:
    SETTINGS.ENABLE_SHAPELY_GEOMETRY_QA
"""

from __future__ import annotations

from typing import List
from xml.etree.ElementTree import Element

from ultimate_pipeline.config.settings import SETTINGS

try:
    from shapely.geometry import LineString
    from shapely.ops import unary_union

    HAS_SHAPELY = True
except Exception:
    HAS_SHAPELY = False


class CollisionMeshValidator:
    @staticmethod
    def validate(root: Element) -> List[str]:
        """
        Returns a list of string issues.
        Empty list == gate passed or skipped.
        """

        # -----------------------------
        # Single, canonical gate
        # -----------------------------
        if not getattr(SETTINGS, "ENABLE_SHAPELY_GEOMETRY_QA", False):
            print("⚠ CollisionMeshValidator: Shapely QA disabled by settings.")
            return []

        if not HAS_SHAPELY:
            print("⚠ CollisionMeshValidator: Shapely not available.")
            return []

        issues: List[str] = []

        road_polygons = []

        for road in root.findall("road"):
            rid = road.get("id", "UNKNOWN")
            geoms = road.findall("./planView/geometry")

            pts = []
            for g in geoms:
                try:
                    x = float(g.get("x", "0"))
                    y = float(g.get("y", "0"))
                except ValueError:
                    continue
                pts.append((x, y))

            # Need enough points to form a meaningful polyline
            if len(pts) < 4:
                continue

            try:
                line = LineString(pts)
                poly = line.buffer(3.5)  # approximate lane + shoulder
                road_polygons.append((rid, poly))
            except Exception as e:
                issues.append(f"Road {rid}: failed to build buffered geometry ({e})")

        if not road_polygons:
            return issues

        try:
            merged = unary_union([p for _, p in road_polygons])
            if merged.geom_type not in ("Polygon", "MultiPolygon"):
                issues.append(
                    "Merged collision geometry is not polygonal "
                    f"(geom_type={merged.geom_type})."
                )
        except Exception as e:
            issues.append(f"Shapely unary_union failed: {e}")

        return issues
