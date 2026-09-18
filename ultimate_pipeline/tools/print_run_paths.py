#!/usr/bin/env python3
"""
Print helpful paths and suggested commands for latest runs (Windows-friendly).
"""

from __future__ import annotations

import os
from pathlib import Path
from ultimate_pipeline.tools.path_utils import repo_root, resolve_latest_run, norm_path_str


def main() -> int:
    root = repo_root()
    out_root = root / "ultimate_pipeline_out"
    manual_meta = root / "manual_maps" / "tiles_500m_b50" / "tile_metadata.json"
    manual_tiles = root / "manual_maps" / "tiles_500m_b50" / "tiles"

    print(f"RepoRoot: {norm_path_str(root)}")
    latest = None
    try:
        latest = resolve_latest_run(out_root, skip_names=["manual_baselines"])
        print(f"Latest auto run: {norm_path_str(latest)}")
    except Exception as e:
        print(f"Latest auto run: not found ({e})")

    print(f"Manual meta exists: {manual_meta.is_file()} ({norm_path_str(manual_meta)})")
    print(f"Manual tiles dir: {manual_tiles.is_dir()} ({norm_path_str(manual_tiles)})")

    if latest:
        corr_suggest = root / "eval_out" / "manual_auto" / "correspondence.csv"
        print("\nSuggested commands:")
        print(f"  python ultimate_pipeline\\tools\\evaluate_tiling.py --a-meta {norm_path_str(manual_meta)} --b-meta {norm_path_str(latest / 'tile_metadata.json')}")
        print(f"  $env:UP_TILE_CORRESPONDENCE_CSV = \"{norm_path_str(corr_suggest)}\"")
        print("  python ultimate_pipeline\\run_full_domain_gap.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
