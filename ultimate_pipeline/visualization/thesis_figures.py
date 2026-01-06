# ultimate_pipeline/visualization/thesis_figures.py

from __future__ import annotations
import os
import json
import glob
from typing import Dict, Any, List

import matplotlib.pyplot as plt
import pandas as pd

from ultimate_pipeline.visualization.heatmap_plotter import TileHeatmapPlotter
from ultimate_pipeline.visualization.map_diff import overlay_maps


def load_map_gap(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_experiment_reports(pattern: str) -> List[Dict[str, Any]]:
    exps = []
    for p in glob.glob(pattern):
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_path"] = p
        exps.append(data)
    return exps


def plot_similarity_radar(sim_scores: Dict[str, float], out_png: str):
    labels = [k for k in sim_scores.keys() if k.endswith("_score")]
    values = [sim_scores[k] for k in labels]
    if not labels:
        return

    import numpy as np
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    values += values[:1]
    angles += angles[:1]

    fig, ax = plt.subplots(subplot_kw={"polar": True}, figsize=(5, 5))
    ax.plot(angles, values)
    ax.fill(angles, values, alpha=0.25)
    ax.set_thetagrids([a * 180 / np.pi for a in angles[:-1]], labels)
    ax.set_title("City Similarity Radar")
    ax.set_ylim(0, 1)

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_png, dpi=200)
    plt.close()


def plot_map_vs_map(manual_xodr: str, auto_xodr_aligned: str, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    overlay_maps(
        manual_xodr,
        auto_xodr_aligned,
        label_a="Manual",
        label_b="Auto (aligned)",
        out_png=os.path.join(out_dir, "overlay_manual_vs_auto_aligned.png"),
    )


def plot_domain_vs_perception_scatter(exps: List[Dict[str, Any]], out_png: str):
    rows = []
    for e in exps:
        dom = e.get("domain_gap", {})
        perc = e.get("perception_gap", {})
        row = {"experiment": e.get("experiment", "unknown")}
        for k, v in dom.items():
            row[f"domain_{k}"] = v
        for k, v in perc.items():
            row[f"perception_{k}"] = v
        rows.append(row)

    df = pd.DataFrame(rows)
    if "domain_lane_width_gap" not in df.columns or "perception_mAP_gap" not in df.columns:
        return

    plt.figure(figsize=(6, 4))
    plt.scatter(df["domain_lane_width_gap"], df["perception_mAP_gap"])
    plt.xlabel("Lane width domain gap")
    plt.ylabel("mAP gap (manual - auto)")
    plt.title("Lane Width Gap vs Detection mAP Gap")
    plt.grid(True, linewidth=0.3)

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_png, dpi=200)
    plt.close()


def main():
    figures_dir = "figures/thesis"
    os.makedirs(figures_dir, exist_ok=True)

    # 1) Load map domain gap
    map_gap_path = "logs/domain_gap/map_domain_gap_full.json"
    if not os.path.isfile(map_gap_path):
        print(f"⚠ Map gap file missing: {map_gap_path}")
        return

    map_gap = load_map_gap(map_gap_path)

    # 2) Radar plot of similarity
    if "similarity" in map_gap:
        plot_similarity_radar(
            sim_scores=map_gap["similarity"],
            out_png=os.path.join(figures_dir, "city_similarity_radar.png"),
        )

    # 3) Per-tile gap heatmap (already exists)
    if "per_tile_geometry_gap" in map_gap:
        TileHeatmapPlotter.plot(
            map_gap["per_tile_geometry_gap"],
            out_png=os.path.join(figures_dir, "per_tile_geom_gap_heatmap.png"),
            title="Per-Tile Geometric Gap",
        )

    # 4) Map overlay
    manual_xodr = "cities/ingolstadt/manual_full.xodr"
    auto_aligned_xodr = "logs/domain_gap/auto_aligned.xodr"
    if os.path.isfile(manual_xodr) and os.path.isfile(auto_aligned_xodr):
        plot_map_vs_map(manual_xodr, auto_aligned_xodr, os.path.join(figures_dir, "map_overlay"))

    # 5) Domain vs perception scatter
    exp_reports = load_experiment_reports("logs/hpc/*_full_report.json")
    if exp_reports:
        plot_domain_vs_perception_scatter(
            exp_reports,
            out_png=os.path.join(figures_dir, "domain_vs_perception_scatter.png"),
        )

    print(f"✅ Thesis figures written to {figures_dir}")


if __name__ == "__main__":
    main()
