# ultimate_pipeline/visualization/heatmap_plotter.py

from __future__ import annotations
import os
import numpy as np
from typing import Dict, Tuple, Optional

# Force a headless backend before importing pyplot: this system's (and any
# server/CI environment's) matplotlib default can be an interactive GUI
# backend (e.g. tkagg) that requires a display and crashes with a TclError
# when Tk isn't properly installed. run_full_domain_gap.py imports this
# module directly without first importing visualization/map_plotter.py
# (the sibling module that already does this), so there is no other
# safety net for this call path.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


class TileHeatmapPlotter:
    """
    Visualize per-tile domain/perception gap values as a heatmap.
    Expects a dict:
       {
          "tile_0_0.xodr": value,
          "tile_0_1.xodr": value,
          ...
       }
    """

    @staticmethod
    def _parse_tile_name(tile_name: str) -> Tuple[int, int]:
        """
        tile_3_2.xodr → (3, 2)
        Robustly handle paths like 'C:/runs/tiles/tile_3_2.xodr' or just 'tile_3_2'.
        """
        name = os.path.basename(tile_name)
        if "." in name:
            name = name.split(".")[0]
        
        parts = name.split("_")
        if len(parts) < 3:
             # Fallback or error
             return 0, 0
             
        try:
            return int(parts[1]), int(parts[2])
        except (ValueError, IndexError):
            return 0, 0

    @staticmethod
    def plot(
        tile_values: Dict[str, float],
        out_png: str,
        title: str = "Per-Tile Gap Heatmap",
        cmap: str = "viridis",
        vmin: Optional[float] = None,
        vmax: Optional[float] = None,
    ) -> None:

        # Determine grid size
        coords = [TileHeatmapPlotter._parse_tile_name(t) for t in tile_values.keys()]
        max_i = max(i for (i, j) in coords)
        max_j = max(j for (i, j) in coords)

        heatmap = np.full((max_i + 1, max_j + 1), np.nan)

        for tile, val in tile_values.items():
            i, j = TileHeatmapPlotter._parse_tile_name(tile)
            heatmap[i, j] = val

        plt.figure(figsize=(8, 6))
        im = plt.imshow(
            heatmap,
            cmap=cmap,
            interpolation="nearest",
            vmin=vmin,
            vmax=vmax,
            origin="lower"
        )

        plt.colorbar(im, label="Gap Value")
        plt.title(title)
        plt.xlabel("Tile column (j)")
        plt.ylabel("Tile row (i)")

        for (i, j), v in np.ndenumerate(heatmap):
            if not np.isnan(v):
                plt.text(j, i, f"{v:.2f}", ha="center", va="center", color="white")

        os.makedirs(os.path.dirname(out_png), exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_png, dpi=200)
        plt.close()

        print(f"[TileHeatmapPlotter] Saved heatmap → {out_png}")
