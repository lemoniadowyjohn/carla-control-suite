from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

import numpy as np

from .map_stats_xodr import XODRMapStats
from .map_stats_osm import OSMMapStats


# =============================================================================
# Utility functions
# =============================================================================

def _safe_mean(xs: List[float]) -> float:
    if not xs:
        return 0.0
    return float(sum(xs) / len(xs))


def _l1_hist_gap(
    xs: List[float],
    ys: List[float],
    *,
    bins: int = 30,
    eps: float = 1e-12,
) -> float:
    """
    Histogram-based L1 distance between two distributions.

    Output range: [0, 1]
    0   → identical distributions
    1   → maximally different
    """
    if not xs and not ys:
        return 0.0
    if not xs or not ys:
        return 1.0

    lo = min(min(xs), min(ys))
    hi = max(max(xs), max(ys))

    if hi <= lo:
        return 0.0

    hist_x, _ = np.histogram(xs, bins=bins, range=(lo, hi), density=True)
    hist_y, _ = np.histogram(ys, bins=bins, range=(lo, hi), density=True)

    hist_x = hist_x + eps
    hist_y = hist_y + eps

    hist_x /= hist_x.sum()
    hist_y /= hist_y.sum()

    # L1 distance scaled to [0,1]
    return float(0.5 * np.abs(hist_x - hist_y).sum())


def _relative_gap(a: float, b: float, scale: float) -> float:
    """
    Relative difference normalized by a scale.
    """
    if scale <= 0:
        return 0.0
    return min(1.0, abs(a - b) / scale)


def _density(count: int, length_m: float) -> float:
    """
    Objects per km of road.
    """
    if length_m <= 0:
        return 0.0
    return count / (length_m / 1000.0)


# =============================================================================
# Data container
# =============================================================================

@dataclass
class DomainGapScores:
    """
    Normalized domain-gap scores in [0,1].

    Interpretation:
        0.0 → identical
        0.2 → small but measurable gap
        0.5 → strong domain shift
        1.0 → severe mismatch
    """

    lane_width_gap: float
    curvature_gap: float
    road_length_gap: float
    traffic_light_density_gap: float
    building_density_gap: float
    road_type_coverage_gap: float

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


# =============================================================================
# Main analyzer
# =============================================================================

class DomainGapAnalyzer:
    """
    Compare OSM-derived map statistics against XODR-derived statistics
    and produce interpretable, normalized domain-gap metrics.
    """

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    @staticmethod
    def compare(
        osm_stats: OSMMapStats,
        xodr_stats: XODRMapStats,
        *,
        lane_width_scale_m: float = 3.5,
    ) -> DomainGapScores:
        """
        Compute structural domain-gap metrics.

        Parameters
        ----------
        lane_width_scale_m:
            Normalization scale for lane width gap (typical lane width).
        """

        # ------------------------------------------------------------
        # Lane width gap
        # ------------------------------------------------------------
        lane_width_gap = _relative_gap(
            osm_stats.avg_lane_width,
            xodr_stats.avg_lane_width,
            scale=lane_width_scale_m,
        )

        # ------------------------------------------------------------
        # Curvature distribution gap
        # ------------------------------------------------------------
        curvature_gap = _l1_hist_gap(
            osm_stats.curvature_samples,
            xodr_stats.curvature_samples,
        )

        # ------------------------------------------------------------
        # Road length coverage gap
        # ------------------------------------------------------------
        if osm_stats.total_road_length > 0:
            ratio = xodr_stats.total_road_length / osm_stats.total_road_length
            road_length_gap = min(1.0, abs(1.0 - ratio))
        else:
            road_length_gap = 0.0

        # ------------------------------------------------------------
        # Density-based gaps
        # ------------------------------------------------------------
        tl_dens_osm = _density(
            osm_stats.num_traffic_lights,
            osm_stats.total_road_length,
        )
        tl_dens_xodr = _density(
            xodr_stats.num_traffic_lights,
            xodr_stats.total_road_length,
        )

        bld_dens_osm = _density(
            osm_stats.num_buildings,
            osm_stats.total_road_length,
        )
        bld_dens_xodr = _density(
            xodr_stats.num_buildings,
            xodr_stats.total_road_length,
        )

        traffic_light_density_gap = _relative_gap(
            tl_dens_osm,
            tl_dens_xodr,
            scale=max(tl_dens_osm, 1.0),
        )

        building_density_gap = _relative_gap(
            bld_dens_osm,
            bld_dens_xodr,
            scale=max(bld_dens_osm, 1.0),
        )

        # ------------------------------------------------------------
        # Road type coverage gap
        # ------------------------------------------------------------
        osm_types = osm_stats.road_type_counts or {}
        xodr_types = xodr_stats.road_type_counts or {}

        if not osm_types:
            road_type_coverage_gap = 0.0
        else:
            missing = sum(1 for t in osm_types if t not in xodr_types)
            road_type_coverage_gap = missing / len(osm_types)

        return DomainGapScores(
            lane_width_gap=lane_width_gap,
            curvature_gap=curvature_gap,
            road_length_gap=road_length_gap,
            traffic_light_density_gap=traffic_light_density_gap,
            building_density_gap=building_density_gap,
            road_type_coverage_gap=road_type_coverage_gap,
        )

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    @staticmethod
    def save_json(scores: DomainGapScores, out_path: str) -> None:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(scores.to_dict(), f, indent=2)

    @classmethod
    def compare_xodr_to_xodr(cls, reference_stats, generated_stats):
        pass
