#!/usr/bin/env python3
# -*- coding: utf-8 -*-

r"""
One-shot script to create tiles from the manual reference map.

Run from project root:
    python -m ultimate_pipeline.dev_tools.tools.extract_manual_tiles \
      --manual_xodr cities/ingolstadt/manual_grid0828.xodr \
      --out_dir domain_gap_results/manual_tiles
"""

import argparse
import os

from ultimate_pipeline.tiling.tile_extractor import TileExtractor


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract manual XODR tiles for per-tile latent gap evaluation."
    )
    parser.add_argument(
        "--manual_xodr",
        default="cities/ingolstadt/manual_grid0828.xodr",
        help="Path to the manual full-map XODR file.",
    )
    parser.add_argument(
        "--out_dir",
        default="domain_gap_results/manual_tiles",
        help="Output directory for extracted manual tiles.",
    )
    parser.add_argument(
        "--tile_size",
        type=float,
        default=1000.0,
        help="Tile size in map units.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    manual_xodr = str(args.manual_xodr)
    out_dir = str(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    tiles = TileExtractor.tile(manual_xodr, out_dir, tile_size=float(args.tile_size))
    print(f"Manual tiles extracted: {len(tiles)} -> {out_dir}")


if __name__ == "__main__":
    main()
