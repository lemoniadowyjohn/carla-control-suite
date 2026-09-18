"""CARLA import preflight checks for 's' coordinates.

CARLA's OpenDRIVE importer is fragile and will crash the UE process for certain
schema-valid but CARLA-invalid patterns. One common crash signature is an
assertion like: `s >= 0.0`.

This gate is intentionally conservative and focuses on invariants that are
required (or strongly expected) by CARLA:

1) For every road, all planView geometry entries must have s >= 0.
2) The first planView geometry must start at s == 0 (within tolerance).
3) planView geometry s must be non-decreasing.
4) elevationProfile, superelevation, laneOffset entries must have s >= 0.
5) road length must be >= max(geometry.s + geometry.length).

The checker can run in "validate-only" mode (default) or "auto_fix" mode.
Auto-fix is safe for a *QA-only* copy (e.g., tiles), where the goal is to keep
CARLA from crashing rather than preserve exact OSM provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import xml.etree.ElementTree as ET


@dataclass
class CarlaImportSIssue:
    road_id: str
    element: str
    attribute: str
    value: float
    message: str


class CarlaImportSChecker:
    TOL = 1e-6

    @staticmethod
    def _f(x: str, default: float = 0.0) -> float:
        try:
            return float(x)
        except Exception:
            return default

    @staticmethod
    def validate(root: ET.Element) -> List[Dict]:
        issues: List[CarlaImportSIssue] = []

        for road in root.findall("road"):
            rid = road.get("id", "?")

            # ---- planView geometries ----
            geoms = road.findall("./planView/geometry")
            s_prev = -1e9
            for i, g in enumerate(geoms):
                s = CarlaImportSChecker._f(g.get("s", "0"))
                if s < -CarlaImportSChecker.TOL:
                    issues.append(CarlaImportSIssue(rid, "planView/geometry", "s", s, "negative geometry s"))
                if i == 0 and abs(s) > 1e-3:
                    issues.append(CarlaImportSIssue(rid, "planView/geometry", "s", s, "first geometry s should be 0"))
                if s + CarlaImportSChecker.TOL < s_prev:
                    issues.append(CarlaImportSIssue(rid, "planView/geometry", "s", s, "geometry s is decreasing"))
                s_prev = s

            # ---- elevation / superelevation / laneOffset ----
            for path, attr in [
                ("./elevationProfile/elevation", "s"),
                ("./lateralProfile/superelevation", "s"),
                ("./lanes/laneOffset", "s"),
            ]:
                for el in road.findall(path):
                    s = CarlaImportSChecker._f(el.get(attr, "0"))
                    if s < -CarlaImportSChecker.TOL:
                        issues.append(CarlaImportSIssue(rid, path, attr, s, f"negative {attr} in {path}"))

            # ---- road length sanity vs geometry span ----
            road_len = CarlaImportSChecker._f(road.get("length", "0"))
            max_end = 0.0
            for g in geoms:
                s = CarlaImportSChecker._f(g.get("s", "0"))
                gl = CarlaImportSChecker._f(g.get("length", "0"))
                max_end = max(max_end, s + gl)
            if max_end > 0 and road_len + 1e-3 < max_end:
                issues.append(
                    CarlaImportSIssue(rid, "road", "length", road_len, f"road.length={road_len:.3f} < max geometry end {max_end:.3f}")
                )

        # serialize to JSON-friendly dicts
        return [
            {
                "road_id": x.road_id,
                "element": x.element,
                "attribute": x.attribute,
                "value": x.value,
                "message": x.message,
            }
            for x in issues
        ]

    @staticmethod
    def auto_fix_in_place(root: ET.Element) -> Tuple[int, List[Dict]]:
        """Attempt safe fixes for CARLA-crash patterns.

        Fixes applied:
        - For each road: if first planView geometry has s != 0, shift all geometry s so first is 0.
        - Clamp any negative s (geometry/elevation/superelevation/laneOffset) to 0.
        - Ensure road.length >= max(geometry.s + geometry.length).

        Returns (num_fixes, issues_after).
        """

        fixes = 0
        for road in root.findall("road"):
            geoms = road.findall("./planView/geometry")
            if geoms:
                first_s = CarlaImportSChecker._f(geoms[0].get("s", "0"))
                if abs(first_s) > 1e-3:
                    # shift all geometry s so the first becomes 0
                    for g in geoms:
                        s = CarlaImportSChecker._f(g.get("s", "0"))
                        g.set("s", f"{s - first_s:.6f}")
                    fixes += 1

            # clamp negative s-like values
            for path, attr in [
                ("./planView/geometry", "s"),
                ("./elevationProfile/elevation", "s"),
                ("./lateralProfile/superelevation", "s"),
                ("./lanes/laneOffset", "s"),
            ]:
                for el in road.findall(path):
                    s = CarlaImportSChecker._f(el.get(attr, "0"))
                    if s < 0:
                        el.set(attr, "0.0")
                        fixes += 1

            # update road length if needed
            max_end = 0.0
            for g in geoms:
                s = CarlaImportSChecker._f(g.get("s", "0"))
                gl = CarlaImportSChecker._f(g.get("length", "0"))
                max_end = max(max_end, s + gl)
            if max_end > 0:
                road_len = CarlaImportSChecker._f(road.get("length", "0"))
                if road_len + 1e-3 < max_end:
                    road.set("length", f"{max_end:.6f}")
                    fixes += 1

        return fixes, CarlaImportSChecker.validate(root)
