#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Best-effort perception metrics for lightweight paired analysis.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, List


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2 == 1:
        return float(values[mid])
    return float((values[mid - 1] + values[mid]) / 2.0)


def _extract_timestamp_from_name(name: str) -> Optional[int]:
    parts = re.findall(r"\d+", name)
    if not parts:
        return None
    try:
        return int(parts[-1])
    except Exception:
        return None


def _read_ply_point_count(path: Path) -> Optional[int]:
    try:
        with path.open("rb") as f:
            header = []
            while True:
                line = f.readline()
                if not line:
                    break
                header.append(line.decode("utf-8", errors="ignore").strip())
                if line.strip() == b"end_header":
                    break
        for line in header:
            if line.startswith("element vertex"):
                parts = line.split()
                if len(parts) >= 3:
                    return int(parts[2])
    except Exception:
        return None
    return None


def _read_bin_point_count(path: Path) -> Optional[int]:
    try:
        size = path.stat().st_size
        if size <= 0:
            return None
        stride = 4 * 4
        if size % stride != 0:
            return None
        return int(size // stride)
    except Exception:
        return None


def compute_perception_metrics(run_dir: str) -> Dict[str, Any]:
    """
    Best-effort: compute simple metrics from captured sensors.
    Returns dict with camera + lidar counts, image resolution, basic intensity stats,
    lidar point count stats, time span.
    Never raises; returns {"enabled": False, "reason": ...} if no data found.
    """
    try:
        root = Path(run_dir)
    except Exception:
        return {"enabled": False, "reason": "invalid_run_dir"}

    if not root.exists():
        return {"enabled": False, "reason": "run_dir_missing"}

    camera_counts: Dict[str, int] = {}
    camera_first_image: Dict[str, Path] = {}
    timestamps: List[int] = []
    lidar_points: List[int] = []
    lidar_frames = 0

    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            lower = fn.lower()
            path = Path(dirpath) / fn
            ts = _extract_timestamp_from_name(path.stem)
            if ts is not None:
                timestamps.append(ts)

            if lower.endswith((".png", ".jpg", ".jpeg")):
                cam_name = path.parent.name if path.parent != root else "root"
                camera_counts[cam_name] = camera_counts.get(cam_name, 0) + 1
                if cam_name not in camera_first_image:
                    camera_first_image[cam_name] = path
            elif lower.endswith(".ply"):
                lidar_frames += 1
                count = _read_ply_point_count(path)
                if count is not None:
                    lidar_points.append(count)
            elif lower.endswith(".bin"):
                lidar_frames += 1
                count = _read_bin_point_count(path)
                if count is not None:
                    lidar_points.append(count)

    if not camera_counts and lidar_frames == 0:
        return {"enabled": False, "reason": "no_sensor_data_found"}

    resolution = None
    mean_intensity: Dict[str, Optional[float]] = {}
    try:
        from PIL import Image, ImageStat

        for cam_name, img_path in camera_first_image.items():
            try:
                with Image.open(img_path) as img:
                    if resolution is None:
                        resolution = {"width": int(img.width), "height": int(img.height)}
                    stat = ImageStat.Stat(img.convert("L"))
                    if stat.mean:
                        mean_intensity[cam_name] = float(stat.mean[0])
            except Exception:
                mean_intensity[cam_name] = None
    except Exception:
        mean_intensity = {}

    time_span = None
    if timestamps:
        start = min(timestamps)
        end = max(timestamps)
        time_span = {"start": start, "end": end, "duration": end - start}

    return {
        "enabled": True,
        "camera": {
            "counts": camera_counts,
            "total_frames": int(sum(camera_counts.values())),
            "resolution": resolution,
            "mean_intensity": mean_intensity,
        },
        "lidar": {
            "frames": int(lidar_frames),
            "point_counts": {
                "min": min(lidar_points) if lidar_points else None,
                "max": max(lidar_points) if lidar_points else None,
                "median": _median(lidar_points),
            },
        },
        "time_span": time_span,
    }
