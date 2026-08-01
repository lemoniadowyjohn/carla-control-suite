#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the thesis curvature distribution comparison figure.

This script rebuilds the Chapter 7 curvature comparison figure from the
authoritative structural comparison pair:
    - cities/ingolstadt/manual_grid0828.xodr
    - artifacts/final_runs/scenario_b_audit/contract_run/08_final_structural_gap.xodr

It uses the corrected paramPoly3-aware curvature extraction already present in
ultimate_pipeline.domain_gap.curvature_gap and exports a deterministic PNG that
renders publication-safe math notation in the thesis PDF.
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.domain_gap.curvature_gap import CurvatureGap, _extract_curvatures


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANUAL = REPO_ROOT / "cities" / "ingolstadt" / "manual_grid0828.xodr"
DEFAULT_AUTO = (
    REPO_ROOT
    / "artifacts"
    / "final_runs"
    / "scenario_b_audit"
    / "contract_run"
    / "08_final_structural_gap.xodr"
)
DEFAULT_OUT = (
    REPO_ROOT
    / "THI_thesis_source_tree_regenerated"
    / "THI_thesis_ultimate_working_v15"
    / "images"
    / "fig_curvature_distribution_comparison.png"
)


def _load_curvature_values(xodr_path: Path) -> np.ndarray:
    root = ET.parse(xodr_path).getroot()
    values = _extract_curvatures(
        root,
        include_lines=bool(getattr(SETTINGS, "CURVATURE_INCLUDE_LINES", True)),
        max_geoms=getattr(SETTINGS, "CURVATURE_MAX_GEOMS", None),
    )
    if not values:
        raise RuntimeError(f"No curvature samples extracted from {xodr_path}")
    return np.asarray(values, dtype=float)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual-xodr", type=Path, default=DEFAULT_MANUAL)
    parser.add_argument("--auto-xodr", type=Path, default=DEFAULT_AUTO)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    manual_xodr = args.manual_xodr.resolve()
    auto_xodr = args.auto_xodr.resolve()
    out_path = args.out.resolve()

    if not manual_xodr.is_file():
        raise FileNotFoundError(f"Manual XODR not found: {manual_xodr}")
    if not auto_xodr.is_file():
        raise FileNotFoundError(f"Auto XODR not found: {auto_xodr}")

    manual_vals = _load_curvature_values(manual_xodr)
    auto_vals = _load_curvature_values(auto_xodr)
    metrics = CurvatureGap.compute(str(manual_xodr), str(auto_xodr))
    if metrics.get("disabled"):
        raise RuntimeError(f"Curvature metric disabled: {metrics}")

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 12,
            "axes.titlesize": 15,
            "axes.labelsize": 13,
            "legend.fontsize": 12,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "mathtext.fontset": "dejavusans",
        }
    )

    fig, axes = plt.subplots(1, 2, figsize=(11.4, 5.7))
    fig.suptitle(
        "Curvature distributions: authoritative Ingolstadt pair",
        fontsize=16,
        y=0.98,
    )

    manual_color = "#1f77b4"
    auto_color = "#d62728"
    bulk_bins = np.linspace(0.0, 0.6, 60)
    tail_bins = np.linspace(0.0, 3.0, 90)
    xlabel = r"Absolute curvature $|\kappa|$ [$\mathrm{m}^{-1}$]"

    ax_bulk, ax_tail = axes
    for values, color, label in (
        (manual_vals, manual_color, "Manual reference"),
        (auto_vals, auto_color, "Auto map"),
    ):
        ax_bulk.hist(
            values,
            bins=bulk_bins,
            density=True,
            histtype="step",
            linewidth=2.0,
            color=color,
            label=label,
        )
        ax_tail.hist(
            values,
            bins=tail_bins,
            density=True,
            histtype="step",
            linewidth=2.0,
            color=color,
            label=label,
            log=True,
        )

    ax_bulk.set_title("Bulk near-straight regime")
    ax_bulk.set_xlabel(xlabel)
    ax_bulk.set_ylabel("Density")
    ax_bulk.set_xlim(0.0, 0.6)
    ax_bulk.grid(True, alpha=0.22)
    ax_bulk.legend(loc="upper right", frameon=False)

    ax_tail.set_title("Tail visibility (log-density scale)")
    ax_tail.set_xlabel(xlabel)
    ax_tail.set_ylabel("Density (log)")
    ax_tail.set_xlim(0.0, 3.0)
    ax_tail.grid(True, which="both", alpha=0.22)

    info_text = "\n".join(
        [
            "Corrected authoritative pair",
            rf"$\mathrm{{KL}} = {metrics['kl_divergence']:.5f}$",
            rf"$\sigma_{{\mathrm{{manual}}}} = {metrics['std_manual']:.3f}\,\mathrm{{m}}^{{-1}}$",
            rf"$\sigma_{{\mathrm{{auto}}}} = {metrics['std_auto']:.3f}\,\mathrm{{m}}^{{-1}}$",
        ]
    )
    ax_tail.text(
        0.98,
        0.98,
        info_text,
        transform=ax_tail.transAxes,
        ha="right",
        va="top",
        fontsize=12,
        bbox={
            "boxstyle": "round,pad=0.35",
            "facecolor": "white",
            "edgecolor": "#999999",
            "alpha": 0.95,
        },
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(pad=1.0, rect=(0.0, 0.0, 1.0, 0.93))
    fig.savefig(out_path, dpi=300, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    print(f"[curvature_figure] wrote {out_path}")
    print(
        "[curvature_figure] "
        f"kl={metrics['kl_divergence']:.5f} "
        f"std_manual={metrics['std_manual']:.3f} "
        f"std_auto={metrics['std_auto']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
