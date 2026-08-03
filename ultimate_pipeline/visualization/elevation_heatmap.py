#!/usr/bin/env python3
from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import List, Tuple

import matplotlib.pyplot as plt
import rasterio
import numpy as np


def _sample_road_xy(root: ET.Element, step: float = 20.0) -> List[Tuple[float, float]]:
    pts = []
    for geom in root.findall(".//geometry"):
        x = float(geom.get("x", "0"))
        y = float(geom.get("y", "0"))
        length = float(geom.get("length", "0"))
        hdg = float(geom.get("hdg", "0"))

        n = max(2, int(length / step))
        for i in range(n + 1):
            ds = length * (i / n)
            px = x + ds * np.cos(hdg)
            py = y + ds * np.sin(hdg)
            pts.append((px, py))
    return pts


def save_tile_elevation_heatmap(tile_xodr: str, dem_path: str, out_png: str):
    """
    Samples the DEM along road geometry and plots elevation as a 2D heatmap-like scatter.
    """
    tree = ET.parse(tile_xodr)
    root = tree.getroot()

    pts_xy = _sample_road_xy(root)
    if not pts_xy:
        return

    with rasterio.open(dem_path) as ds:
        coords = [(x, y) for (x, y) in pts_xy]
        zs = list(ds.sample(coords))
        z_vals = np.array([z[0] for z in zs])

    xs = np.array([p[0] for p in pts_xy])
    ys = np.array([p[1] for p in pts_xy])

    plt.figure()
    plt.scatter(xs, ys, c=z_vals, s=5)
    plt.colorbar(label="Elevation [m]")
    plt.title(f"Tile elevation heatmap\n{tile_xodr}")
    plt.xlabel("X [m]")
    plt.ylabel("Y [m]")
    plt.axis("equal")
    plt.tight_layout()
    plt.savefig(out_png)
    plt.close()
