#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Experiment: does "natural" domain randomization occur across generated maps?

Requirement coverage:
 - "To better understand variability and improve robustness you will generate many maps using the osm to Carla pipeline and analyze whether domain randomization occurs naturally."

Input:
 - a directory containing multiple .xodr files (each from OSM→XODR run)

What it computes (CARLA-free):
 - per-map structural statistics via XODRMapStatsExtractor
 - variance + coefficient of variation across maps
 - a simple pairwise distance score (normalized L2 in metric-space)

Output:
 - CSV of per-map metrics
 - JSON summary with variability indicators
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from ultimate_pipeline.domain_gap.map_stats_xodr import XODRMapStatsExtractor


METRICS = [
    "total_road_length",
    "num_roads",
    "num_junctions",
    "num_roundabouts",
    "num_traffic_lights",
    "num_buildings",
]


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr-dir", required=True, help="folder with many .xodr")
    ap.add_argument("--out-dir", default="out_domain_randomization")
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    xdir = Path(args.xodr_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(xdir.rglob("*.xodr"))
    if args.limit and args.limit > 0:
        files = files[: args.limit]
    if not files:
        raise FileNotFoundError(f"No .xodr files found under: {xdir}")

    rows = []
    for p in files:
        stats = XODRMapStatsExtractor.from_file(str(p)).to_dict()
        row = {"path": str(p)}
        for k in METRICS:
            row[k] = stats.get(k)
        rows.append(row)
        print(f"✓ {p.name}: roads={row['num_roads']} junc={row['num_junctions']} len={row['total_road_length']:.1f}")

    # Write CSV
    csv_path = out_dir / "per_map_metrics.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["path"] + METRICS)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Variability summary
    mat = np.array([[float(r[k]) for k in METRICS] for r in rows], dtype=np.float64)
    mu = mat.mean(axis=0)
    sd = mat.std(axis=0)
    cv = sd / np.maximum(1e-9, np.abs(mu))

    # Pairwise normalized L2 (simple proxy for "how different" maps are)
    z = (mat - mu) / np.maximum(1e-9, sd)
    dists = []
    for i in range(len(z)):
        for j in range(i + 1, len(z)):
            dists.append(float(np.linalg.norm(z[i] - z[j])))

    summary = {
        "n_maps": len(rows),
        "metrics": {m: {"mean": float(mu[i]), "std": float(sd[i]), "cv": float(cv[i])} for i, m in enumerate(METRICS)},
        "pairwise_z_l2": {
            "mean": float(np.mean(dists)) if dists else 0.0,
            "std": float(np.std(dists)) if dists else 0.0,
            "min": float(np.min(dists)) if dists else 0.0,
            "max": float(np.max(dists)) if dists else 0.0,
        },
        "interpretation": (
            "Higher coefficients of variation (cv) and higher pairwise distances indicate stronger natural map variability. "
            "If all cv≈0 and pairwise distances≈0, your pipeline is effectively deterministic for these metrics."
        ),
        "csv": str(csv_path),
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"✅ Wrote: {csv_path}")
    print(f"✅ Wrote: {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
