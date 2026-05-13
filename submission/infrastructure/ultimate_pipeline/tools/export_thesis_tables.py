#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline.tools.export_thesis_tables

Creates thesis-ready batch tables by scanning ultimate_pipeline_out/<RUN_ID>/ directories.

Outputs (in output folder, default: BASE_OUTPUT_DIR):
- thesis_batch_summary.csv
- thesis_batch_summary.json

Columns are scalars only.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Optional, List

from ultimate_pipeline.config.settings import SETTINGS

def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def _latest_final_xodr(run_dir: Path) -> Optional[Path]:
    cands = sorted(run_dir.glob("08_final*_semantic.xodr"), key=lambda x: x.stat().st_mtime, reverse=True)
    if cands:
        return cands[0]
    cands = sorted(run_dir.glob("08_final*.xodr"), key=lambda x: x.stat().st_mtime, reverse=True)
    if cands:
        return cands[0]
    return None

def collect_run_row(run_dir: Path) -> Dict[str, Any]:
    row: Dict[str, Any] = {"run_id": run_dir.name}

    det = _read_json(run_dir / "determinism_fingerprint.json") or {}
    acc = _read_json(run_dir / "map_acceptance.json") or {}
    stats = _read_json(run_dir / "map_statistics.json") or {}

    dg_dir = run_dir / (getattr(SETTINGS, "DOMAIN_GAP_OUT_DIR", "domain_gap") or "domain_gap")
    dg_sum = _read_json(dg_dir / "domain_gap_summary.json") or _read_json(dg_dir / "summary.json") or {}
    align = _read_json(dg_dir / "alignment.json") or {}

    dem_full = _read_json(run_dir / "dem_full_coverage.json") or _read_json(run_dir / "logs" / "dem_full_coverage.json") or {}
    rec_sum = _read_json(run_dir / "perception_thesis" / "recording_summary.json") or _read_json(run_dir / "recording_summary.json") or {}

    final_xodr = _latest_final_xodr(run_dir)
    row["final_xodr_path"] = str(final_xodr) if final_xodr else ""

    row["determinism_final_xodr_sha256"] = det.get("final_xodr")
    row["settings_snapshot_sha256"] = det.get("settings_snapshot")
    row["git_commit"] = det.get("git_commit")
    row["seed"] = det.get("seed")

    row["map_acceptance_valid"] = acc.get("valid")
    row["roads_total"] = stats.get("total_roads")
    row["junctions_total"] = stats.get("total_junctions")
    row["lane_sections_total"] = stats.get("total_lane_sections")

    row["dem_full_coverage_ratio"] = dem_full.get("coverage_ratio")
    row["dem_full_total_samples"] = dem_full.get("total_samples")

    diag = align.get("diagnostics", {}) if isinstance(align, dict) else {}
    row["alignment_n_points"] = diag.get("n_points")
    row["alignment_rmse_after"] = diag.get("rmse_after")
    row["alignment_fallback_used"] = diag.get("fallback_used")

    whole_geom = (dg_sum.get("whole_geometry_gap") or dg_sum.get("whole_geometry") or {})
    if isinstance(whole_geom, dict):
        row["domain_gap_geometry_rmse"] = whole_geom.get("rmse") or whole_geom.get("rmse_xy")
        row["domain_gap_geometry_hausdorff"] = whole_geom.get("hausdorff")
    whole_curv = (dg_sum.get("whole_curvature_gap") or dg_sum.get("whole_curvature") or {})
    if isinstance(whole_curv, dict):
        row["domain_gap_curvature_kl"] = whole_curv.get("kl_divergence")

    row["perception_frames_recorded"] = rec_sum.get("frames_recorded")
    row["perception_min_frames_required"] = rec_sum.get("min_frames_required")
    row["perception_status"] = rec_sum.get("status")
    row["perception_png_count"] = rec_sum.get("png_count")
    row["perception_ply_count"] = rec_sum.get("ply_count")

    return row

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(getattr(SETTINGS, "BASE_OUTPUT_DIR", "ultimate_pipeline_out")))
    ap.add_argument("--csv", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    out_root = Path(args.out).expanduser()
    if not out_root.is_dir():
        raise SystemExit(f"Not a directory: {out_root}")

    csv_path = Path(args.csv) if args.csv else (out_root / "thesis_batch_summary.csv")
    json_path = Path(args.json) if args.json else (out_root / "thesis_batch_summary.json")

    run_dirs = [p for p in out_root.iterdir() if p.is_dir() and not p.name.lower().startswith("manual")]
    run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if args.limit and args.limit > 0:
        run_dirs = run_dirs[: args.limit]

    rows: List[Dict[str, Any]] = []
    for rd in run_dirs:
        try:
            rows.append(collect_run_row(rd))
        except Exception:
            continue

    headers = [
        "run_id",
        "final_xodr_path",
        "determinism_final_xodr_sha256",
        "settings_snapshot_sha256",
        "git_commit",
        "seed",
        "map_acceptance_valid",
        "roads_total",
        "junctions_total",
        "lane_sections_total",
        "dem_full_coverage_ratio",
        "dem_full_total_samples",
        "alignment_n_points",
        "alignment_rmse_after",
        "alignment_fallback_used",
        "domain_gap_geometry_rmse",
        "domain_gap_geometry_hausdorff",
        "domain_gap_curvature_kl",
        "perception_frames_recorded",
        "perception_min_frames_required",
        "perception_status",
        "perception_png_count",
        "perception_ply_count",
    ]

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow({h: r.get(h, "") for h in headers})

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps({"runs": rows}, indent=2), encoding="utf-8")

    # Sparsity check
    total_cells = len(rows) * len(headers)
    if total_cells > 0:
        empty_count = sum(1 for r in rows for h in headers if not r.get(h))
        sparsity = empty_count / total_cells
        if sparsity > 0.5:
            print(f"⚠ WARNING: Table is very sparse ({sparsity:.1%} empty). Review artifact completeness.")

    print(f"Wrote: {csv_path}")
    print(f"Wrote: {json_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
