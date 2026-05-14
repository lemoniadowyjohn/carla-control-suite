#!/usr/bin/env python3
"""
Task 2: Extract structural features from XODR artifacts for N>=30 GNN retraining.

Stdlib-only feature extraction (ElementTree). No CARLA imports required.
Outputs feature_matrix_n30.json with per-tile structural features.

Source XODR directories searched:
  1. carla_main_governed/thesis_results/structural_gap_v1/run_13/auto_tiles_source/tiles  (auto)
  2. carla_main_governed/thesis_results/structural_gap_v1/run_13/manual_tiles_aligned/tiles (manual)
  3. carla_main_governed/domain_gap_results/auto_tiles_aligned  (auto, up to 20 tiles sampled)
  4. carla_main_governed/work/codex-full-pipeline-rerun-20260427/domain_gap_results/auto_tiles_aligned (auto)
"""

from __future__ import annotations

import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = Path("C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_main_governed")
OUT_DIR = Path("C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/submission/results/gnn_v1_full")
OUT_PATH = OUT_DIR / "feature_matrix_n30.json"

AUTO_DIRS = [
    BASE / "thesis_results/structural_gap_v1/run_13/auto_tiles_source/tiles",
    BASE / "domain_gap_results/auto_tiles_aligned",
    BASE / "work/codex-full-pipeline-rerun-20260427/domain_gap_results/auto_tiles_aligned",
]

MANUAL_DIRS = [
    BASE / "thesis_results/structural_gap_v1/run_13/manual_tiles_aligned/tiles",
    BASE / "thesis_results/structural_gap_v1/run_15_domain_gap/manual_tiles_aligned/tiles",
    BASE / "thesis_results/structural_gap_v1/run_16_post_fix/manual_tiles_aligned/tiles",
]

# Max tiles to sample from each dir to avoid dominating from a single run
MAX_AUTO_PER_DIR = 15
MAX_MANUAL_PER_DIR = 15


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except Exception:
        return default


def extract_features(xodr_path: Path) -> Optional[Dict[str, Any]]:
    """
    Extract structural features from an OpenDRIVE file.
    Returns None if file is invalid or has no roads.
    """
    try:
        raw = xodr_path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        root = ET.fromstring(raw)
    except Exception as exc:
        print(f"  [SKIP] parse error {xodr_path.name}: {exc}", file=sys.stderr)
        return None

    roads = root.findall("road")
    road_count = len(roads)
    if road_count == 0:
        return None

    # junction_count: roads that are connectors inside junctions
    junction_count = sum(
        1 for r in roads if r.get("junction") not in (None, "-1")
    )

    # road lengths
    lengths: List[float] = []
    for r in roads:
        v = _safe_float(r.get("length"), -1.0)
        if v > 0:
            lengths.append(v)

    mean_road_length_m = float(sum(lengths) / len(lengths)) if lengths else 0.0
    if len(lengths) > 1:
        variance = sum((l - mean_road_length_m) ** 2 for l in lengths) / len(lengths)
        std_road_length_m = float(math.sqrt(variance))
    else:
        std_road_length_m = 0.0

    # curvature from arc geometry elements
    curvatures: List[float] = []
    for r in roads:
        for geom in r.findall("./planView/geometry"):
            arc = geom.find("arc")
            if arc is not None:
                c = _safe_float(arc.get("curvature"), 0.0)
                curvatures.append(abs(c))

    mean_curvature = float(sum(curvatures) / len(curvatures)) if curvatures else 0.0
    if len(curvatures) > 1:
        cv = sum((c - mean_curvature) ** 2 for c in curvatures) / len(curvatures)
        std_curvature = float(math.sqrt(cv))
    else:
        std_curvature = 0.0

    # lane count (exclude center lane id=0)
    lane_count = 0
    for lane in root.findall(".//lane"):
        lid = lane.get("id", "0").strip()
        if lid != "0":
            lane_count += 1

    # connectivity rate: roads that have a successor or predecessor link
    roads_with_links = 0
    for r in roads:
        link = r.find("link")
        if link is not None:
            has_succ = link.find("successor") is not None
            has_pred = link.find("predecessor") is not None
            if has_succ or has_pred:
                roads_with_links += 1
    connectivity_rate = float(roads_with_links / road_count) if road_count > 0 else 0.0

    # bbox from header
    header = root.find("header")
    bbox_area_m2 = 0.0
    if header is not None:
        north = _safe_float(header.get("north"), 0.0)
        south = _safe_float(header.get("south"), 0.0)
        east = _safe_float(header.get("east"), 0.0)
        west = _safe_float(header.get("west"), 0.0)
        dx = abs(east - west)
        dy = abs(north - south)
        if dx > 0 and dy > 0:
            bbox_area_m2 = float(dx * dy)

    return {
        "road_count": int(road_count),
        "junction_count": int(junction_count),
        "mean_road_length_m": round(mean_road_length_m, 4),
        "std_road_length_m": round(std_road_length_m, 4),
        "mean_curvature": round(mean_curvature, 8),
        "std_curvature": round(std_curvature, 8),
        "lane_count": int(lane_count),
        "connectivity_rate": round(connectivity_rate, 6),
        "bbox_area_m2": round(bbox_area_m2, 2),
    }


def collect_tiles(
    directories: List[Path],
    label: str,
    max_per_dir: int,
) -> List[Dict[str, Any]]:
    samples: List[Dict[str, Any]] = []
    seen_names: set = set()  # deduplicate by filename to avoid counting same tile twice

    for d in directories:
        if not d.is_dir():
            print(f"  [INFO] directory not found, skipping: {d}", file=sys.stderr)
            continue

        xodr_files = sorted(d.glob("*.xodr"))[:max_per_dir]
        dir_count = 0
        for xf in xodr_files:
            # Use name+size as dedup key
            key = f"{xf.name}_{xf.stat().st_size}"
            if key in seen_names:
                continue
            seen_names.add(key)

            feats = extract_features(xf)
            if feats is None:
                continue

            tile_id = f"{xf.stem}_{label}_{d.parent.name}"
            samples.append({
                "id": tile_id,
                "label": label,
                "source_dir": str(d),
                "filename": xf.name,
                "file_size_bytes": xf.stat().st_size,
                "features": feats,
            })
            dir_count += 1
            print(f"  [OK] {label} {xf.name} roads={feats['road_count']} junctions={feats['junction_count']}")

        print(f"  -> {dir_count} {label} tiles from {d.name}", file=sys.stderr)

    return samples


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== TASK 2: Feature Extraction ===")
    print(f"Output: {OUT_PATH}")

    print("\n[Auto tiles]")
    auto_samples = collect_tiles(AUTO_DIRS, "auto", MAX_AUTO_PER_DIR)

    print("\n[Manual tiles]")
    manual_samples = collect_tiles(MANUAL_DIRS, "manual", MAX_MANUAL_PER_DIR)

    all_samples = auto_samples + manual_samples
    n_auto = len(auto_samples)
    n_manual = len(manual_samples)
    n_total = len(all_samples)

    print(f"\n=== Summary ===")
    print(f"Auto tiles:   {n_auto}")
    print(f"Manual tiles: {n_manual}")
    print(f"Total:        {n_total}")

    if n_total < 30:
        print(f"WARNING: Only {n_total} samples found. Target is 30+.", file=sys.stderr)

    feature_names = [
        "road_count",
        "junction_count",
        "mean_road_length_m",
        "std_road_length_m",
        "mean_curvature",
        "std_curvature",
        "lane_count",
        "connectivity_rate",
        "bbox_area_m2",
    ]

    payload = {
        "schema_version": "n30_v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "feature_names": feature_names,
        "n_auto": n_auto,
        "n_manual": n_manual,
        "n_total": n_total,
        "target_met": n_total >= 30,
        "source_dirs_auto": [str(d) for d in AUTO_DIRS],
        "source_dirs_manual": [str(d) for d in MANUAL_DIRS],
        "samples": all_samples,
    }

    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote: {OUT_PATH}")


if __name__ == "__main__":
    main()
