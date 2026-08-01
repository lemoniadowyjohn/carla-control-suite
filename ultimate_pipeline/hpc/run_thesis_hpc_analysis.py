#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HPC analysis/training orchestrator for thesis paired datasets (no CARLA).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional


def _scan_runs(dataset_root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for run_dir in sorted(dataset_root.glob("*")):
        if not run_dir.is_dir():
            continue
        perception_dir = run_dir / "perception_pair"
        if not perception_dir.is_dir():
            continue
        row = {
            "run_dir": str(run_dir),
            "perception_metrics": str(perception_dir / "perception_metrics.json") if (perception_dir / "perception_metrics.json").is_file() else "",
            "pair_manifest": str(perception_dir / "pair_manifest.json") if (perception_dir / "pair_manifest.json").is_file() else "",
            "structural_report": str(run_dir / "structural" / "full_report.json") if (run_dir / "structural" / "full_report.json").is_file() else "",
        }
        rows.append(row)
    return rows


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["run_dir", "perception_metrics", "pair_manifest", "structural_report"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_summary(path: Path, rows: List[Dict[str, Any]]) -> None:
    summary = {
        "total_runs": len(rows),
        "with_perception_metrics": sum(1 for r in rows if r["perception_metrics"]),
        "with_pair_manifest": sum(1 for r in rows if r["pair_manifest"]),
        "with_structural_report": sum(1 for r in rows if r["structural_report"]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="HPC analysis helper for thesis paired datasets.")
    ap.add_argument("--dataset_root", required=True, help="Directory containing many <run>/perception_pair outputs")
    ap.add_argument("--manual_xodr", default="", help="Optional manual XODR path (if structural analysis is needed)")
    ap.add_argument("--out", required=True, help="Output directory for index/summary")
    ap.add_argument("--train-yolo-config", default="", help="Optional YOLO training config JSON")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    dataset_root = Path(args.dataset_root).expanduser()
    out_dir = Path(args.out).expanduser()

    rows = _scan_runs(dataset_root)
    _write_csv(out_dir / "hpc_dataset_index.csv", rows)
    _write_summary(out_dir / "hpc_dataset_summary.json", rows)

    if args.train_yolo_config:
        cfg_path = Path(args.train_yolo_config).expanduser()
        if cfg_path.is_file():
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ultimate_pipeline.hpc.train_yolo",
                    "--exp-name",
                    "thesis_hpc_yolo",
                    "--config",
                    str(cfg_path),
                ],
                check=False,
            )
        else:
            print(f"[WARNING] YOLO config not found: {cfg_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
