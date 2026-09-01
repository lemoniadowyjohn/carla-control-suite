#!/usr/bin/env python3
"""
Evaluate correspondence between two tile_metadata.json files.

Outputs:
  - frame_diagnosis.json
  - frame_diagnosis_a.json
  - frame_diagnosis_b.json
  - correspondence.csv
  - alignment_stats.json
  - NO_MATCH_DIAGNOSIS.txt (only when no matches found)
  - domain_gap_report.json (optional, if metrics provided)
  - worst_pairs.csv (optional, if metrics provided)
"""

from __future__ import annotations

import argparse
import os
import csv
import json
import math
import random
import time
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Tuple


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_meta(path: Path) -> Dict[str, dict]:
    data = _load_json(path)
    if isinstance(data, dict) and "tiles" in data and isinstance(data["tiles"], dict):
        data = data["tiles"]
    if not isinstance(data, dict):
        return {}

    cleaned: Dict[str, dict] = {}
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        if k.startswith("_"):  # skip settings snapshots and similar
            continue
        cleaned[str(k)] = v
    return cleaned


def _parse_bbox(meta: dict) -> Optional[Tuple[float, float, float, float]]:
    bb = meta.get("core_bbox") or meta.get("bbox") or meta.get("bounds") or {}

    # list / tuple [minx, miny, maxx, maxy]
    if isinstance(bb, (list, tuple)) and len(bb) >= 4:
        try:
            return float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
        except Exception:
            return None

    # nested dict {core: {...}}
    if isinstance(bb, dict) and "core" in bb and isinstance(bb.get("core"), dict):
        bb = bb["core"]

    minx = bb.get("min_x") if isinstance(bb, dict) else None
    maxx = bb.get("max_x") if isinstance(bb, dict) else None
    miny = bb.get("min_y") if isinstance(bb, dict) else None
    maxy = bb.get("max_y") if isinstance(bb, dict) else None

    if isinstance(bb, dict) and None in (minx, maxx, miny, maxy):
        mn, mx = bb.get("min"), bb.get("max")
        if isinstance(mn, (list, tuple)) and isinstance(mx, (list, tuple)) and len(mn) >= 2 and len(mx) >= 2:
            minx, miny = mn[0], mn[1]
            maxx, maxy = mx[0], mx[1]

    if None in (minx, maxx, miny, maxy):
        return None
    try:
        return float(minx), float(miny), float(maxx), float(maxy)
    except Exception:
        return None


def _bbox_center_diag(bb: Tuple[float, float, float, float]) -> Tuple[Tuple[float, float], float]:
    minx, miny, maxx, maxy = bb
    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0
    dx = maxx - minx
    dy = maxy - miny
    diag = math.hypot(dx, dy)
    return (cx, cy), diag


def _bbox_iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter
    if denom <= 0.0:
        return 0.0
    return inter / denom


def _frame_diagnosis(coords: List[float]) -> dict:
    if not coords:
        return {"label": "unknown", "min": None, "max": None, "median": None, "p95": None}
    abs_vals = [abs(c) for c in coords]
    abs_vals.sort()
    min_v = abs_vals[0]
    max_v = abs_vals[-1]
    med_v = abs_vals[len(abs_vals) // 2]
    p95_v = abs_vals[int(round((len(abs_vals) - 1) * 0.95))]

    label = "unknown"
    if max_v <= 180.0 and med_v <= 90.0:
        label = "degrees"
    elif 1e3 <= med_v <= 1e5:
        label = "local_meters"
    elif max_v >= 1e5:
        label = "projected_meters"

    return {
        "label": label,
        "min": min_v,
        "max": max_v,
        "median": med_v,
        "p95": p95_v,
    }


def _build_index(meta: Dict[str, dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for k in sorted(meta.keys()):
        bb = _parse_bbox(meta[k])
        if bb is None:
            continue
        center, diag = _bbox_center_diag(bb)
        out[k] = {"bbox": bb, "center": center, "diag": diag}
    return out


def _median_tile_diag(idx: Dict[str, dict]) -> float:
    if not idx:
        return 1.0
    diags = sorted(v["diag"] for v in idx.values())
    return diags[len(diags) // 2] if diags else 1.0


def _distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _series_stats(values: List[float]) -> dict:
    if not values:
        return {"min": None, "median": None, "max": None}
    sorted_vals = sorted(values)
    return {
        "min": sorted_vals[0],
        "median": median(sorted_vals),
        "max": sorted_vals[-1],
    }


def _center_magnitude_stats(idx: Dict[str, dict]) -> dict:
    abs_x = [abs(v["center"][0]) for v in idx.values()]
    abs_y = [abs(v["center"][1]) for v in idx.values()]
    return {"abs_x": _series_stats(abs_x), "abs_y": _series_stats(abs_y)}


def _sample_center_distance_stats(
    idx_a: Dict[str, dict],
    idx_b: Dict[str, dict],
    sample_size: int = 200,
) -> dict:
    centers_a = [v["center"] for _, v in sorted(idx_a.items())]
    centers_b = [v["center"] for _, v in sorted(idx_b.items())]
    if not centers_a or not centers_b:
        return {
            "samples_a": len(centers_a),
            "samples_b": len(centers_b),
            "pairs": 0,
            "min": None,
            "median": None,
            "max": None,
        }

    rng = random.Random(0)
    sample_a = centers_a if len(centers_a) <= sample_size else rng.sample(centers_a, sample_size)
    sample_b = centers_b if len(centers_b) <= sample_size else rng.sample(centers_b, sample_size)

    distances = [_distance(a, b) for a in sample_a for b in sample_b]
    distances.sort()
    return {
        "samples_a": len(sample_a),
        "samples_b": len(sample_b),
        "pairs": len(distances),
        "min": distances[0] if distances else None,
        "median": median(distances) if distances else None,
        "max": distances[-1] if distances else None,
    }


def _match_tiles(
    idx_a: Dict[str, dict],
    idx_b: Dict[str, dict],
    *,
    max_dist_mult: float,
    min_iou: float,
) -> Tuple[List[dict], dict]:
    median_diag = _median_tile_diag(idx_a)
    max_dist = max_dist_mult * median_diag

    candidates: List[Tuple[float, float, str, str]] = []
    for b_id, b_info in idx_b.items():
        b_center = b_info["center"]
        best_a = None
        best_dist = None
        best_iou = None
        for a_id, a_info in idx_a.items():
            dist = _distance(b_center, a_info["center"])
            if dist > max_dist:
                continue
            iou = _bbox_iou(a_info["bbox"], b_info["bbox"])
            if iou < min_iou:
                continue
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_iou = iou
                best_a = a_id
        if best_a is not None and best_dist is not None and best_iou is not None:
            candidates.append((best_dist, -best_iou, b_id, best_a))

    candidates.sort()
    candidate_pairs = len(candidates)
    matched_a = set()
    matched_b = set()
    matches: List[dict] = []
    for dist, neg_iou, b_id, a_id in candidates:
        if b_id in matched_b or a_id in matched_a:
            continue
        a_info = idx_a[a_id]
        b_info = idx_b[b_id]
        dx = a_info["center"][0] - b_info["center"][0]
        dy = a_info["center"][1] - b_info["center"][1]
        match = {
            "b_tile": b_id,
            "a_tile": a_id,
            "distance": dist,
            "iou": -neg_iou,
            "dx": dx,
            "dy": dy,
            "a_center": a_info["center"],
            "b_center": b_info["center"],
        }
        matches.append(match)
        matched_a.add(a_id)
        matched_b.add(b_id)

    stats = {
        "matched": len(matches),
        "unmatched_a": len(idx_a) - len(matched_a),
        "unmatched_b": len(idx_b) - len(matched_b),
        "max_dist": max_dist,
        "median_tile_diag": median_diag,
        "candidate_pairs": candidate_pairs,
    }
    return matches, stats


def _loose_translation(matches: List[dict]) -> Tuple[float, float]:
    if not matches:
        return 0.0, 0.0
    dxs = sorted(m["dx"] for m in matches)
    dys = sorted(m["dy"] for m in matches)
    mx = dxs[len(dxs) // 2]
    my = dys[len(dys) // 2]
    return mx, my


def _apply_translation(idx: Dict[str, dict], dx: float, dy: float) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for k, v in idx.items():
        cx, cy = v["center"]
        bb = v["bbox"]
        shifted_bb = (bb[0] + dx, bb[1] + dy, bb[2] + dx, bb[3] + dy)
        out[k] = {
            "bbox": shifted_bb,
            "center": (cx + dx, cy + dy),
            "diag": v["diag"],
        }
    return out


def _dump_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8")


def _write_csv(path: Path, rows: List[dict], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _write_no_match_diag(
    out_dir: Path,
    *,
    count_a: int,
    count_b: int,
    frame_a: dict,
    frame_b: dict,
    center_stats_a: dict,
    center_stats_b: dict,
    sample_stats: dict,
    gating: dict,
) -> None:
    def _fmt(val: Optional[float]) -> str:
        if val is None:
            return "n/a"
        if isinstance(val, float):
            return f"{val:.6f}"
        return str(val)

    lines = [
        "No correspondence matches were produced.",
        f"tiles_in_a: {count_a}",
        f"tiles_in_b: {count_b}",
        f"frame_label_a: {frame_a.get('label')}",
        f"frame_label_b: {frame_b.get('label')}",
        "",
        "gating:",
    ]
    for key in ("min_iou", "max_dist_mult", "estimate_translation", "bootstrap_loose_enabled", "max_dist_absolute"):
        if key in gating:
            lines.append(f"  {key}: {_fmt(gating.get(key))}")
    if "buffer" in gating:
        lines.append(f"  buffer: {_fmt(gating.get('buffer'))}")

    lines.extend(
        [
            "",
            "center_magnitude_abs:",
            f"  A abs(x): min={_fmt(center_stats_a.get('abs_x', {}).get('min'))} median={_fmt(center_stats_a.get('abs_x', {}).get('median'))} max={_fmt(center_stats_a.get('abs_x', {}).get('max'))}",
            f"  A abs(y): min={_fmt(center_stats_a.get('abs_y', {}).get('min'))} median={_fmt(center_stats_a.get('abs_y', {}).get('median'))} max={_fmt(center_stats_a.get('abs_y', {}).get('max'))}",
            f"  B abs(x): min={_fmt(center_stats_b.get('abs_x', {}).get('min'))} median={_fmt(center_stats_b.get('abs_x', {}).get('median'))} max={_fmt(center_stats_b.get('abs_x', {}).get('max'))}",
            f"  B abs(y): min={_fmt(center_stats_b.get('abs_y', {}).get('min'))} median={_fmt(center_stats_b.get('abs_y', {}).get('median'))} max={_fmt(center_stats_b.get('abs_y', {}).get('max'))}",
            "",
            "sample_center_distance:",
            f"  samples_a: {sample_stats.get('samples_a', 0)}",
            f"  samples_b: {sample_stats.get('samples_b', 0)}",
            f"  pairs: {sample_stats.get('pairs', 0)}",
            f"  min: {_fmt(sample_stats.get('min'))}",
            f"  median: {_fmt(sample_stats.get('median'))}",
            f"  max: {_fmt(sample_stats.get('max'))}",
            "  note: samples use up to 200 tiles per side with deterministic seed 0.",
        ]
    )

    out_path = out_dir / "NO_MATCH_DIAGNOSIS.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_metrics(path: Optional[str]) -> Dict[str, dict]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    if p.suffix.lower() == ".csv":
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            out: Dict[str, dict] = {}
            for row in reader:
                tile = row.get("tile") or row.get("file") or row.get("name")
                if tile:
                    out[str(tile)] = dict(row)
            return out
    try:
        data = _load_json(p)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _merge_metrics(matches: List[dict], metrics_a: Dict[str, dict], metrics_b: Dict[str, dict]) -> Tuple[dict, List[dict]]:
    rows = []
    distances = []
    ious = []
    for m in matches:
        a_tile = m["a_tile"]
        b_tile = m["b_tile"]
        row = {
            "a_tile": a_tile,
            "b_tile": b_tile,
            "distance": m["distance"],
            "iou": m["iou"],
        }
        if a_tile in metrics_a:
            for k, v in metrics_a[a_tile].items():
                row[f"a_{k}"] = v
        if b_tile in metrics_b:
            for k, v in metrics_b[b_tile].items():
                row[f"b_{k}"] = v
        rows.append(row)
        distances.append(m["distance"])
        ious.append(m["iou"])

    distances.sort()
    ious.sort()
    report = {
        "matched": len(matches),
        "distance": {
            "p50": distances[len(distances) // 2] if distances else None,
            "p95": distances[int(round((len(distances) - 1) * 0.95))] if distances else None,
        },
        "iou": {
            "p50": ious[len(ious) // 2] if ious else None,
            "p95": ious[int(round((len(ious) - 1) * 0.95))] if ious else None,
        },
    }
    rows_sorted = sorted(rows, key=lambda r: (-(float(r.get("distance", 0.0)) if isinstance(r.get("distance"), (int, float, str)) else 0.0)))
    return report, rows_sorted


def evaluate(args: argparse.Namespace) -> int:
    try:
        a_meta = _load_meta(Path(args.a_meta))
    except (OSError, json.JSONDecodeError):
        a_meta = {}
    try:
        b_meta = _load_meta(Path(args.b_meta))
    except (OSError, json.JSONDecodeError):
        b_meta = {}

    if not a_meta:
        print(f"ERROR: failed to load A metadata from {args.a_meta}")
        return 2
    if not b_meta:
        print(f"ERROR: failed to load B metadata from {args.b_meta}")
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    min_iou = float(args.min_iou)
    max_dist_mult = float(args.max_dist_mult)
    estimate_translation = bool(args.estimate_translation)
    bootstrap_loose_enabled = bool(args.bootstrap_loose)
    min_bootstrap_matches = int(args.min_bootstrap_matches)

    idx_a = _build_index(a_meta)
    idx_b = _build_index(b_meta)

    coords_a = []
    coords_b = []
    for v in idx_a.values():
        bb = v["bbox"]
        coords_a.extend([bb[0], bb[1], bb[2], bb[3]])
    for v in idx_b.values():
        bb = v["bbox"]
        coords_b.extend([bb[0], bb[1], bb[2], bb[3]])

    frame_a = _frame_diagnosis(coords_a)
    frame_b = _frame_diagnosis(coords_b)
    frame_combined = _frame_diagnosis(coords_a + coords_b)
    _dump_json(out_dir / "frame_diagnosis.json", frame_combined)
    _dump_json(out_dir / "frame_diagnosis_a.json", frame_a)
    _dump_json(out_dir / "frame_diagnosis_b.json", frame_b)

    center_stats_a = _center_magnitude_stats(idx_a)
    center_stats_b = _center_magnitude_stats(idx_b)
    sample_stats = _sample_center_distance_stats(idx_a, idx_b)

    # Bootstrap-loose provenance tracking
    trans_applied = False
    trans_dx = 0.0
    trans_dy = 0.0
    translation_estimated = False
    translation_rejected_reason: Optional[str] = None
    loose_candidate_pairs = 0
    loose_matched = 0
    loose_unmatched_a = len(idx_a)
    loose_unmatched_b = len(idx_b)
    likely_causes: List[str] = []

    # Optional bootstrap-loose translation estimation (does not alter user gates unless applied)
    idx_b_for_match = idx_b
    if bootstrap_loose_enabled:
        loose_matches, loose_stats = _match_tiles(
            idx_a,
            idx_b,
            max_dist_mult=50.0,
            min_iou=0.0,
        )
        loose_candidate_pairs = loose_stats.get("candidate_pairs", 0)
        loose_matched = loose_stats.get("matched", 0)
        loose_unmatched_a = loose_stats.get("unmatched_a", 0)
        loose_unmatched_b = loose_stats.get("unmatched_b", 0)

        if len(loose_matches) >= min_bootstrap_matches:
            dx, dy = _loose_translation(loose_matches)
            translation_estimated = True
            median_diag = _median_tile_diag(idx_a)
            if median_diag <= 0:
                median_diag = 1.0

            if math.isfinite(dx) and math.isfinite(dy):
                if abs(dx) <= 5.0 * median_diag and abs(dy) <= 5.0 * median_diag:
                    idx_b_for_match = _apply_translation(idx_b, dx, dy)
                    trans_applied = True
                    trans_dx = dx
                    trans_dy = dy
                else:
                    translation_rejected_reason = (
                        f"Translation magnitude exceeds 5x median diag ({median_diag:.6f})"
                    )
                    likely_causes.append("Translation magnitude gate tripped (possible frame mismatch)")
                    translation_estimated = False
            else:
                translation_rejected_reason = "Non-finite translation from bootstrap"
                likely_causes.append("Bootstrap translation produced NaN/Inf")
                translation_estimated = False
        else:
            translation_rejected_reason = (
                f"Insufficient loose matches: {len(loose_matches)} < {min_bootstrap_matches}"
            )
            likely_causes.append(f"Only {len(loose_matches)} loose matches (need {min_bootstrap_matches})")

    # initial matching with user gates (after optional bootstrap translation)
    matches, stats = _match_tiles(
        idx_a,
        idx_b_for_match,
        max_dist_mult=max_dist_mult,
        min_iou=min_iou,
    )

    if estimate_translation and not bootstrap_loose_enabled:
        loose_matches, loose_stats = _match_tiles(
            idx_a,
            idx_b,
            max_dist_mult=max_dist_mult * 5.0,
            min_iou=max(min_iou * 0.5, 0.0),
        )
        loose_candidate_pairs = loose_stats.get("candidate_pairs", 0)

        # EVIDENCE GATE: require minimum matches for translation estimation
        if len(loose_matches) >= min_bootstrap_matches:
            trans_dx, trans_dy = _loose_translation(loose_matches)
            translation_estimated = True

            # SAFETY GATE 1: dx/dy must be finite
            if not (math.isfinite(trans_dx) and math.isfinite(trans_dy)):
                translation_rejected_reason = f"Non-finite translation: dx={trans_dx}, dy={trans_dy}"
                translation_estimated = False
                likely_causes.append("Translation estimation produced NaN/Inf")

            # SAFETY GATE 2: magnitude sanity (max 5x median tile diagonal)
            if translation_estimated:
                median_diag = _median_tile_diag(idx_a)
                max_trans_magnitude = 5.0 * median_diag
                trans_magnitude = math.hypot(trans_dx, trans_dy)
                if trans_magnitude > max_trans_magnitude:
                    translation_rejected_reason = (
                        f"Translation magnitude {trans_magnitude:.2f} exceeds "
                        f"5x median tile diagonal ({max_trans_magnitude:.2f})"
                    )
                    translation_estimated = False
                    likely_causes.append("Absurd translation magnitude (frame mismatch?)")

            # Apply translation if all gates passed
            if translation_estimated:
                idx_b_shifted = _apply_translation(idx_b, trans_dx, trans_dy)
                matches, stats = _match_tiles(
                    idx_a,
                    idx_b_shifted,
                    max_dist_mult=max_dist_mult,
                    min_iou=min_iou,
                )
                trans_applied = True
        else:
            translation_rejected_reason = (
                f"Insufficient loose matches: {len(loose_matches)} < {min_bootstrap_matches}"
            )
            likely_causes.append(f"Only {len(loose_matches)} loose matches (need {min_bootstrap_matches})")

    # Diagnose zero strict matches
    if not matches:
        if not likely_causes:
            likely_causes.append("Coordinate frame mismatch (different projections?)")
            likely_causes.append("Tile grids do not overlap spatially")
            likely_causes.append("Metadata format incompatibility")

    matches_sorted = sorted(matches, key=lambda m: m["distance"])
    corr_csv = out_dir / "correspondence.csv"
    corr_fields = [
        "a_tile",
        "b_tile",
        "distance",
        "iou",
        "dx",
        "dy",
        "a_center_x",
        "a_center_y",
        "b_center_x",
        "b_center_y",
    ]
    corr_rows = []
    for m in matches_sorted:
        corr_rows.append(
            {
                "a_tile": m["a_tile"],
                "b_tile": m["b_tile"],
                "distance": f"{m['distance']:.6f}",
                "iou": f"{m['iou']:.6f}",
                "dx": f"{m['dx']:.6f}",
                "dy": f"{m['dy']:.6f}",
                "a_center_x": f"{m['a_center'][0]:.6f}",
                "a_center_y": f"{m['a_center'][1]:.6f}",
                "b_center_x": f"{m['b_center'][0]:.6f}",
                "b_center_y": f"{m['b_center'][1]:.6f}",
            }
        )
    _write_csv(corr_csv, corr_rows, corr_fields)

    dists = sorted(m["distance"] for m in matches_sorted)
    ious = sorted(m["iou"] for m in matches_sorted)
    stats_out = {
        "matched": stats.get("matched", 0),
        "unmatched_a": stats.get("unmatched_a", 0),
        "unmatched_b": stats.get("unmatched_b", 0),
        "distance_p50": dists[len(dists) // 2] if dists else None,
        "distance_p95": dists[int(round((len(dists) - 1) * 0.95))] if dists else None,
        "iou_p50": ious[len(ious) // 2] if ious else None,
        "iou_p95": ious[int(round((len(ious) - 1) * 0.95))] if ious else None,
        "median_tile_diag": stats.get("median_tile_diag"),
        "max_dist": stats.get("max_dist"),
        "translation_applied": trans_applied,
        "translation_dx": trans_dx,
        "translation_dy": trans_dy,
        "tiles_in_a": len(idx_a),
        "tiles_in_b": len(idx_b),
        "gating": {
            "min_iou": min_iou,
            "max_dist_mult": max_dist_mult,
            "estimate_translation": estimate_translation,
            "bootstrap_loose_enabled": bootstrap_loose_enabled,
            "max_dist_absolute": stats.get("max_dist"),
        },
        "frame_labels": {"a": frame_a.get("label"), "b": frame_b.get("label")},
        # Bootstrap-loose provenance (thesis traceability)
        "bootstrap_loose_provenance": {
            "bootstrap_loose_enabled": bootstrap_loose_enabled,
            "bootstrap_loose_min_matches": min_bootstrap_matches,
            "loose_matched": loose_matched,
            "loose_unmatched_a": loose_unmatched_a,
            "loose_unmatched_b": loose_unmatched_b,
            "loose_candidate_pairs": loose_candidate_pairs,
            "translation_estimated": translation_estimated,
            "translation_applied": trans_applied if bootstrap_loose_enabled else False,
            "translation_dx": trans_dx if bootstrap_loose_enabled else 0.0,
            "translation_dy": trans_dy if bootstrap_loose_enabled else 0.0,
            "translation_rejected_reason": translation_rejected_reason,
            "likely_causes": likely_causes if likely_causes else None,
        },
    }
    _dump_json(out_dir / "alignment_stats.json", stats_out)

    if not matches_sorted:
        _write_no_match_diag(
            out_dir,
            count_a=len(idx_a),
            count_b=len(idx_b),
            frame_a=frame_a,
            frame_b=frame_b,
            center_stats_a=center_stats_a,
            center_stats_b=center_stats_b,
            sample_stats=sample_stats,
            gating={
                "min_iou": min_iou,
                "max_dist_mult": max_dist_mult,
                "estimate_translation": estimate_translation,
                "bootstrap_loose_enabled": bootstrap_loose_enabled,
                "max_dist_absolute": stats.get("max_dist"),
                "buffer": None,
            },
        )

    metrics_a = _load_metrics(args.a_metrics)
    metrics_b = _load_metrics(args.b_metrics)
    if metrics_a or metrics_b:
        report, worst_rows = _merge_metrics(matches_sorted, metrics_a, metrics_b)
        _dump_json(out_dir / "domain_gap_report.json", report)
        worst_fields = sorted({k for row in worst_rows for k in row.keys()})
        _write_csv(out_dir / "worst_pairs.csv", worst_rows, worst_fields)

    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Evaluate correspondence between two tile_metadata.json files.")
    ap.add_argument("--a-meta", required=True, help="Path to first tile_metadata.json")
    ap.add_argument("--b-meta", required=True, help="Path to second tile_metadata.json")
    ap.add_argument("--a-metrics", help="Optional metrics (csv or json) for A tiles")
    ap.add_argument("--b-metrics", help="Optional metrics (csv or json) for B tiles")
    ap.add_argument("--out", default=None, help="Output directory (default: eval_out/<a>__vs__<b>__<ts>)")
    ap.add_argument("--max-dist-mult", type=float, default=3.0, help="Max distance multiplier of median tile diagonal")
    ap.add_argument("--min-iou", type=float, default=0.01, help="Minimum IoU to accept a match")
    ap.add_argument("--estimate-translation", action="store_true", help="Estimate median translation and rematch")
    ap.add_argument("--bootstrap-loose", action="store_true", default=False,
                    help="Enable thesis-safe loose matching rescue mode (OFF by default)")
    ap.add_argument("--min-bootstrap-matches", type=int, default=10,
                    help="Minimum loose matches required to estimate translation (default: 10)")
    return ap


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.out is None:
        a_name = Path(args.a_meta).parent.name or "a"
        b_name = Path(args.b_meta).parent.name or "b"
        ts = time.strftime("%Y%m%d_%H%M%S")
        args.out = os.path.join("eval_out", f"{a_name}__vs__{b_name}__{ts}")
    return evaluate(args)


if __name__ == "__main__":
    raise SystemExit(main())
