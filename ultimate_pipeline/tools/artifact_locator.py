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


def find_xodr_artifact(run_dir: Path) -> Tuple[Optional[Path], str]:
    candidates = [run_dir / "tiles" / "tile_0_0.xodr"]
    candidates += sorted(run_dir.glob("08_final*.xodr"))
    candidates += sorted(run_dir.rglob("*.xodr"))
    for p in candidates:
        if p.exists():
            return p, "run_dir"
    return None, "not_found"


def find_final_xodr(run_dir: Path) -> Tuple[Optional[Path], str]:
    candidates = sorted(run_dir.glob("08_final*.xodr"))
    if candidates:
        return candidates[0], "08_final"
    return find_xodr_artifact(run_dir)
