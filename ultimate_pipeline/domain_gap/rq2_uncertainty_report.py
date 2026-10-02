"""RQ2 spatial-uncertainty report (exploratory, no PASS thresholds).

Consumes ultimate_pipeline.analysis.spatial_bootstrap output and summarizes
across-block variability (mean/std/min/max over supported blocks) for the
applicable RQ2 metrics. Uncertainty here is descriptive dispersion across
space, NOT a confidence interval for the headline result and NOT a gate.
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional

from ultimate_pipeline.analysis.spatial_bootstrap import spatial_block_bootstrap


def _summarize(values: List[float]) -> Dict[str, Any]:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "status": "NO_SUPPORTED_BLOCKS"}
    out: Dict[str, Any] = {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 4),
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
    }
    out["stdev"] = round(statistics.stdev(vals), 4) if len(vals) >= 2 else 0.0
    return out


def build_uncertainty_report(
    auto_xodr: str,
    manual_xodr: str,
    *,
    grid=(2, 2),
    min_manual_roads: int = 5,
    footprint: str = "hull",
) -> Dict[str, Any]:
    boot = spatial_block_bootstrap(
        auto_xodr,
        manual_xodr,
        grid=grid,
        min_manual_roads=min_manual_roads,
        footprint=footprint,
    )
    supported = [b for b in boot["blocks"] if not b["low_support"]]
    report: Dict[str, Any] = {
        "method": "spatial blocks (grid over manual footprint), roads binned by centroid; "
        "low-support blocks excluded from dispersion (listed, not dropped silently)",
        "grid": boot["grid"],
        "footprint": footprint,
        "n_blocks": len(boot["blocks"]),
        "n_supported": len(supported),
        "low_support_block_ids": [b["block_id"] for b in boot["blocks"] if b["low_support"]],
        "blocks": boot["blocks"],
        "dispersion": {
            "lane_width_gap": _summarize([b["lane_width_gap"] for b in supported]),
            "curvature_gap": _summarize([b["curvature_gap"] for b in supported]),
            "road_length_ratio": _summarize([b["road_length_ratio"] for b in supported]),
        },
        "no_pass_thresholds": True,
    }
    return report
