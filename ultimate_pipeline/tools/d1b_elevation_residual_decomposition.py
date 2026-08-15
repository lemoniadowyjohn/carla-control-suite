#!/usr/bin/env python3
"""D1b: decompose XODR-vs-DEM elevation residuals by structure class."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from ultimate_pipeline.tools.visual_mesh_elevation_warp import (
    RasterDemSampler,
    decompose_xodr_dem_elevation_residuals,
    load_structure_class_map,
    sha256_file,
)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xodr", required=True, type=Path)
    parser.add_argument("--dem", required=True, type=Path)
    parser.add_argument("--structure-cache", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--sample-limit", type=int, default=0)
    parser.add_argument("--at-grade-p95-threshold-m", type=float, default=5.0)
    parser.add_argument("--at-grade-max-threshold-m", type=float, default=10.0)
    args = parser.parse_args(argv)

    sampler = RasterDemSampler(args.dem)
    road_classes = load_structure_class_map(args.structure_cache)
    report = decompose_xodr_dem_elevation_residuals(
        args.xodr,
        sample_dem=sampler,
        road_class_by_id=road_classes,
        sample_limit=args.sample_limit,
        at_grade_p95_threshold_m=args.at_grade_p95_threshold_m,
        at_grade_max_threshold_m=args.at_grade_max_threshold_m,
    )
    report.update(
        {
            "xodr_sha256": sha256_file(args.xodr),
            "dem_sha256": sha256_file(args.dem),
            "structure_cache": str(args.structure_cache),
            "structure_cache_sha256": sha256_file(args.structure_cache),
            "road_classes_loaded": int(len(road_classes)),
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "verdict": report["verdict"],
                "overall": report["overall"]["residual_summary"],
                "tail_interpretation": report["tail_interpretation"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
