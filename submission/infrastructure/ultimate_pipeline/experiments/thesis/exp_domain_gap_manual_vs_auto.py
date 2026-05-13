#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Experiment: structural + (optional) perceptual domain gap (manual vs auto).

This is a thin CLI wrapper around `ultimate_pipeline.run_full_domain_gap.run_full_domain_gap`.

What it does:
 - Always computes **structural** gaps from XODR (CARLA-free).
 - Optionally computes **tile gaps** if you provide tile dirs.
 - Optionally computes **perception gap** if you provide *precomputed* perception-metrics JSONs.

Important detail:
 - `run_full_domain_gap()` compares perception metrics; it does NOT itself run CARLA to capture them.
   Use `ultimate_pipeline.perception.record_route` / `hpc/perception_runner_hpc.py` to generate metrics JSONs.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from ultimate_pipeline.run_full_domain_gap import run_full_domain_gap
from ultimate_pipeline.experiments.thesis.manual_refs import resolve_manual_town, assert_manual_auto_distinct


def _rotation_deg(transform: dict) -> float:
    c = float(transform.get("cos", 1.0))
    sn = float(transform.get("sin", 0.0))
    return math.degrees(math.atan2(sn, c))


def _translation_mag(transform: dict) -> float:
    tx = float(transform.get("tx", 0.0))
    ty = float(transform.get("ty", 0.0))
    return float(math.sqrt(tx * tx + ty * ty))


def _warn_alignment(transform: dict, manual_bbox: dict | None) -> dict:
    scale = float(transform.get("scale", 1.0))
    rot = _rotation_deg(transform)
    trans = _translation_mag(transform)
    extent = None
    if isinstance(manual_bbox, dict) and all(k in manual_bbox for k in ("min_x", "max_x", "min_y", "max_y")):
        try:
            extent = max(abs(float(manual_bbox["max_x"]) - float(manual_bbox["min_x"])),
                         abs(float(manual_bbox["max_y"]) - float(manual_bbox["min_y"])))
        except Exception:
            extent = None

    warnings = []
    if abs(scale - 1.0) > 0.01:
        warnings.append("scale_deviation_gt_1pct")
    if abs(rot) > 5.0:
        warnings.append("rotation_gt_5deg")
    if extent and trans > 0.2 * float(extent):
        warnings.append("translation_large_vs_extent")

    return {
        "scale": scale,
        "rotation_deg": rot,
        "translation_m": trans,
        "extent_m": extent,
        "warnings": warnings,
    }


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto-xodr", required=True, help="auto-generated map .xodr")
    ap.add_argument("--manual-xodr", default="", help="manual Ingolstadt map .xodr")
    ap.add_argument("--manual-town", choices=["Grid0821", "Grid0828"], default="", help="manual Ingolstadt reference (uses mapping)")
    ap.add_argument("--auto-tiles", default="", help="optional dir with auto tiles (contains .xodr tiles)")
    ap.add_argument("--manual-tiles", default="", help="optional dir with manual tiles")
    ap.add_argument("--perception-auto-json", default="", help="optional perception metrics JSON for auto map")
    ap.add_argument("--perception-manual-json", default="", help="optional perception metrics JSON for manual map")
    ap.add_argument("--out-dir", default="out_domain_gap")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.manual_town and args.manual_xodr:
        raise SystemExit("Use only one of --manual-town or --manual-xodr")
    if args.manual_town:
        manual_ref = resolve_manual_town(args.manual_town)
        manual_xodr = Path(manual_ref["manual_xodr_path"])
    else:
        manual_xodr = Path(args.manual_xodr)
    auto_xodr = Path(args.auto_xodr)
    if not manual_xodr.is_file():
        raise SystemExit(f"Manual XODR not found: {manual_xodr}")
    if not auto_xodr.is_file():
        raise SystemExit(f"Auto XODR not found: {auto_xodr}")
    hashes = assert_manual_auto_distinct(manual_xodr, auto_xodr)

    combined = run_full_domain_gap(
        manual_xodr=str(manual_xodr),
        auto_xodr=str(auto_xodr),
        manual_tiles=args.manual_tiles or "",
        auto_tiles=args.auto_tiles or "",
        perception_manual_json=args.perception_manual_json or None,
        perception_auto_json=args.perception_auto_json or None,
        output_dir=str(out_dir),
    )

    print(f"✓ Wrote domain gap outputs → {out_dir}")
    if isinstance(combined, dict):
        # Helpful for quick sanity
        print("Keys:", sorted(combined.keys()))

    run_meta = out_dir / "run_metadata.json"
    if run_meta.exists():
        try:
            data = json.loads(run_meta.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            data = {}
        data["manual_xodr_resolved"] = str(manual_xodr.resolve())
        data["auto_xodr_resolved"] = str(auto_xodr.resolve())
        data.setdefault("input_fingerprints", {})
        data["input_fingerprints"].update({
            "manual_xodr": {"sha256": hashes["manual_xodr_sha256"]},
            "auto_xodr": {"sha256": hashes["auto_xodr_sha256"]},
        })
        run_meta.write_text(json.dumps(data, indent=2), encoding="utf-8")

    align_path = out_dir / "alignment.json"
    if align_path.exists():
        try:
            alignment = json.loads(align_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            alignment = {}
        transform = alignment.get("transform", alignment) if isinstance(alignment, dict) else {}
        manual_bbox = alignment.get("diagnostics", {}).get("manual_bbox") if isinstance(alignment, dict) else None
        sanity = _warn_alignment(transform if isinstance(transform, dict) else {}, manual_bbox)
        (out_dir / "alignment_sanity.json").write_text(json.dumps(sanity, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
