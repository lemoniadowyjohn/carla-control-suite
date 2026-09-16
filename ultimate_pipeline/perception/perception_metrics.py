#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Best-effort perception metrics for lightweight paired analysis.
"""

from __future__ import annotations

import math
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


# =============================================================================
# Paired-capture comparison (RQ3: generated map vs. Town10HD control)
# =============================================================================
#
# See submission/results/perception_rq3_bounded/paired_metrics.json and
# capture_attempt_log.txt (2026-05-14): the one real paired-capture attempt on
# record used mismatched configs for its two sides (20 frames/1 camera vs.
# 8 frames/6 cameras), so every pixel-level metric (kl_divergence,
# histogram_intersection, mean_brightness_difference, per_channel_kl) came
# back `null` -- the comparison was structurally impossible to compute.
#
# `compute_paired_perception_metrics()` is the single place that reads two
# capture output directories and produces a paired comparison. It calls
# `assert_paired_captures_compatible()` FIRST and raises
# `PairedCaptureMismatchError` if the two datasets aren't directly
# comparable, instead of silently emitting nulls like the 2026-05-14 run did.


class PairedCaptureMismatchError(ValueError):
    """Raised when two capture datasets are not directly comparable.

    A paired RQ3 comparison requires matching camera sets AND matching
    per-camera frame counts on both sides; otherwise pixel-level metrics
    (KL-divergence, histogram intersection, ...) cannot be computed at all,
    which is exactly the failure recorded in
    submission/results/perception_rq3_bounded/paired_metrics.json
    (2026-05-14: generated map 20 frames/1 camera vs. Town10HD 8 frames/6
    cameras -> every metric came back null).
    """


def _capture_signature(metrics: Dict[str, Any]) -> Dict[str, Any]:
    camera = metrics.get("camera") or {}
    counts = dict(camera.get("counts") or {})
    return {
        "camera_names": sorted(counts.keys()),
        "camera_count": len(counts),
        "frames_per_camera": counts,
    }


def assert_paired_captures_compatible(
    metrics_a: Dict[str, Any],
    metrics_b: Dict[str, Any],
    *,
    label_a: str = "capture_a",
    label_b: str = "capture_b",
) -> None:
    """Fail fast unless two capture datasets have matching camera configs.

    `metrics_a`/`metrics_b` are the dicts returned by
    `compute_perception_metrics()`. Raises `PairedCaptureMismatchError` with
    a specific, actionable message (rather than letting downstream code
    silently produce `null` KL-divergence/histogram metrics) when:
      - either capture has no usable sensor data;
      - the set of camera names differs between the two sides;
      - the per-camera frame count differs for any shared camera.
    """
    issues: List[str] = []

    if not metrics_a.get("enabled", False):
        issues.append(f"{label_a}: no usable sensor data ({metrics_a.get('reason', 'unknown')})")
    if not metrics_b.get("enabled", False):
        issues.append(f"{label_b}: no usable sensor data ({metrics_b.get('reason', 'unknown')})")
    if issues:
        raise PairedCaptureMismatchError(
            "Cannot compare paired captures: " + "; ".join(issues)
        )

    sig_a = _capture_signature(metrics_a)
    sig_b = _capture_signature(metrics_b)

    if sig_a["camera_names"] != sig_b["camera_names"]:
        issues.append(
            f"camera set mismatch: {label_a}={sig_a['camera_names']!r} "
            f"vs {label_b}={sig_b['camera_names']!r}"
        )
    else:
        for name in sig_a["camera_names"]:
            frames_a = sig_a["frames_per_camera"].get(name)
            frames_b = sig_b["frames_per_camera"].get(name)
            if frames_a != frames_b:
                issues.append(
                    f"frame count mismatch for camera '{name}': "
                    f"{label_a}={frames_a} vs {label_b}={frames_b}"
                )

    if issues:
        raise PairedCaptureMismatchError(
            "Paired capture datasets are not directly comparable -- refusing to "
            "compute pixel-level metrics (this would silently produce null "
            "kl_divergence/histogram_intersection results, as happened in the "
            "2026-05-14 run; see "
            "submission/results/perception_rq3_bounded/paired_metrics.json). "
            "Issues:\n  - " + "\n  - ".join(issues)
        )


def _channel_histogram_counts(path: Path, bins: int) -> Optional[Dict[str, List[int]]]:
    try:
        import numpy as np
        from PIL import Image

        with Image.open(path) as img:
            arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
        out: Dict[str, List[int]] = {}
        for idx, channel in enumerate(("r", "g", "b")):
            hist, _ = np.histogram(arr[:, :, idx], bins=int(bins), range=(0, 255))
            out[channel] = [int(v) for v in hist]
        return out
    except Exception:
        return None


def _camera_image_paths(root: Path) -> Dict[str, List[Path]]:
    """Collect ALL image paths per camera subdirectory (not just the first).

    Mirrors the camera-name grouping logic in `compute_perception_metrics`,
    but keeps every frame so histograms can be aggregated across the whole
    capture rather than a single sample image.
    """
    paths: Dict[str, List[Path]] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            p = Path(dirpath) / fn
            cam_name = p.parent.name if p.parent != root else "root"
            paths.setdefault(cam_name, []).append(p)
    for names in paths.values():
        names.sort()
    return paths


def _aggregate_channel_histograms(
    paths: List[Path], bins: int
) -> Optional[Dict[str, List[float]]]:
    totals: Dict[str, List[int]] = {"r": [0] * bins, "g": [0] * bins, "b": [0] * bins}
    n_ok = 0
    for p in paths:
        counts = _channel_histogram_counts(p, bins)
        if counts is None:
            continue
        n_ok += 1
        for channel, hist in counts.items():
            for i, v in enumerate(hist):
                totals[channel][i] += v
    if n_ok == 0:
        return None
    normalized: Dict[str, List[float]] = {}
    for channel, hist in totals.items():
        total = float(sum(hist))
        normalized[channel] = [c / total for c in hist] if total > 0 else [0.0] * bins
    return normalized


def _kl_divergence(p: List[float], q: List[float], eps: float = 1e-8) -> float:
    total = 0.0
    for pi, qi in zip(p, q):
        pi = max(float(pi), eps)
        qi = max(float(qi), eps)
        total += pi * math.log(pi / qi)
    return float(total)


def _histogram_intersection(p: List[float], q: List[float]) -> float:
    return float(sum(min(float(a), float(b)) for a, b in zip(p, q)))


def compute_paired_perception_metrics(
    run_dir_a: str,
    run_dir_b: str,
    *,
    label_a: str = "generated_map",
    label_b: str = "town10hd",
    bins: int = 32,
) -> Dict[str, Any]:
    """Compute real pixel-level paired comparison metrics for two captures.

    Raises `PairedCaptureMismatchError` (via `assert_paired_captures_compatible`)
    instead of returning null metrics when the two capture datasets are not
    directly comparable -- see module docstring for the 2026-05-14 incident
    this guards against.

    On success, returns per-channel (R/G/B) KL-divergence and histogram
    intersection over 256-level pixel intensity histograms, aggregated
    across every matched frame of every shared camera, plus a
    per-camera breakdown and the mean brightness difference.
    """
    metrics_a = compute_perception_metrics(run_dir_a)
    metrics_b = compute_perception_metrics(run_dir_b)
    assert_paired_captures_compatible(metrics_a, metrics_b, label_a=label_a, label_b=label_b)

    paths_a = _camera_image_paths(Path(run_dir_a))
    paths_b = _camera_image_paths(Path(run_dir_b))
    shared_cameras = sorted(set(paths_a.keys()) & set(paths_b.keys()))

    per_camera_kl: Dict[str, Dict[str, float]] = {}
    per_camera_histogram_intersection: Dict[str, Dict[str, float]] = {}
    per_camera_brightness_difference: Dict[str, float] = {}

    channel_totals_a: Dict[str, List[float]] = {"r": [0.0] * bins, "g": [0.0] * bins, "b": [0.0] * bins}
    channel_totals_b: Dict[str, List[float]] = {"r": [0.0] * bins, "g": [0.0] * bins, "b": [0.0] * bins}
    cameras_with_data = 0

    mean_intensity_a = (metrics_a.get("camera") or {}).get("mean_intensity") or {}
    mean_intensity_b = (metrics_b.get("camera") or {}).get("mean_intensity") or {}

    for cam in shared_cameras:
        hist_a = _aggregate_channel_histograms(paths_a[cam], bins)
        hist_b = _aggregate_channel_histograms(paths_b[cam], bins)
        if hist_a is None or hist_b is None:
            continue
        cameras_with_data += 1
        per_camera_kl[cam] = {
            ch: _kl_divergence(hist_a[ch], hist_b[ch]) for ch in ("r", "g", "b")
        }
        per_camera_histogram_intersection[cam] = {
            ch: _histogram_intersection(hist_a[ch], hist_b[ch]) for ch in ("r", "g", "b")
        }
        for ch in ("r", "g", "b"):
            for i in range(bins):
                channel_totals_a[ch][i] += hist_a[ch][i]
                channel_totals_b[ch][i] += hist_b[ch][i]

        mean_a = mean_intensity_a.get(cam)
        mean_b = mean_intensity_b.get(cam)
        if mean_a is not None and mean_b is not None:
            per_camera_brightness_difference[cam] = float(mean_a) - float(mean_b)

    if cameras_with_data == 0:
        return {
            "enabled": False,
            "reason": "no_readable_image_pairs",
            "label_a": label_a,
            "label_b": label_b,
        }

    # Re-normalize the pooled (across-camera) histograms before computing the
    # overall per_channel_kl / histogram_intersection summary.
    per_channel_kl: Dict[str, float] = {}
    per_channel_histogram_intersection: Dict[str, float] = {}
    for ch in ("r", "g", "b"):
        total_a = float(sum(channel_totals_a[ch]))
        total_b = float(sum(channel_totals_b[ch]))
        norm_a = [c / total_a for c in channel_totals_a[ch]] if total_a > 0 else [0.0] * bins
        norm_b = [c / total_b for c in channel_totals_b[ch]] if total_b > 0 else [0.0] * bins
        per_channel_kl[ch] = _kl_divergence(norm_a, norm_b)
        per_channel_histogram_intersection[ch] = _histogram_intersection(norm_a, norm_b)

    kl_divergence = float(sum(per_channel_kl.values()) / len(per_channel_kl))
    histogram_intersection = float(
        sum(per_channel_histogram_intersection.values()) / len(per_channel_histogram_intersection)
    )
    mean_brightness_difference = (
        float(sum(per_camera_brightness_difference.values()) / len(per_camera_brightness_difference))
        if per_camera_brightness_difference
        else None
    )

    return {
        "enabled": True,
        "label_a": label_a,
        "label_b": label_b,
        "frames_a": int(metrics_a["camera"]["total_frames"]),
        "frames_b": int(metrics_b["camera"]["total_frames"]),
        "camera_names": shared_cameras,
        "bins": int(bins),
        "kl_divergence": kl_divergence,
        "histogram_intersection": histogram_intersection,
        "mean_brightness_difference": mean_brightness_difference,
        "per_channel_kl": per_channel_kl,
        "per_channel_histogram_intersection": per_channel_histogram_intersection,
        "per_camera_kl": per_camera_kl,
        "per_camera_histogram_intersection": per_camera_histogram_intersection,
        "per_camera_brightness_difference": per_camera_brightness_difference,
    }
