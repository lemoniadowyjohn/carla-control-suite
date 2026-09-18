# ultimate_pipeline/domain_gap/perception_plots.py

from __future__ import annotations

import json
import os
from typing import Dict, Any, List

import matplotlib.pyplot as plt
import numpy as np


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def load_experiment_report(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Plot 1: Per-class IoU gap
# ---------------------------------------------------------------------------

def plot_iou_gap_bar(
    report_path: str,
    out_png: str,
    *,
    sort_by_gap: bool = True,
) -> None:
    """
    Plot per-class IoU gap between manual and auto datasets.

    Definition:
        IoU gap = IoU(manual) − IoU(auto)

    Positive value:
        manual map produces better perception performance.
    """

    rep = load_experiment_report(report_path)
    pgap = rep.get("perception_gap", {})

    iou_gap = pgap.get("iou_gap_per_class", {})
    if not iou_gap:
        print("[plot_iou_gap_bar] No per-class IoU gaps found.")
        return

    classes = list(iou_gap.keys())
    values = np.array([iou_gap[c] for c in classes], dtype=float)

    if sort_by_gap:
        order = np.argsort(values)[::-1]
        classes = [classes[i] for i in order]
        values = values[order]

    x = np.arange(len(classes))

    plt.figure(figsize=(9, 4.5))
    plt.bar(x, values)
    plt.axhline(0.0, linestyle="--", linewidth=1, color="black")

    plt.xticks(x, classes, rotation=45, ha="right")
    plt.ylabel("IoU(manual) − IoU(auto)")
    plt.title("Per-class perception gap (IoU)")
    plt.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, dpi=200)
    plt.close()

    print(f"[plot_iou_gap_bar] Saved → {out_png}")


# ---------------------------------------------------------------------------
# Plot 2: Mean IoU + mAP gap summary
# ---------------------------------------------------------------------------

def plot_perception_gap_summary(
    report_path: str,
    out_png: str,
) -> None:
    """
    Plot aggregate perception gap metrics:
      - mean IoU gap
      - mAP gap

    Useful as a compact thesis figure.
    """

    rep = load_experiment_report(report_path)
    pgap = rep.get("perception_gap", {})

    mean_iou_gap = pgap.get("mean_iou_gap", None)
    map_gap = pgap.get("mAP_gap", None)

    if mean_iou_gap is None and map_gap is None:
        print("[plot_perception_gap_summary] No aggregate perception metrics found.")
        return

    labels = []
    values = []

    if mean_iou_gap is not None:
        labels.append("Mean IoU gap")
        values.append(mean_iou_gap)

    if map_gap is not None:
        labels.append("mAP gap")
        values.append(map_gap)

    x = np.arange(len(labels))

    plt.figure(figsize=(5, 4))
    plt.bar(x, values)
    plt.axhline(0.0, linestyle="--", linewidth=1, color="black")

    plt.xticks(x, labels)
    plt.ylabel("Metric(manual) − Metric(auto)")
    plt.title("Aggregate perception gap")
    plt.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, dpi=200)
    plt.close()

    print(f"[plot_perception_gap_summary] Saved → {out_png}")


# ---------------------------------------------------------------------------
# Plot 3: Experiment comparison (absolute performance)
# ---------------------------------------------------------------------------

def plot_map_comparison(
    reports: Dict[str, str],
    out_png: str,
    *,
    metric: str = "mAP",
) -> None:
    """
    Compare absolute perception performance across experiments.

    reports:
        {experiment_label: path_to_report.json}

    metric:
        "mAP" or "mean_miou"

    IMPORTANT:
        This plot compares ABSOLUTE performance,
        not domain-gap deltas.
    """

    labels: List[str] = []
    values: List[float] = []

    for label, path in reports.items():
        try:
            rep = load_experiment_report(path)
        except FileNotFoundError:
            print(f"[plot_map_comparison] Missing report: {path}")
            continue

        pgap = rep.get("perception_gap", {})

        if metric == "mAP":
            val = pgap.get("mAP_absolute")
        elif metric == "mean_miou":
            val = pgap.get("mean_miou_absolute")
        else:
            raise ValueError(f"Unknown metric: {metric}")

        if val is None:
            print(f"[plot_map_comparison] Metric '{metric}' missing for {label}")
            continue

        labels.append(label)
        values.append(float(val))

    if not labels:
        print("[plot_map_comparison] No valid experiments to plot.")
        return

    x = np.arange(len(labels))

    plt.figure(figsize=(6, 4))
    plt.bar(x, values)
    plt.xticks(x, labels)
    plt.ylabel(metric)
    plt.title(f"Perception performance comparison ({metric})")
    plt.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, dpi=200)
    plt.close()

    print(f"[plot_map_comparison] Saved → {out_png}")
