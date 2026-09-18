#!/usr/bin/env python3
r"""
Experiment 1: Auto-vs-Auto domain gap (pipeline stability / natural variability)

Usage (PowerShell):
  python .\experiment_auto_vs_auto.py ^
    --ref-run "C:\...\ultimate_pipeline_out\20251226_221201_423005" ^
    --cur-run "C:\...\ultimate_pipeline_out\20251227_003034_043278" ^
    --out-dir "C:\...\ultimate_pipeline_out\experiments\auto_vs_auto_01"

This script:
- finds final XODR in each run folder
- finds tiles folder if present
- computes basic XML node counts + SHA256 hashes
- runs ultimate_pipeline.run_full_domain_gap.run_full_domain_gap()
- writes experiment_summary.json into out-dir
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Dict, Optional, Tuple


# -----------------------------
# Helpers
# -----------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_best_xodr(run_dir: Path) -> Path:
    """Prefer laneSectionFixed, then semantic, then 08_final, else any .xodr."""
    candidates = list(run_dir.glob("*.xodr"))
    if not candidates:
        raise FileNotFoundError(f"No .xodr files found in: {run_dir}")

    def rank(p: Path) -> Tuple[int, int, str]:
        name = p.name
        # lower is better
        if "laneSectionFixed" in name:
            r = 0
        elif "semantic" in name:
            r = 1
        elif name.startswith("08_final"):
            r = 2
        else:
            r = 3
        # prefer larger files among same category (often more complete)
        size_rank = -p.stat().st_size
        return r, size_rank, name

    return sorted(candidates, key=rank)[0]


def find_tiles_dir(run_dir: Path) -> Optional[Path]:
    tiles = run_dir / "tiles"
    return tiles if tiles.exists() and tiles.is_dir() else None


def xml_counts(xodr_path: Path) -> Dict[str, int]:
    """
    Fast structural counts (no fancy semantics). Mirrors your PowerShell checks.
    """
    root = ET.parse(xodr_path).getroot()
    def cnt(xpath: str) -> int:
        return len(root.findall(xpath))

    # Use './/' for robust nested counting
    return {
        "roads": cnt(".//road"),
        "geometries": cnt(".//geometry"),
        "laneSections": cnt(".//laneSection"),
        "lanes": cnt(".//lane"),
        "elevations": cnt(".//elevation"),
        "signals": cnt(".//signal"),
        "objects": cnt(".//object"),
    }


def ensure_import_paths():
    """
    Allows running from repo root without installing package.
    """
    # repo root assumed: directory containing this script
    here = Path(__file__).resolve()
    repo_root = here.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


# -----------------------------
# Main
# -----------------------------
def main():
    ap = argparse.ArgumentParser(description="Auto-vs-Auto domain gap experiment runner.")
    ap.add_argument("--ref-run", required=True, help="Path to reference run dir (previous pipeline run).")
    ap.add_argument("--cur-run", required=True, help="Path to current run dir (new pipeline run).")
    ap.add_argument("--out-dir", required=True, help="Output directory for experiment results.")
    ap.add_argument("--no-tiles", action="store_true", help="Do not use tiles even if folders exist.")

    args = ap.parse_args()

    ref_run = Path(args.ref_run).expanduser().resolve()
    cur_run = Path(args.cur_run).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    if not ref_run.exists():
        raise FileNotFoundError(f"ref-run not found: {ref_run}")
    if not cur_run.exists():
        raise FileNotFoundError(f"cur-run not found: {cur_run}")

    out_dir.mkdir(parents=True, exist_ok=True)

    ref_xodr = find_best_xodr(ref_run)
    cur_xodr = find_best_xodr(cur_run)

    ref_tiles = None if args.no_tiles else find_tiles_dir(ref_run)
    cur_tiles = None if args.no_tiles else find_tiles_dir(cur_run)

    # Basic validation + summary
    summary = {
        "ref_run": str(ref_run),
        "cur_run": str(cur_run),
        "ref_xodr": str(ref_xodr),
        "cur_xodr": str(cur_xodr),
        "ref_tiles": str(ref_tiles) if ref_tiles else "",
        "cur_tiles": str(cur_tiles) if cur_tiles else "",
        "ref_sha256": sha256_file(ref_xodr),
        "cur_sha256": sha256_file(cur_xodr),
        "ref_counts": xml_counts(ref_xodr),
        "cur_counts": xml_counts(cur_xodr),
    }

    # Save pre-run summary
    (out_dir / "experiment_summary_pre.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Import and run domain gap
    ensure_import_paths()
    try:
        from ultimate_pipeline.run_full_domain_gap import run_full_domain_gap  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Failed to import ultimate_pipeline.run_full_domain_gap.run_full_domain_gap.\n"
            "Make sure you run this script from the repo root (carla_-main) and your environment is correct.\n"
            f"Import error: {e}"
        )

    gap_out = out_dir / "domain_gap_results"
    gap_out.mkdir(parents=True, exist_ok=True)

    # If tiles are missing, pass empty string (matches your function signature)
    manual_tiles = str(ref_tiles) if ref_tiles else ""
    auto_tiles = str(cur_tiles) if cur_tiles else ""

    print("\n=== Experiment: Auto-vs-Auto Domain Gap ===")
    print("REF XODR:", ref_xodr)
    print("CUR XODR:", cur_xodr)
    print("OUT DIR:", gap_out)
    if ref_tiles and cur_tiles:
        print("Using tiles:", ref_tiles, "vs", cur_tiles)
    else:
        print("Tiles: disabled or missing -> running XODR-only gap")

    report = run_full_domain_gap(
        manual_xodr=str(ref_xodr),
        auto_xodr=str(cur_xodr),
        manual_tiles=manual_tiles,
        auto_tiles=auto_tiles,
        perception_manual_json=None,
        perception_auto_json=None,
        output_dir=str(gap_out),
    )

    # Save final summary + report
    summary["domain_gap_output_dir"] = str(gap_out)
    summary["domain_gap_report_keys"] = sorted(list(report.keys())) if isinstance(report, dict) else ["<non-dict>"]
    (out_dir / "experiment_summary_post.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Save the returned report too
    try:
        (out_dir / "domain_gap_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        # report may contain non-serializable objects; ignore
        pass

    print("\n✅ Done.")
    print("Pre-summary :", out_dir / "experiment_summary_pre.json")
    print("Post-summary:", out_dir / "experiment_summary_post.json")
    print("Gap output  :", gap_out)


if __name__ == "__main__":
    main()
