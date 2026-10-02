"""RQ2 sensitivity analysis over predeclared parameterization variants.

Variants (declared up front; primary result reported first; no cherry-picking):
  1. footprint: hull (primary) vs bbox context
  2. road-matching threshold: frechet match_threshold_m in {30.0, 50.0, 75.0}
  3. geometry sampling spacing: frechet spacing_m in {2.5, 5.0, 10.0}
  4. small alignment perturbations: NOT_APPLICABLE -- the authority path uses
     datum-correct CRS reprojection (no fitted alignment to perturb); the
     fitted-alignment path (GeoAligner) is oracle-only.

Only the primary comparison is a thesis result; all variants are robustness
context around it.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from ultimate_pipeline.domain_gap import rq2_metric_authority as _auth
from ultimate_pipeline.domain_gap.frechet_gap import compute_frechet_gap

MATCH_THRESHOLDS_M = (30.0, 50.0, 75.0)
SPACINGS_M = (2.5, 5.0, 10.0)


def run_sensitivity(
    auto_xodr: str, manual_xodr: str, *, primary: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """Run predeclared variants; `primary` is the already-computed hull result."""
    variants: List[Dict[str, Any]] = []

    bbox_res = _auth.run_rq2_comparison(
        auto_xodr, manual_xodr, "manual_hull", {"footprint": "bbox"}
    )
    bp = bbox_res.primary
    variants.append({
        "variant": "footprint=bbox (context; primary is hull)",
        "lane_width_gap": bp["lane_width_gap"],
        "curvature_gap": bp["curvature_gap"],
        "road_length_ratio": bp["road_length_ratio"],
        "junction_ratio": bp["junction_ratio"],
        "road_count_ratio": bp["road_count_ratio"],
        "frechet_mean_m": bp["frechet_distance"].get("mean_m"),
        "frechet_median_m": bp["frechet_distance"].get("median_m"),
        "frechet_p90_m": bp["frechet_distance"].get("p90_m"),
        "frechet_pairs": bp["frechet_distance"].get("matched_pair_count"),
    })

    for thr in MATCH_THRESHOLDS_M:
        fr = compute_frechet_gap(
            auto_xodr, manual_xodr, match_threshold_m=thr, footprint="hull"
        )
        variants.append({
            "variant": f"frechet match_threshold_m={thr}",
            "frechet_mean_m": fr.get("mean_m"),
            "frechet_median_m": fr.get("median_m"),
            "frechet_p90_m": fr.get("p90_m"),
            "frechet_pairs": fr.get("matched_pair_count"),
        })

    for sp in SPACINGS_M:
        fr = compute_frechet_gap(
            auto_xodr, manual_xodr, spacing_m=sp, footprint="hull"
        )
        variants.append({
            "variant": f"frechet spacing_m={sp}",
            "frechet_mean_m": fr.get("mean_m"),
            "frechet_median_m": fr.get("median_m"),
            "frechet_p90_m": fr.get("p90_m"),
            "frechet_pairs": fr.get("matched_pair_count"),
        })

    variants.append({
        "variant": "small alignment perturbations",
        "status": "NOT_APPLICABLE",
        "reason": "authority path uses datum-correct CRS reprojection (no fitted "
        "alignment parameters to perturb); GeoAligner fitted path is oracle-only",
    })

    out: Dict[str, Any] = {
        "primary_first": True,
        "primary": (primary or {}),
        "variants": variants,
        "auto_xodr": os.path.abspath(auto_xodr),
        "manual_xodr": os.path.abspath(manual_xodr),
        "no_cherry_picking": "all predeclared variants reported; primary (hull, "
        "threshold 50 m, spacing 5 m) stated first regardless of outcome",
    }
    return out
