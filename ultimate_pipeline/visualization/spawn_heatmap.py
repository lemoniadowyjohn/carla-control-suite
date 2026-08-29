#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Spawn Heatmap Plotter

Reads spawn_probe_details.json (from qa_tile_spawn_probe.py) and
creates a simple 2D scatter plot of broken spawn locations per tile.

This is a post-processing tool for analysis / thesis figures.
"""

import os
import json
from typing import Dict, Any

import matplotlib
matplotlib.use("Agg")  # headless backend: this system's default (tkagg) needs a display
import matplotlib.pyplot as plt


def plot_spawn_heatmap(
    details_json: str,
    out_png: str,
    title: str = "Broken spawnpoints (per tile)",
) -> None:
    if not os.path.isfile(details_json):
        print(f"⚠ spawn_heatmap: details JSON not found: {details_json}")
        return

    with open(details_json, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)

    xs = []
    ys = []

    # data structure: { "tile_0_0.xodr": [ { "x": ..., "y": ..., ... }, ...], ... }
    for tile_name, broken_list in data.items():
        for entry in broken_list:
            x = entry.get("x")
            y = entry.get("y")
            if x is None or y is None:
                continue
            xs.append(x)
            ys.append(y)

    if not xs:
        print("⚠ spawn_heatmap: no broken spawnpoints found in JSON.")
        return

    plt.figure()
    plt.scatter(xs, ys, s=8, alpha=0.6)
    plt.xlabel("X [m]")
    plt.ylabel("Y [m]")
    plt.title(title)
    plt.axis("equal")
    plt.grid(True)

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, dpi=200)
    plt.close()

    print(f"🗺 Spawn heatmap saved → {out_png}")


if __name__ == "__main__":
    # Example manual usage:
    base = r"C:\path\to\your\ultimate_pipeline_out\2025xxxx_xxxxxx"
    details = os.path.join(base, "spawn_probe", "spawn_probe_details.json")
    out_img = os.path.join(base, "spawn_probe", "spawn_heatmap.png")
    plot_spawn_heatmap(details, out_img)
