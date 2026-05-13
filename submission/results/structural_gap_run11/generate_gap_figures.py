#!/usr/bin/env python
"""
Generate domain-gap analysis figures and tables for thesis.

Outputs (written to same directory as this script):
  fig_road_type_distribution.png   -- road type count + length bar chart
  fig_intersection_density.png     -- intersection type comparison
  fig_semantic_depletion.png       -- per-class object gap table/chart
  gap_summary_table.csv            -- machine-readable summary table

Also patches full_report.json:
  - method string: removes misleading "ICP refinement" label
  - adds alignment_method_note key
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ── locate outputs relative to this script ────────────────────────────────────
HERE = Path(__file__).parent
REPO = HERE.parents[2]  # carla_-main  (run_11 → structural_gap_v1 → thesis_results → carla_-main)

# ── source data ───────────────────────────────────────────────────────────────
DGR = REPO / "domain_gap_results"
RUN11 = HERE

# ── matplotlib (non-interactive) ─────────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ══════════════════════════════════════════════════════════════════════════════
# 1.  Road-type distribution
# ══════════════════════════════════════════════════════════════════════════════

def _road_type_chart() -> None:
    sem = json.loads((DGR / "gap_whole_semantics.json").read_text())
    rt = sem["road_types"]

    # length in km
    auto_len = {k: v / 1000 for k, v in rt["auto_length"].items()}
    manual_len = {k: v / 1000 for k, v in rt["manual_length"].items()}

    classes = sorted(set(auto_len) | set(manual_len))
    x = np.arange(len(classes))
    w = 0.35

    auto_vals  = [auto_len.get(c, 0)   for c in classes]
    manual_vals = [manual_len.get(c, 0) for c in classes]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Road-Type Distribution: Auto-Generated vs Manual Map", fontsize=13, fontweight="bold")

    # ── length bars ─────────────────────────────────────────────────────────
    bars1 = ax1.bar(x - w/2, auto_vals,   w, label="Auto (OSM→XODR)", color="#2196F3", alpha=0.85)
    bars2 = ax1.bar(x + w/2, manual_vals, w, label="Manual (reference)", color="#FF9800", alpha=0.85)
    ax1.set_xticks(x); ax1.set_xticklabels([c.capitalize() for c in classes])
    ax1.set_ylabel("Road length (km)")
    ax1.set_title("Road length by type")
    ax1.legend()

    for bar in bars1:
        h = bar.get_height()
        if h > 0:
            ax1.text(bar.get_x() + bar.get_width()/2, h + 1, f"{h:.0f}", ha="center", va="bottom", fontsize=8)
    for bar in bars2:
        h = bar.get_height()
        if h > 0:
            ax1.text(bar.get_x() + bar.get_width()/2, h + 1, f"{h:.0f}", ha="center", va="bottom", fontsize=8)

    # ── road count bars ──────────────────────────────────────────────────────
    clf = json.loads((DGR / "gap_whole_road_classification.json").read_text())
    cat_classes = sorted(set(clf["auto_counts"]) | set(clf["manual_counts"]))
    cx = np.arange(len(cat_classes))
    auto_cnts  = [clf["auto_counts"].get(c, 0)   for c in cat_classes]
    man_cnts   = [clf["manual_counts"].get(c, 0) for c in cat_classes]

    ax2.bar(cx - w/2, auto_cnts,  w, label="Auto (OSM→XODR)", color="#2196F3", alpha=0.85)
    ax2.bar(cx + w/2, man_cnts,   w, label="Manual (reference)", color="#FF9800", alpha=0.85)
    ax2.set_xticks(cx); ax2.set_xticklabels([c.capitalize() for c in cat_classes])
    ax2.set_ylabel("Road segment count")
    ax2.set_title("Road segment count by classification")
    ax2.legend()

    for bars, vals in [(ax2.patches[:len(cat_classes)], auto_cnts),
                       (ax2.patches[len(cat_classes):], man_cnts)]:
        for bar, v in zip(bars, vals):
            if v > 0:
                ax2.text(bar.get_x() + bar.get_width()/2,
                         bar.get_height() + 20, str(v),
                         ha="center", va="bottom", fontsize=8)

    plt.tight_layout()
    out = RUN11 / "fig_road_type_distribution.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


# ══════════════════════════════════════════════════════════════════════════════
# 2.  Intersection density
# ══════════════════════════════════════════════════════════════════════════════

def _intersection_chart() -> None:
    inter = json.loads((DGR / "gap_whole_intersection.json").read_text())
    types = sorted(set(inter["auto"]) | set(inter["manual"]))

    auto_v  = [inter["auto"].get(t, 0)   for t in types]
    man_v   = [inter["manual"].get(t, 0) for t in types]

    auto_total = sum(auto_v)
    man_total  = sum(man_v)
    ratio      = auto_total / man_total if man_total else float("inf")

    x = np.arange(len(types))
    w = 0.35
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - w/2, auto_v, w, label=f"Auto  (total {auto_total})", color="#2196F3", alpha=0.85)
    ax.bar(x + w/2, man_v,  w, label=f"Manual (total {man_total})", color="#FF9800", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels([t.replace("_", " ").capitalize() for t in types], rotation=20, ha="right")
    ax.set_ylabel("Junction count")
    ax.set_title(
        f"Intersection Density: Auto vs Manual\n"
        f"Auto total: {auto_total}  |  Manual total: {man_total}  |  Ratio: {ratio:.1f}×\n"
        f"Normalized gap: {inter['normalized_gap']:.4f}",
        fontsize=11
    )
    ax.legend()

    for bars, vals in [(ax.patches[:len(types)], auto_v),
                       (ax.patches[len(types):], man_v)]:
        for bar, v in zip(bars, vals):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width()/2,
                        bar.get_height() + 1, str(v),
                        ha="center", va="bottom", fontsize=8)

    plt.tight_layout()
    out = RUN11 / "fig_intersection_density.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")

    return auto_total, man_total, ratio


# ══════════════════════════════════════════════════════════════════════════════
# 3.  Semantic depletion table
# ══════════════════════════════════════════════════════════════════════════════

def _semantic_depletion_chart() -> None:
    sem = json.loads((DGR / "gap_whole_semantics.json").read_text())
    objs = sem["objects"]

    all_classes = sorted(set(objs["auto"]) | set(objs["manual"]))
    # exclude "none" placeholder
    classes = [c for c in all_classes if c != "none"]

    auto_v  = [objs["auto"].get(c, 0)   for c in classes]
    man_v   = [objs["manual"].get(c, 0) for c in classes]
    delta_v = [objs["delta"].get(c, 0)  for c in classes]

    # gap factor: manual / max(auto,1)  →  > 1 means manual has more
    gap_factors = [m / max(a, 1) for a, m in zip(auto_v, man_v)]

    # ── table figure ─────────────────────────────────────────────────────────
    table_data = []
    for c, a, m, d, gf in zip(classes, auto_v, man_v, delta_v, gap_factors):
        sign = "+" if d >= 0 else ""
        gf_str = f"{gf:.1f}x" if a == 0 and m > 0 else f"{gf:.2f}x"
        table_data.append([c.replace("_", " ").capitalize(), str(a), str(m), f"{sign}{d}", gf_str])

    col_labels = ["Object class", "Auto", "Manual", "Delta (auto-manual)", "Gap factor"]
    n_rows = len(table_data)
    fig, ax = plt.subplots(figsize=(10, n_rows * 0.42 + 1.8))
    ax.axis("off")

    tbl = ax.table(
        cellText=table_data,
        colLabels=col_labels,
        loc="upper center",
        cellLoc="center",
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    tbl.auto_set_column_width([0, 1, 2, 3, 4])

    # colour rows where auto is severely depleted
    for i, (a, m) in enumerate(zip(auto_v, man_v)):
        if a == 0 and m > 0:
            for j in range(5):
                tbl[i + 1, j].set_facecolor("#FFCCCC")   # red: completely absent in auto
        elif m > 0 and a / m < 0.2:
            for j in range(5):
                tbl[i + 1, j].set_facecolor("#FFF3CD")   # yellow: severely depleted

    # header row styling
    for j in range(5):
        tbl[0, j].set_facecolor("#DDDDDD")
        tbl[0, j].set_text_props(fontweight="bold")

    ax.set_title(
        "Semantic Object Depletion: Auto-Generated vs Manual Map\n"
        "Red = class absent in auto map   |   Gap factor = manual / auto",
        fontsize=11, pad=6
    )
    out = RUN11 / "fig_semantic_depletion.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")

    # ── bar chart ─────────────────────────────────────────────────────────────
    fig2, ax2 = plt.subplots(figsize=(11, 5))
    x = np.arange(len(classes))
    w = 0.35
    ax2.bar(x - w/2, auto_v, w, label="Auto (OSM→XODR)", color="#2196F3", alpha=0.85)
    ax2.bar(x + w/2, man_v,  w, label="Manual (reference)", color="#FF9800", alpha=0.85)
    ax2.set_xticks(x)
    ax2.set_xticklabels([c.replace("_", " ").capitalize() for c in classes], rotation=25, ha="right")
    ax2.set_ylabel("Object count")
    ax2.set_yscale("symlog", linthresh=10)
    ax2.set_title("Semantic Object Count per Class (log scale)", fontsize=11)
    ax2.legend()
    plt.tight_layout()
    out2 = RUN11 / "fig_semantic_depletion_bars.png"
    fig2.savefig(out2, dpi=150, bbox_inches="tight")
    plt.close(fig2)
    print(f"Saved: {out2}")

    # ── CSV ──────────────────────────────────────────────────────────────────
    csv_path = RUN11 / "gap_summary_table.csv"
    lines = ["object_class,auto_count,manual_count,delta,gap_factor"]
    for row in table_data:
        lines.append(",".join(row))
    csv_path.write_text("\n".join(lines) + "\n")
    print(f"Saved: {csv_path}")


# ══════════════════════════════════════════════════════════════════════════════
# 4.  Patch full_report.json — fix misleading ICP label
# ══════════════════════════════════════════════════════════════════════════════

def _patch_full_report() -> None:
    rpt_path = RUN11 / "full_report.json"
    rpt = json.loads(rpt_path.read_text())

    old_method = rpt.get("method", "")
    new_method = old_method.replace(
        " + ICP refinement",
        " [note: icp_iters loop ran but did not converge — final alignment is initial SVD rigid pass]"
    )
    if new_method == old_method:
        # fallback replacement if exact string not present
        new_method = (
            "explicit auto CRS reprojection + rigid SE(2) alignment (scale fixed to 1, single SVD pass) "
            "+ paramPoly3-aware geometry sampling + matched-subset RMSE"
        )

    rpt["method"] = new_method
    rpt["alignment_method_note"] = (
        "Alignment is a single rigid SVD pass (rotation + translation, scale=1.0 fixed). "
        "icp_iters_run=20 is reported but the icp_rmse_history shows monotonically worsening RMSE "
        "(2060→2067 m), indicating the ICP loop did not improve alignment. "
        "Thesis text should describe this as 'SVD rigid registration', not 'ICP'."
    )

    # ensure diagnostics note is present
    if "diagnostics" in rpt.get("alignment", {}):
        rpt["alignment"]["diagnostics"]["icp_note"] = (
            "icp_rmse_history is monotonically increasing — no convergence. "
            "The rigid SVD initial alignment (rmse_after_initial_rigid) is the operative result."
        )

    rpt_path.write_text(json.dumps(rpt, indent=2))
    print(f"Patched: {rpt_path}")


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== Generating thesis domain-gap figures ===\n")

    _road_type_chart()

    auto_j, man_j, ratio_j = _intersection_chart()
    print(f"  Intersection totals — auto: {auto_j}, manual: {man_j}, ratio: {ratio_j:.1f}×")

    _semantic_depletion_chart()

    _patch_full_report()

    print("\n=== Done ===")
    print("Figures written to:", RUN11)
