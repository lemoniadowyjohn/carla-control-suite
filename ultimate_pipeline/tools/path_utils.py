#!/usr/bin/env python3
"""
Path helpers for ultimate_pipeline.
ASCII-only, no subprocess dependencies.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List, Optional


def repo_root(start: Optional[Path] = None) -> Path:
    """Walk upward until pyproject.toml, .git, or ultimate_pipeline/ is found."""
    p = (start or Path(__file__).resolve()).parent
    for _ in range(20):
        if (p / "pyproject.toml").is_file() or (p / ".git").exists() or (p / "ultimate_pipeline").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    return p


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def norm_path_str(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def resolve_latest_run(out_dir: str | Path, skip_names: Optional[List[str]] = None) -> Path:
    """Return newest run dir containing tile_metadata.json and tiles/ or 08_final*.xodr."""
    skip = {s.lower() for s in (skip_names or [])}
    base = Path(out_dir)
    if not base.is_dir():
        raise FileNotFoundError(f"Output root not found: {base}")

    best: tuple[float, Path] | None = None
    candidates: List[str] = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        if child.name.lower() in skip:
            continue
        candidates.append(child.name)
        meta = child / "tile_metadata.json"
        tiles_dir = child / "tiles"
        finals = list(child.glob("08_final*.xodr"))
        has_tiles = tiles_dir.is_dir() and any(tiles_dir.glob("tile_*.xodr"))
        if not (meta.is_file() and (has_tiles or finals)):
            continue
        ts = max(meta.stat().st_mtime, tiles_dir.stat().st_mtime if tiles_dir.exists() else 0, child.stat().st_mtime)
        if best is None or ts > best[0]:
            best = (ts, child)

    if best:
        return best[1]

    raise RuntimeError(f"No valid run found under {base}. Candidates seen: {', '.join(sorted(candidates))}")


def timestamp_dirname(prefix: str = "") -> str:
    return prefix + time.strftime("%Y%m%d_%H%M%S")
