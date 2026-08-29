# ultimate_pipeline/visualization/city_map_diff.py

from __future__ import annotations
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")  # headless backend: this system's default (tkagg) needs a display
import matplotlib.pyplot as plt
from typing import Dict, List

from ultimate_pipeline.domain_gap.geo_alignment import GeoAligner
from ultimate_pipeline.visualization.map_diff import _load_polylines


class CityMapDiff:
    """
    Creates high-resolution map comparison images for:
      - Manual vs Auto (unaligned)
      - Manual vs Auto (aligned)
    """

    @staticmethod
    def render_full_city(
        xodr_path: str,
        color: str = "black",
        step=5.0
    ) -> list[list[tuple[float, float]]]:
        """Load polylines using existing sampler."""
        polys = _load_polylines(xodr_path)
        return polys

    @staticmethod
    def plot_two_city_maps(
        manual_xodr: str,
        auto_xodr: str,
        out_png: str,
        aligned=False,
        figsize=(10, 10),
        lw=0.5
    ):
        """
        Render full city overlay showing geometry divergence.
        """
        if aligned:
            print("🔄 Estimating alignment...")
            transform = GeoAligner.estimate_from_xodr(manual_xodr, auto_xodr)
            aligned_xodr = auto_xodr.replace(".xodr", "_aligned.xodr")

            GeoAligner.apply_to_xodr(auto_xodr, aligned_xodr, transform)
            auto_load = aligned_xodr
        else:
            auto_load = auto_xodr

        print("📦 Loading polylines...")
        polys_a = _load_polylines(manual_xodr)
        polys_b = _load_polylines(auto_load)

        print("🎨 Rendering...")

        plt.figure(figsize=figsize)

        # manual
        for p in polys_a:
            xs = [x for x, y in p]
            ys = [y for x, y in p]
            plt.plot(xs, ys, color="black", lw=lw, alpha=0.9)

        # auto
        for p in polys_b:
            xs = [x for x, y in p]
            ys = [y for x, y in p]
            plt.plot(xs, ys, color="red", lw=lw, alpha=0.6)

        plt.gca().set_aspect("equal", "box")
        plt.grid(True, lw=0.3)
        plt.title("Manual (black) vs Auto (red)" + (" [aligned]" if aligned else ""))

        os.makedirs(os.path.dirname(out_png), exist_ok=True)
        plt.savefig(out_png, dpi=300)
        plt.close()

        print(f"📸 Saved map comparison → {out_png}")
