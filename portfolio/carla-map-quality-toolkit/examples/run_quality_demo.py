from pathlib import Path

import numpy as np

from carla_map_quality_toolkit.alignment import SE2Transform, estimate_se2
from carla_map_quality_toolkit.lane_quality import compare_width_profiles
from carla_map_quality_toolkit.metrics import symmetric_hausdorff
from carla_map_quality_toolkit.reporting import build_quality_report


def main() -> None:
    out = Path("out")
    out.mkdir(exist_ok=True)

    reference = np.column_stack([np.linspace(0, 50, 101), 0.5 * np.sin(np.linspace(0, 2.5, 101))])
    observed = SE2Transform(angle_rad=0.01, tx=0.30, ty=-0.15).apply(reference)
    observed[:, 1] += 0.03 * np.sin(np.linspace(0, 8.0, 101))

    fitted, rmse = estimate_se2(observed, reference)
    aligned = fitted.apply(observed)
    hausdorff = symmetric_hausdorff(aligned, reference)

    reference_width = np.full(101, 3.50)
    observed_width = 3.50 + 0.05 * np.sin(np.linspace(0, 5.0, 101))
    width = compare_width_profiles(observed_width, reference_width)

    report = build_quality_report(
        hausdorff_m=hausdorff,
        alignment_rmse_m=rmse,
        lane_width=width,
        topology_errors=0,
        provenance={
            "reference": "synthetic curve generated in examples/run_quality_demo.py",
            "observed": "deterministically perturbed synthetic curve",
            "asset_policy": "no proprietary map assets",
        },
    )
    report.write_json(out / "quality_report.json")
    report.write_markdown(out / "quality_report.md")
    print(report.status)


if __name__ == "__main__":
    main()
