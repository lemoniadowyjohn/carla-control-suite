from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import matplotlib
matplotlib.use("Agg")  # headless backend: this system's default (tkagg) needs a display
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


def _resolve_similarity_scores(map_gap: Dict[str, Any]) -> Dict[str, float]:
    similarity = map_gap.get("similarity")
    if isinstance(similarity, dict) and similarity:
        return similarity

    agg = map_gap.get("aggregation") or {}
    if isinstance(agg.get("similarity"), dict) and agg.get("similarity"):
        return agg.get("similarity")

    derived: Dict[str, float] = {}
    components = agg.get("components") if isinstance(agg, dict) else {}
    if isinstance(components, dict):
        geom = components.get("geometry") if isinstance(components.get("geometry"), dict) else {}
        curv = components.get("curvature") if isinstance(components.get("curvature"), dict) else {}

        geom_norm = geom.get("rmse_norm")
        if isinstance(geom_norm, (int, float)):
            derived["geometry_score"] = max(0.0, min(1.0, 1.0 - float(geom_norm)))

        curv_norm = curv.get("kl_divergence_norm")
        if isinstance(curv_norm, (int, float)):
            derived["curvature_score"] = max(0.0, min(1.0, 1.0 - float(curv_norm)))

    composite = agg.get("composite") if isinstance(agg, dict) else None
    if isinstance(composite, (int, float)):
        derived["composite_score"] = max(0.0, min(1.0, 1.0 - float(composite)))

    return derived


def _normalize_per_tile_geometry_for_heatmap(per_tile_geom: Dict[str, Any]) -> Dict[str, float]:
    values: Dict[str, float] = {}
    for tile, raw in (per_tile_geom or {}).items():
        if not isinstance(tile, str):
            continue
        if isinstance(raw, (int, float)):
            values[tile] = float(raw)
            continue
        if not isinstance(raw, dict):
            continue
        for key in ("rmse_norm", "rmse", "hausdorff_norm", "hausdorff", "js_divergence"):
            v = raw.get(key)
            if isinstance(v, (int, float)):
                values[tile] = float(v)
                break
    return values


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate thesis figures from a run directory.")
    parser.add_argument("--run-dir", type=str, default=None, help="Path to the run output directory.")
    parser.add_argument("--out", type=str, default="figures/thesis", help="Output directory for figures.")
    args = parser.parse_args()

    figures_dir = args.out
    os.makedirs(figures_dir, exist_ok=True)
    saved: List[str] = []

    if args.run_dir:
        run_path = Path(args.run_dir)
        map_gap_path = run_path / "full_report.json"
        auto_aligned_xodr = run_path / "auto_aligned_hardened.xodr"
    else:
        map_gap_path = Path("logs/domain_gap/map_domain_gap_full.json")
        auto_aligned_xodr = Path("logs/domain_gap/auto_aligned.xodr")

    if not map_gap_path.is_file():
        raise RuntimeError(f"thesis_figures: map gap file missing: {map_gap_path}")

    map_gap = load_map_gap(str(map_gap_path))

    similarity = _resolve_similarity_scores(map_gap)
    if similarity:
        radar_png = os.path.join(figures_dir, "city_similarity_radar.png")
        plot_similarity_radar(
            sim_scores=similarity,
            out_png=radar_png,
        )
        if Path(radar_png).is_file():
            saved.append(radar_png)

    per_tile_geom = (
        map_gap.get("per_tile_geometry_gap")
        or (map_gap.get("per_tile_structural_gap") or {}).get("geometry")
        or (map_gap.get("structural_domain_gap", {}).get("geometry", {}) or {}).get("per_tile")
    )
    if per_tile_geom:
        heatmap_values = _normalize_per_tile_geometry_for_heatmap(per_tile_geom)
        if heatmap_values:
            heatmap_png = os.path.join(figures_dir, "per_tile_geom_gap_heatmap.png")
            TileHeatmapPlotter.plot(
                heatmap_values,
                out_png=heatmap_png,
                title="Per-Tile Geometric Gap",
            )
            if Path(heatmap_png).is_file():
                saved.append(heatmap_png)
        else:
            print("? Skipping per-tile heatmap: no numeric per-tile geometry values found.")

    manual_xodr = map_gap.get("reference_map", {}).get("path") or "cities/ingolstadt/manual_full.xodr"
    if os.path.isfile(manual_xodr) and auto_aligned_xodr.is_file():
        overlay_dir = os.path.join(figures_dir, "map_overlay")
        overlay_png = os.path.join(overlay_dir, "overlay_manual_vs_auto_aligned.png")
        plot_map_vs_map(str(manual_xodr), str(auto_aligned_xodr), overlay_dir)
        if Path(overlay_png).is_file():
            saved.append(overlay_png)

    exp_pattern = str(Path(args.run_dir) / "*_full_report.json") if args.run_dir else "logs/hpc/*_full_report.json"
    exp_reports = load_experiment_reports(exp_pattern)
    if exp_reports:
        scatter_png = os.path.join(figures_dir, "domain_vs_perception_scatter.png")
        plot_domain_vs_perception_scatter(
            exp_reports,
            out_png=scatter_png,
        )
        if Path(scatter_png).is_file():
            saved.append(scatter_png)

    if not saved:
        raise RuntimeError("thesis_figures: zero figures produced - check input artifact paths")
    print(f"? Thesis figures written to {figures_dir} ({len(saved)} files)")


if __name__ == "__main__":
    main()
