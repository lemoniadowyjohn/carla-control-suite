# ultimate_pipeline/tile_validation/seam_repair.py
from __future__ import annotations

import math
import os
import statistics
import xml.etree.ElementTree as ET
from typing import Dict

from .lane_seam_checker import LaneSeamChecker


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


class SeamRepair:
    """Apply a small global transform to tile B to match tile A at the seam.

    Strategy:
      - run LaneSeamChecker to obtain matched lane endpoint deltas
      - compute average (dx, dy, dtheta, dz) to align B -> A
      - apply to ALL planView geometries and elevation 'a' (or legacy z)

    Notes:
      - This is a *best-effort* repair intended for small seam errors.
      - It is not a full topological stitcher.
    """

    @staticmethod
    def _apply_transform(root: ET.Element, dx: float, dy: float, dtheta: float, dz: float) -> None:
        cos_t = math.cos(dtheta)
        sin_t = math.sin(dtheta)

        # Apply to geometry starts
        for geom in root.findall(".//geometry"):
            x = _safe_float(geom.get("x", "0"))
            y = _safe_float(geom.get("y", "0"))

            # rotate around origin then translate
            x2 = cos_t * x - sin_t * y + dx
            y2 = sin_t * x + cos_t * y + dy

            geom.set("x", f"{x2:.6f}")
            geom.set("y", f"{y2:.6f}")

            hdg = _safe_float(geom.get("hdg", "0"))
            geom.set("hdg", f"{(hdg + dtheta):.6f}")

        # Elevation: OpenDRIVE uses a/b/c/d; some variants use z
        for elev in root.findall(".//elevation"):
            if elev.get("a") is not None:
                a = _safe_float(elev.get("a", "0"))
                elev.set("a", f"{(a + dz):.6f}")
            else:
                z = _safe_float(elev.get("z", "0"))
                elev.set("z", f"{(z + dz):.6f}")

    @staticmethod
    def repair(tile_a: str, tile_b: str, out_path: str) -> Dict:
        """Compute seam error and generate a new tile_b aligned to tile_a."""

        seam = LaneSeamChecker.analyze(tile_a, tile_b)

        if seam.lane_pairs:
            dxs = [p.get("dx", 0.0) for p in seam.lane_pairs]
            dys = [p.get("dy", 0.0) for p in seam.lane_pairs]
            dts = [p.get("dtheta", 0.0) for p in seam.lane_pairs]
            dzs = [p.get("dz", 0.0) for p in seam.lane_pairs]

            dx = statistics.mean(dxs)
            dy = statistics.mean(dys)
            dtheta = statistics.mean(dts)
            dz = statistics.mean(dzs)
        else:
            # Fallback: conservative nudge (keeps old behavior shape)
            dx = -seam.max_lateral_offset / 2.0
            dy = 0.0
            dtheta = -seam.max_heading_error / 2.0
            dz = -seam.max_elevation_jump / 2.0

        treeB = ET.parse(tile_b)
        rootB = treeB.getroot()

        SeamRepair._apply_transform(rootB, dx, dy, dtheta, dz)

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        treeB.write(out_path, encoding="utf-8")

        return {
            "dx": dx,
            "dy": dy,
            "dtheta": dtheta,
            "dz": dz,
            "warnings": seam.warnings,
            "matched_lane_pairs": len(seam.lane_pairs),
        }
