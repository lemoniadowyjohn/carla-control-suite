#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
alignment_debug.py

Standalone alignment + visualization using pipeline SETTINGS.
Safe to run locally, HPC-safe when visualization is disabled.
"""

from __future__ import annotations
import os

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.domain_gap.geo_alignment import GeoAligner
from ultimate_pipeline.domain_gap.tile_matcher import TileMatcher
from ultimate_pipeline.visualization.map_diff import overlay_maps


def run_alignment_debug() -> None:
    # ------------------------------------------------------------
    # Resolve paths from SETTINGS
    # ------------------------------------------------------------
    manual_xodr = SETTINGS.MANUAL_MAP_XODR
    auto_xodr = SETTINGS.AUTO_MAP_XODR or SETTINGS.latest_final_xodr()

    if not manual_xodr or not os.path.exists(manual_xodr):
        raise RuntimeError("MANUAL_MAP_XODR not set or does not exist")

    if not auto_xodr or not os.path.exists(auto_xodr):
        raise RuntimeError("AUTO_MAP_XODR not found")

    out_dir = SETTINGS.latest_output_dir()
    fig_dir = os.path.join(out_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    aligned_auto_out = os.path.join(out_dir, "auto_aligned.xodr")

    # ------------------------------------------------------------
    # 1) Estimate alignment
    # ------------------------------------------------------------
    print("\n🔧 Estimating GeoAlignment (manual ← auto)")
    transform = GeoAligner.estimate_from_xodr(
        manual_xodr=manual_xodr,
        auto_xodr=auto_xodr,
        max_points=getattr(SETTINGS, "ALIGN_MAX_POINTS", 2000),
    )

    print("Estimated transform:")
    for k, v in transform.items():
        if k in ("R", "t"):
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: {v}")

    # ------------------------------------------------------------
    # 2) Apply transform
    # ------------------------------------------------------------
    GeoAligner.apply_to_xodr(
        in_xodr=auto_xodr,
        out_xodr=aligned_auto_out,
        transform=transform,
    )

    print(f"✓ Aligned auto map written → {aligned_auto_out}")

    # ------------------------------------------------------------
    # 3) Visual comparison (guarded)
    # ------------------------------------------------------------
    if getattr(SETTINGS, "ENABLE_DOMAIN_GAP_PLOTS", True):
        print("\n🖼 Generating overlay visualization…")
        overlay_maps(
            manual_xodr,
            aligned_auto_out,
            label_a="Manual map",
            label_b="Auto map (aligned)",
            out_png=os.path.join(fig_dir, "manual_vs_auto_overlay.png"),
        )
    else:
        print("⚠ Visualization disabled via SETTINGS")

    # ------------------------------------------------------------
    # 4) Tile matching (optional)
    # ------------------------------------------------------------
    manual_tiles = getattr(SETTINGS, "MANUAL_TILES_DIR", None)
    auto_tiles = os.path.join(os.path.dirname(auto_xodr), "tiles")

    if manual_tiles and os.path.isdir(manual_tiles) and os.path.isdir(auto_tiles):
        print("\n🗂 Matching tiles…")
        matches = TileMatcher.match(
            manual_dir=manual_tiles,
            auto_dir=auto_tiles,
        )
        print(f"✓ Matched {len(matches)} tiles")
    else:
        print("⚠ Tile matching skipped (tiles not configured)")


if __name__ == "__main__":
    run_alignment_debug()
