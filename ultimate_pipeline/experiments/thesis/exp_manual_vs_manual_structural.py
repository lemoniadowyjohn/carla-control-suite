#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Experiment: structural domain gap between manual Grid0821 and Grid0828 (sanity check)."""

from __future__ import annotations

import argparse
import json
import os
import math
from pathlib import Path

from ultimate_pipeline.run_full_domain_gap import run_full_domain_gap
from ultimate_pipeline.experiments.thesis.manual_refs import resolve_manual_town, assert_manual_auto_distinct
from ultimate_pipeline.tiling.tile_extractor import TileExtractor
from ultimate_pipeline.tiling.tile_metadata import TileMetadata


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="out_manual_vs_manual")
    ap.add_argument("--manual-tiles", default="", help="Optional manual tiles dir (if already generated)")
    ap.add_argument("--auto-tiles", default="", help="Optional auto tiles dir (if already generated)")
    ap.add_argument("--tile-size", type=float, default=1000.0)
    ap.add_argument("--tile-buffer-m", type=float, default=None)
    ap.add_argument("--alignment-rmse-max", type=float, default=50.0)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    m821 = resolve_manual_town("Grid0821")
    m828 = resolve_manual_town("Grid0828")
    manual_xodr = Path(m821["manual_xodr_path"])
    auto_xodr = Path(m828["manual_xodr_path"])
    hashes = assert_manual_auto_distinct(manual_xodr, auto_xodr)

    def _ensure_tiles(xodr_path: Path, tiles_dir: Path) -> str:
        tiles_dir.mkdir(parents=True, exist_ok=True)
        has_tiles = any(p.name.endswith(".xodr") for p in tiles_dir.glob("*.xodr"))
        if not has_tiles:
            TileExtractor.tile(
                input_xodr=str(xodr_path),
                out_dir=str(tiles_dir),
                tile_size=float(args.tile_size),
                tile_buffer_m=None if args.tile_buffer_m is None else float(args.tile_buffer_m),
            )
        meta_path = tiles_dir / "tile_metadata.json"
        if not meta_path.is_file():
            TileMetadata.generate_metadata(str(tiles_dir), str(meta_path))
        return str(tiles_dir)

    manual_tiles_dir = Path(args.manual_tiles) if args.manual_tiles else (out_dir / "tiles_manual")
    auto_tiles_dir = Path(args.auto_tiles) if args.auto_tiles else (out_dir / "tiles_auto")

    manual_tiles = _ensure_tiles(manual_xodr, manual_tiles_dir)
    auto_tiles = _ensure_tiles(auto_xodr, auto_tiles_dir)

    os.environ["UP_ALIGNMENT_RMSE_MAX"] = str(float(args.alignment_rmse_max))

    run_full_domain_gap(
        manual_xodr=str(manual_xodr),
        auto_xodr=str(auto_xodr),
        manual_tiles=manual_tiles,
        auto_tiles=auto_tiles,
        perception_manual_json=None,
        perception_auto_json=None,
        output_dir=str(out_dir),
    )

    alignment = {}
    align_path = out_dir / "alignment.json"
    if align_path.exists():
        alignment = json.loads(align_path.read_text(encoding="utf-8", errors="replace"))

    transform = alignment.get("transform", alignment) if isinstance(alignment, dict) else {}
    manual_bbox = alignment.get("diagnostics", {}).get("manual_bbox") if isinstance(alignment, dict) else None
    sanity = _warn_alignment(transform if isinstance(transform, dict) else {}, manual_bbox)
    if isinstance(alignment, dict):
        sanity["rmse_after"] = alignment.get("diagnostics", {}).get("rmse_after")
        sanity["rmse_before"] = alignment.get("diagnostics", {}).get("rmse_before")
        sanity["alignment_rmse_max"] = float(args.alignment_rmse_max)
    sanity.update({
        "manual_xodr": str(manual_xodr.resolve()),
        "auto_xodr": str(auto_xodr.resolve()),
        "manual_xodr_sha256": hashes["manual_xodr_sha256"],
        "auto_xodr_sha256": hashes["auto_xodr_sha256"],
    })
    (out_dir / "alignment_sanity.json").write_text(json.dumps(sanity, indent=2), encoding="utf-8")
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
    print(f"✓ Wrote manual-vs-manual outputs → {out_dir}")


if __name__ == "__main__":
    main()
