# ultimate_pipeline/domain_gap/tile_gap_heatmap.py

from __future__ import annotations

import json
import os
from typing import Dict, Any, Tuple

import matplotlib
matplotlib.use("Agg")  # headless backend: this system's default (tkagg) needs a display
import matplotlib.pyplot as plt
import numpy as np


# ============================================================
# Helpers
# ============================================================

def _parse_tile_index(tile_name: str) -> Tuple[int, int]:
    """
    Parse tile indices from:
      - tile_2_3
      - tile_2_3.xodr
      - tile_2_3_gap.json

    Returns (i, j)
    """
    base = os.path.basename(tile_name)

    for suffix in (".xodr", "_gap.json", ".json"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]

    if not base.startswith("tile_"):
        raise ValueError(f"Not a tile name: {tile_name}")

    parts = base.split("_")
    if len(parts) != 3:
        raise ValueError(f"Unexpected tile name pattern: {tile_name}")

    return int(parts[1]), int(parts[2])


def load_tile_gap_json(path: str) -> Dict[str, Dict[str, float]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# Matrix construction
# ============================================================

def build_gap_matrix(
    tile_gaps: Dict[str, Dict[str, float]],
    metric: str,
) -> Tuple[np.ndarray, np.ndarray, Tuple[float, float, float, float]]:
    """
    Build a 2D matrix [i, j] for a given metric.

    Returns:
      values   : float matrix with NaN for missing tiles
      valid    : boolean mask of valid tiles
      extent   : imshow extent (xmin, xmax, ymin, ymax)
    """
    indices = [_parse_tile_index(name) for name in tile_gaps.keys()]
    if not indices:
        raise ValueError("No tiles found in tile_gaps")

    is_ = [i for i, _ in indices]
    js_ = [j for _, j in indices]

    imin, imax = min(is_), max(is_)
    jmin, jmax = min(js_), max(js_)

    ni = imax - imin + 1
    nj = jmax - jmin + 1

    values = np.full((ni, nj), np.nan, dtype=float)
    valid = np.zeros_like(values, dtype=bool)

    for tile_name, metrics in tile_gaps.items():
        i, j = _parse_tile_index(tile_name)
        ii = i - imin
        jj = j - jmin
        v = metrics.get(metric, np.nan)
        values[ii, jj] = v
        valid[ii, jj] = True

    # Extent matches index coordinates
    extent = (
        imin - 0.5,
        imax + 0.5,
        jmin - 0.5,
        jmax + 0.5,
    )

    return values, valid, extent


# ============================================================
# Plotting
# ============================================================

def plot_tile_gap_heatmap(
    gap_json_path: str,
    metric: str,
    out_png: str,
    *,
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    annotate: bool = False,
) -> None:
    """
    Render a heatmap of per-tile domain gap for a given metric.

    Best used for:
      - geometry gaps
      - lane width gaps
      - curvature gaps
      - IoU-based tile rejection
    """
    tile_gaps = load_tile_gap_json(gap_json_path)
    values, valid, extent = build_gap_matrix(tile_gaps, metric)

    masked = np.ma.masked_invalid(values)

    plt.figure(figsize=(6.5, 5.5))

    im = plt.imshow(
        masked.T,
        origin="lower",
        extent=extent,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        interpolation="nearest",
        aspect="equal",
    )

    cbar = plt.colorbar(im)
    cbar.set_label(metric)

    plt.xlabel("tile i")
    plt.ylabel("tile j")
    plt.title(f"Per-tile domain gap heatmap: {metric}")

    if annotate:
        for tile_name in tile_gaps.keys():
            i, j = _parse_tile_index(tile_name)
            v = tile_gaps[tile_name].get(metric, None)
            if v is not None:
                plt.text(
                    i,
                    j,
                    f"{v:.2f}",
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="white" if v > (vmin or 0.5) else "black",
                )

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, dpi=200)
    plt.close()
