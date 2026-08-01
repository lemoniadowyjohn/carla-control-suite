from __future__ import annotations

"""Lightweight perception metrics from a recording directory.

This intentionally avoids heavy dependencies and CARLA imports.
It is used to:
- validate that capture produced real data (>=min frames)
- export metrics JSON consumed by domain-gap orchestration

What it measures (stable & thesis-friendly):
- counts of RGB frames (png/jpg/jpeg)
- counts of semantic frames (png)
- counts of LiDAR frames (ply/bin/pcd/npz)
- basic folder inventory
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


IMG_EXTS = (".png", ".jpg", ".jpeg")
LIDAR_EXTS = (".ply", ".pcd", ".bin", ".npz")


def _count_files(root: Path, exts: Tuple[str, ...]) -> int:
    n = 0
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            n += 1
    return n


def _count_semantic_pngs(root: Path) -> int:
    # heuristic: semantic images are typically in a folder containing "seg" or "semantic"
    n = 0
    for p in root.rglob("*.png"):
        s = str(p).lower()
        if "seg" in s or "semantic" in s:
            n += 1
    return n


def compute_metrics(recording_dir: str | Path) -> Dict:
    rdir = Path(recording_dir)
    metrics = {
        "recording_dir": str(rdir),
        "exists": rdir.exists(),
        "rgb_frames": 0,
        "semantic_frames": 0,
        "lidar_frames": 0,
        "total_images": 0,
        "folders": [],
    }
    if not rdir.exists():
        return metrics

    metrics["total_images"] = _count_files(rdir, IMG_EXTS)
    metrics["rgb_frames"] = metrics["total_images"]  # conservative default
    metrics["semantic_frames"] = _count_semantic_pngs(rdir)
    metrics["lidar_frames"] = _count_files(rdir, LIDAR_EXTS)

    # folder inventory (depth 2)
    try:
        folders = []
        for p in sorted(rdir.glob("**/*")):
            if p.is_dir():
                rel = str(p.relative_to(rdir)).replace("\\", "/")
                if rel.count("/") <= 2:
                    folders.append(rel)
        metrics["folders"] = folders[:200]
    except Exception:
        pass

    return metrics


def validate_recording(
    metrics: Dict,
    *,
    min_rgb: int = 1,
    min_lidar: int = 0,
    require_rgb: bool = True,
    require_lidar: bool = False,
) -> Dict:
    """Return a validation report with ok flag and reasons."""
    reasons: List[str] = []
    ok = True

    if not metrics.get("exists", False):
        ok = False
        reasons.append("recording_dir_missing")

    rgb = int(metrics.get("rgb_frames", 0) or 0)
    lidar = int(metrics.get("lidar_frames", 0) or 0)

    if require_rgb and rgb < int(min_rgb):
        ok = False
        reasons.append(f"rgb_frames<{min_rgb} (got {rgb})")

    if require_lidar and lidar < int(min_lidar):
        ok = False
        reasons.append(f"lidar_frames<{min_lidar} (got {lidar})")

    return {"ok": ok, "reasons": reasons, "rgb_frames": rgb, "lidar_frames": lidar}
