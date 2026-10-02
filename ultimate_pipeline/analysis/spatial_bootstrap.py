"""Spatial-block bootstrap for RQ2 structural metrics.

Roads are NOT independent samples (a subdivided arterial inflates n without new
information). This module partitions the manual footprint into a regular grid of
spatial blocks (in the manual map's native CRS), assigns each manual road and
each footprint-cropped auto road to a block by planView-centroid, and recomputes
block-level structural metrics with the same primitives as the RQ2 authority
(XODRMapStatsExtractor + DomainGapAnalyzer.compare_xodr_to_xodr).

Blocks with fewer than `min_manual_roads` manual roads are flagged low-support:
reported explicitly, excluded from dispersion summaries (never silently dropped).

Exploratory uncertainty only: no PASS thresholds are derived here.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.domain_gap import local_registration as _lr
from ultimate_pipeline.domain_gap.gap_analyzer import DomainGapAnalyzer
from ultimate_pipeline.domain_gap.map_stats_xodr import XODRMapStatsExtractor


@dataclass
class SpatialBlock:
    block_id: str
    col: int
    row: int
    manual_roads: int = 0
    auto_roads: int = 0
    manual_length_m: float = 0.0
    auto_length_m: float = 0.0
    lane_width_gap: Optional[float] = None
    curvature_gap: Optional[float] = None
    road_length_ratio: Optional[float] = None
    low_support: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _centroid(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    if not points:
        return None
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def spatial_block_bootstrap(
    auto_xodr: str,
    manual_xodr: str,
    *,
    grid: Tuple[int, int] = (2, 2),
    min_manual_roads: int = 5,
    footprint: str = "hull",
) -> Dict[str, Any]:
    """Partition the manual footprint into grid blocks; per-block RQ2 metrics."""
    ncols, nrows = grid
    if ncols < 1 or nrows < 1:
        raise ValueError("grid dimensions must be >= 1")
    if footprint not in ("hull", "bbox"):
        raise ValueError(f"footprint must be 'hull' or 'bbox', got {footprint!r}")

    auto_root = ET.parse(auto_xodr).getroot()
    manual_root = ET.parse(manual_xodr).getroot()
    auto_off = _lr.read_offset(auto_root)
    auto_proj = _lr.read_georef_proj4(auto_root)
    manual_proj = _lr.read_georef_proj4(manual_root)

    if footprint == "hull":
        poly = _lr.transform_manual_points_to_auto_local(
            _lr.manual_geometry_convex_hull(manual_root),
            manual_proj,
            auto_proj,
            auto_off,
        )
    else:
        poly = _lr.transform_manual_bbox_to_auto_local(
            _lr.manual_geometry_bbox(manual_root), manual_proj, auto_proj, auto_off
        )
    kept_auto = _lr.crop_roads_to_polygon(auto_root.findall("road"), poly)
    manual_roads = manual_root.findall("road")

    # Block grid over the manual native bbox.
    w, s, e, n = _lr.manual_geometry_bbox(manual_root)
    dx = (e - w) / ncols
    dy = (n - s) / nrows

    def block_of(pt: Tuple[float, float]) -> Tuple[int, int]:
        c = min(ncols - 1, max(0, int((pt[0] - w) / dx))) if dx > 0 else 0
        r = min(nrows - 1, max(0, int((pt[1] - s) / dy))) if dy > 0 else 0
        return c, r

    manual_bins: Dict[Tuple[int, int], List[ET.Element]] = {}
    for road in manual_roads:
        pts = _lr.road_geometry_points(road)
        c = _centroid(pts)
        if c is None:
            continue
        manual_bins.setdefault(block_of(c), []).append(road)

    # Auto roads are in auto-local frame: map each centroid back to manual frame
    # in one batched transform, then bin.
    auto_centroids = []
    auto_with_centroid = []
    for road in kept_auto:
        pts = _lr.road_geometry_points(road)
        c = _centroid(pts)
        if c is None:
            continue
        auto_with_centroid.append(road)
        auto_centroids.append(c)
    back = _lr.transform_auto_points_to_manual_local(
        auto_centroids, auto_proj4=auto_proj, auto_offset=auto_off,
        manual_proj4=manual_proj,
    )
    auto_bins: Dict[Tuple[int, int], List[ET.Element]] = {}
    for road, pt in zip(auto_with_centroid, back):
        auto_bins.setdefault(block_of(pt), []).append(road)

    blocks: List[SpatialBlock] = []
    for col in range(ncols):
        for row in range(nrows):
            key = (col, row)
            m_roads = manual_bins.get(key, [])
            a_roads = auto_bins.get(key, [])
            blk = SpatialBlock(
                block_id=f"c{col}r{row}", col=col, row=row,
                manual_roads=len(m_roads), auto_roads=len(a_roads),
            )
            if len(m_roads) < min_manual_roads or not a_roads:
                blk.low_support = True
                blocks.append(blk)
                continue
            m_tree = ET.Element("OpenDRIVE")
            for r in m_roads:
                m_tree.append(r)
            a_tree = ET.Element("OpenDRIVE")
            for r in a_roads:
                a_tree.append(r)
            try:
                m_stats = XODRMapStatsExtractor.from_root(m_tree)
                a_stats = XODRMapStatsExtractor.from_root(a_tree)
                scores = DomainGapAnalyzer.compare_xodr_to_xodr(m_stats, a_stats)
                blk.manual_length_m = round(m_stats.total_road_length, 1)
                blk.auto_length_m = round(a_stats.total_road_length, 1)
                blk.lane_width_gap = round(scores.lane_width_gap, 4)
                blk.curvature_gap = round(scores.curvature_gap, 4)
                if m_stats.total_road_length > 0:
                    blk.road_length_ratio = round(
                        a_stats.total_road_length / m_stats.total_road_length, 3
                    )
            except Exception:
                blk.low_support = True
            blocks.append(blk)

    return {
        "grid": [ncols, nrows],
        "footprint": footprint,
        "min_manual_roads": min_manual_roads,
        "auto_xodr": os.path.abspath(auto_xodr),
        "manual_xodr": os.path.abspath(manual_xodr),
        "blocks": [b.to_dict() for b in blocks],
        "n_low_support": sum(1 for b in blocks if b.low_support),
    }
