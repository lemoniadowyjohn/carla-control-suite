#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
run_alignment_and_matching.py

Standalone alignment + optional visualization using pipeline SETTINGS.

Robust to SETTINGS drift:
- If SETTINGS.AUTO_MAP_XODR doesn't exist, auto-detect the latest 08_final*.xodr
  under the latest run output directory.
- If plots are unavailable/disabled, it still writes alignment_debug.json.
- Tile matching is optional and will never crash this tool.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.domain_gap.geo_alignment import GeoAligner
from ultimate_pipeline.tools.artifact_locator import _repaired_sibling_exists


def _run_dir_has_completed_output(run_dir: str) -> bool:
    """Structural guard for _safe_latest_output_dir: does this candidate run
    directory contain evidence of a *completed* pipeline run (a written
    08_final*.xodr), rather than being an empty/partial/stale directory that
    merely happens to carry a newer mtime?

    This is a content-shape check, independent of filesystem mtime -- a
    directory touched by an unrelated process, a clock-skewed restore, or a
    leftover empty/aborted run folder cannot win selection purely by having
    the newest mtime unless it also has real completed-run evidence backing
    it up. Mirrors the structural-guard-before-mtime convention established
    in ultimate_pipeline/tools/artifact_locator.py::_newest_final_xodr
    (_repaired_sibling_exists).
    """
    try:
        return any(Path(run_dir).glob("08_final*.xodr"))
    except Exception:
        return False


def _safe_latest_output_dir() -> Optional[str]:
    """Best-effort latest output directory without creating a new run folder."""
    try:
        d = SETTINGS.latest_output_dir()
        if d and os.path.isdir(d):
            return d
    except Exception:
        pass

    # Fallback: scan BASE_OUTPUT_DIR
    base = getattr(SETTINGS, "BASE_OUTPUT_DIR", "")
    if base and os.path.isdir(base):
        try:
            run_dirs = [os.path.join(base, d) for d in os.listdir(base)]
            run_dirs = [d for d in run_dirs if os.path.isdir(d)]
            if not run_dirs:
                return None
            # Structural guard: prefer directories with real completed-run
            # evidence (see _run_dir_has_completed_output) over raw mtime
            # ordering. mtime is then only a tie-breaker among directories
            # that are equally legitimate by that structural check (or when
            # no candidate has completed-run evidence at all).
            completed = [d for d in run_dirs if _run_dir_has_completed_output(d)]
            pool = completed or run_dirs
            pool.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            return pool[0]
        except Exception:
            return None
    return None


def _find_latest_final_xodr(out_dir: str) -> Optional[str]:
    """Find newest 08_final*.xodr (prefer semantic) within a given run output directory."""
    try:
        p = Path(out_dir)
        if not p.is_dir():
            return None

        # Prefer semantic final if present
        candidates = list(p.glob("08_final*_semantic.xodr"))
        candidates += list(p.glob("08_final*.xodr"))

        if not candidates:
            # fallback: any .xodr in run dir
            candidates = list(p.glob("*.xodr"))

        if not candidates:
            return None

        # Structural guard (matches ultimate_pipeline/tools/artifact_locator.py's
        # _newest_final_xodr convention): prefer candidates that are
        # structurally verified post-repair -- a same-run
        # *_laneSectionFixed*.xodr sibling exists on disk -- before trusting
        # mtime at all. This does not depend on filesystem mtime, so a stale
        # or adversarially-touched file cannot win purely by having a newer
        # mtime without also having the repair artifacts to back it up.
        # mtime is then used only as the tie-breaker among files that are
        # equally legitimate by that structural check (or when no candidate
        # has repair evidence, e.g. ENABLE_LANE_SECTION_REPAIR=0 runs).
        repaired = [c for c in candidates if _repaired_sibling_exists(c)]
        pool = repaired or candidates
        pool.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return str(pool[0])
    except Exception:
        return None


def _resolve_auto_xodr() -> str:
    """Resolve which 'auto' XODR to align against the manual reference."""
    # 1) Env override wins
    env = os.getenv("UP_AUTO_XODR", "").strip()
    if env and os.path.exists(env):
        return env

    # 2) If settings defines AUTO_MAP_XODR, use it (if exists)
    auto_attr = getattr(SETTINGS, "AUTO_MAP_XODR", None)
    if isinstance(auto_attr, str) and auto_attr and os.path.exists(auto_attr):
        return auto_attr

    # 3) Use latest run output dir and pick newest 08_final*.xodr
    out_dir = _safe_latest_output_dir()
    if out_dir:
        latest = _find_latest_final_xodr(out_dir)
        if latest and os.path.exists(latest):
            return latest

    # 4) Last resort: SETTINGS.INPUT_XODR (exists for most configs)
    fallback = getattr(SETTINGS, "INPUT_XODR", "")
    if fallback and os.path.exists(fallback):
        return fallback

    raise RuntimeError(
        "Could not resolve auto XODR. Set UP_AUTO_XODR to an existing .xodr file "
        "or run the pipeline once to create an 08_final*.xodr under ultimate_pipeline_out."
    )


def run_alignment_debug() -> None:
    # ------------------------------------------------------------
    # Resolve paths from SETTINGS
    # ------------------------------------------------------------
    manual_xodr = getattr(SETTINGS, "MANUAL_MAP_XODR", "")
    if not manual_xodr or not os.path.exists(manual_xodr):
        raise RuntimeError(f"MANUAL_MAP_XODR not set or does not exist: {manual_xodr}")

    auto_xodr = _resolve_auto_xodr()
    if not auto_xodr or not os.path.exists(auto_xodr):
        raise RuntimeError(f"Auto XODR not found: {auto_xodr}")

    out_dir = _safe_latest_output_dir()
    if not out_dir:
        # Keep outputs next to auto_xodr if no run dir exists
        out_dir = str(Path(auto_xodr).resolve().parent)

    # Where to drop alignment artifacts
    domain_gap_dir = os.path.join(out_dir, getattr(SETTINGS, "DOMAIN_GAP_OUT_DIR", "domain_gap"))
    os.makedirs(domain_gap_dir, exist_ok=True)

    fig_dir = os.path.join(out_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    aligned_auto_out = os.path.join(domain_gap_dir, "auto_aligned.xodr")

    # ------------------------------------------------------------
    # 1) Estimate alignment
    # ------------------------------------------------------------
    print("\n🔧 Estimating GeoAlignment (manual ← auto)")
    transform_bundle = GeoAligner.estimate_from_xodr(
        manual_xodr=manual_xodr,
        auto_xodr=auto_xodr,
        max_points=int(getattr(SETTINGS, "ALIGN_MAX_POINTS", 2000) or 2000),
        out_dir=domain_gap_dir,
        strict=True,  # fail loudly if correspondences can't be extracted
    )

    print("Estimated transform:")
    for k, v in transform_bundle.items():
        print(f"  {k}: {v}")

    # ------------------------------------------------------------
    # 2) Apply transform
    # ------------------------------------------------------------
    GeoAligner.apply_to_xodr(
        in_xodr=auto_xodr,
        out_xodr=aligned_auto_out,
        transform=transform_bundle,
    )
    print(f"✓ Aligned auto map written → {aligned_auto_out}")

    # ------------------------------------------------------------
    # 3) Visual comparison (optional)
    # ------------------------------------------------------------
    if getattr(SETTINGS, "ENABLE_DOMAIN_GAP_PLOTS", True):
        try:
            from ultimate_pipeline.visualization.map_diff import overlay_maps

            print("\n🖼 Generating overlay visualization…")
            overlay_maps(
                manual_xodr,
                aligned_auto_out,
                label_a="Manual map",
                label_b="Auto map (aligned)",
                out_png=os.path.join(fig_dir, "manual_vs_auto_overlay.png"),
            )
        except Exception as e:
            print(f"⚠ Visualization skipped: {e}")
    else:
        print("⚠ Visualization disabled via SETTINGS")

    # ------------------------------------------------------------
    # 4) Tile matching (optional; never crash)
    # ------------------------------------------------------------
    try:
        from ultimate_pipeline.domain_gap.tile_matcher import TileMatcher

        manual_tiles = getattr(SETTINGS, "MANUAL_TILES_DIR", None)
        auto_tiles = os.path.join(out_dir, "tiles")  # pipeline outputs tiles under run dir

        if manual_tiles and os.path.isdir(manual_tiles) and os.path.isdir(auto_tiles):
            print("\n🗂 Matching tiles…")
            matches = TileMatcher.match(
                manual_dir=manual_tiles,
                auto_dir=auto_tiles,
            )
            if matches is None:
                # Some older TileMatcher implementations return None instead of [].
                print("⚠ TileMatcher returned None (treating as 0 matches).")
            else:
                try:
                    print(f"✓ Matched {len(matches)} tiles")
                except Exception:
                    print("✓ Tile matching completed (non-sized result).")
        else:
            print("⚠ Tile matching skipped (tiles not configured)")
    except Exception as e:
        print(f"⚠ Tile matching skipped: {e}")


if __name__ == "__main__":
    run_alignment_debug()
