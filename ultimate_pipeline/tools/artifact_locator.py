#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared artifact locator helpers (OSM/XODR/run dir).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple


def output_root_from_settings() -> Path:
    try:
        from ultimate_pipeline.config.settings import SETTINGS

        return Path(getattr(SETTINGS, "PIPELINE_OUTPUT_ROOT", "ultimate_pipeline_out"))
    except Exception:
        return Path("ultimate_pipeline_out")


def resolve_run_dir(
    run_dir_arg: Optional[str],
    *,
    env_var: str = "UP_HEALTH_RUN_DIR",
    output_root: Optional[Path] = None,
) -> Path:
    env = os.environ.get(env_var, "").strip()
    if env:
        return Path(env)
    if run_dir_arg:
        return Path(run_dir_arg)
    root = output_root or output_root_from_settings()
    if root.exists():
        candidates = [p for p in root.iterdir() if p.is_dir()]
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]
    return Path(".")


def find_osm_artifact(run_dir: Path) -> Tuple[Optional[Path], str]:
    candidates = [
        run_dir / "osm" / "extract.osm",
        run_dir / "osm" / "extract.osm.pbf",
        run_dir / "osm_extract.osm",
        run_dir / "osm_extract.osm.pbf",
        run_dir / "artifacts" / "osm_extract.osm",
        run_dir / "artifacts" / "osm_extract.osm.pbf",
    ]
    for p in candidates:
        if p.exists():
            return p, "run_dir"
    osm_files = sorted(run_dir.rglob("*.osm")) + sorted(run_dir.rglob("*.osm.pbf"))
    if osm_files:
        osm_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return osm_files[0], "run_dir_glob"
    return None, "not_found"


def _newest_final_xodr(run_dir: Path) -> Optional[Path]:
    """Pick the authoritative final XODR among any 08_final*.xodr variants.

    A real pipeline run writes several 08_final*.xodr files in sequence:
    the plain 08_final_<ts>.xodr (pre-repair), then 08_final_<ts>_semantic.xodr
    (a copy), then 08_final_<ts>_laneSectionFixed.xodr (the repaired map --
    "AUTHORITATIVE MAP SWITCH" per stage_08_integrity.py), and finally
    08_final_<ts>_semantic.xodr is re-copied from the repaired file. Naive
    lexicographic sorting (plain sorted(glob(...))) picks the plain
    pre-repair file first ("." < "_" in ASCII) -- the exact file the
    laneSection-successor repair exists to supersede, since loading it can
    trip CARLA's MapBuilder.cpp asserts. Prefer the semantic variant
    (mtime-newest, matching the already-established convention in
    export_thesis_tables.py::_latest_final_xodr), falling back to the
    mtime-newest 08_final*.xodr of any kind.
    """
    semantic = sorted(
        run_dir.glob("08_final*_semantic.xodr"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if semantic:
        return semantic[0]
    any_final = sorted(
        run_dir.glob("08_final*.xodr"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return any_final[0] if any_final else None


def find_xodr_artifact(run_dir: Path) -> Tuple[Optional[Path], str]:
    tile = run_dir / "tiles" / "tile_0_0.xodr"
    if tile.exists():
        return tile, "run_dir"
    final = _newest_final_xodr(run_dir)
    if final is not None:
        return final, "run_dir"
    candidates = sorted(run_dir.rglob("*.xodr"))
    for p in candidates:
        if p.exists():
            return p, "run_dir"
    return None, "not_found"


def find_final_xodr(run_dir: Path) -> Tuple[Optional[Path], str]:
    final = _newest_final_xodr(run_dir)
    if final is not None:
        return final, "08_final"
    return find_xodr_artifact(run_dir)
