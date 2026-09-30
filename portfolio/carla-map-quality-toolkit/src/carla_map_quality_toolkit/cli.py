from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from carla_map_quality_toolkit.alignment import SE2Transform, estimate_se2
from carla_map_quality_toolkit.lane_quality import compare_width_profiles
from carla_map_quality_toolkit.metrics import symmetric_hausdorff
from carla_map_quality_toolkit.reporting import build_quality_report


def _demo(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    reference = np.column_stack([np.linspace(0, 40, 81), np.zeros(81)])
    synthetic = SE2Transform(angle_rad=0.015, tx=0.20, ty=-0.10).apply(reference)
    fitted, rmse = estimate_se2(synthetic, reference)
    aligned = fitted.apply(synthetic)
    hausdorff = symmetric_hausdorff(aligned, reference)

    reference_widths = np.full(81, 3.50)
    observed_widths = 3.50 + 0.04 * np.sin(np.linspace(0, 3.0, 81))
    width_metrics = compare_width_profiles(observed_widths, reference_widths)

    report = build_quality_report(
        hausdorff_m=hausdorff,
        alignment_rmse_m=rmse,
        lane_width=width_metrics,
        topology_errors=0,
        provenance={
            "fixture": "synthetic_straight_road_v1",
            "source": "generated; no proprietary assets",
            "alignment": "paired-point deterministic SE(2)",
        },
    )
    report.write_json(output / "quality_report.json")
    report.write_markdown(output / "quality_report.md")
    print(f"{report.status}: wrote {output / 'quality_report.json'}")
    return 0 if report.status == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="CARLA/OpenDRIVE map quality toolkit")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Run a sanitized synthetic quality-gate example")
    demo.add_argument("--output", type=Path, default=Path("out"))
    args = parser.parse_args()
    if args.command == "demo":
        return _demo(args.output)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
