from __future__ import annotations
import os

from ultimate_pipeline.visualization.map_diff import overlay_maps
from ultimate_pipeline.visualization.tile_gap_heatmap import TileGapHeatmap
from ultimate_pipeline.visualization.city_drift_field import CityDriftField
from ultimate_pipeline.visualization.curvature_drift_plot import CurvatureDriftPlot


def generate_all():
    os.makedirs("figures", exist_ok=True)

    overlay_maps(
        "cities/ingolstadt/manual_full.xodr",
        "cities/ingolstadt/auto_full_aligned.xodr",
        "Manual",
        "Auto (aligned)",
        "figures/map_overlay.png"
    )

    TileGapHeatmap.plot_heatmap(
        "domain_gap/per_tile_gap.json",
        "figures/tile_gap_heatmap.png"
    )

    CityDriftField.plot(
        "cities/ingolstadt/manual_full.xodr",
        "cities/ingolstadt/auto_full_aligned.xodr",
        "figures/city_drift_field.png"
    )

    CurvatureDriftPlot.plot(
        "cities/ingolstadt/manual_full.xodr",
        "cities/ingolstadt/auto_full_aligned.xodr",
        "figures/curvature_drift.png"
    )

    print("📘 All thesis figures generated.")


if __name__ == "__main__":
    generate_all()
