# ultimate_pipeline/visualization/tile_gap_heatmap.py

from __future__ import annotations
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")  # headless backend: this system's default (tkagg) needs a display
import matplotlib.pyplot as plt
from typing import Dict, Tuple
import os

class TileGapHeatmap:
    """
    Visualize per-tile domain gaps as a heatmap.

    Expected JSON format:
    {
        "tile_2_3.xodr": {"gap_score": 0.14},
        "tile_3_3.xodr": {"gap_score": 0.22},
        ...
    }
    """

    # ----------------------------
    # JSON Loader
    # ----------------------------
    @staticmethod
    def load_gap_json(path: str) -> Dict[str, Dict]:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ----------------------------
    # Convert dict → matrix
    # ----------------------------
    @staticmethod
    def build_matrix(tile_gap: Dict[str, Dict]) -> Tuple[np.ndarray, Dict[str, Tuple[int, int]]]:
        """
        Convert:
            { "tile_2_3.xodr": {"gap_score": 0.14}, ... }

        Into:
            M[i, j] = gap_score
            coords = {"tile_2_3.xodr": (2, 3), ...}
        """
        coords: Dict[str, Tuple[int, int]] = {}

        # Extract matrix coordinates from file names
        for tile in tile_gap:
            name = tile.replace(".xodr", "")
            if "_" not in name:
                continue

            try:
                _, i_str, j_str = name.split("_")
                coords[tile] = (int(i_str), int(j_str))
            except Exception:
                continue

        if not coords:
            raise RuntimeError("❌ No tile coordinates found in tile_gap keys.")

        max_i = max(c[0] for c in coords.values())
        max_j = max(c[1] for c in coords.values())

        M = np.zeros((max_i + 1, max_j + 1))

        for tile, (i, j) in coords.items():
            score = float(tile_gap[tile].get("gap_score", 0.0))
            M[i, j] = score

        return M, coords

    # ----------------------------
    # Heatmap Renderer
    # ----------------------------
    @staticmethod
    def plot_heatmap(
        gap_json: str,
        out_png: str,
        title: str = "Per-Tile Domain Gap Heatmap",
        cmap: str = "inferno",
        figsize=(9, 7)
    ) -> None:

        tile_gap = TileGapHeatmap.load_gap_json(gap_json)
        M, coords = TileGapHeatmap.build_matrix(tile_gap)

        plt.figure(figsize=figsize)
        im = plt.imshow(M, cmap=cmap, origin="lower")

        plt.colorbar(im, label="Domain Gap Score")
        plt.title(title, fontsize=14)
        plt.xlabel("Tile column (j)")
        plt.ylabel("Tile row (i)")

        # Add per-tile labels in each cell
        for tile, (i, j) in coords.items():
            value = M[i, j]
            label = tile.replace(".xodr", "")

            # Choose text color for visibility
            text_color = "white" if value > np.max(M) * 0.5 else "black"

            plt.text(
                j,
                i,
                label,
                ha="center",
                va="center",
                fontsize=7,
                color=text_color,
            )

        plt.tight_layout()

        # Create directory if needed
        out_dir = "/".join(out_png.split("/")[:-1])
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        plt.savefig(out_png, dpi=250)
        plt.close()

        print(f"📊 Saved tile heatmap → {out_png}")
