#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Quick seam-artifact sanity checker.

Usage:
  python ultimate_pipeline/tools/check_seams.py <RUN_DIR>

Checks:
- adjacency JSON exists (tile_adjacency.json or tile_adjacency_fallback.json)
- seams_manifest.json exists
- counts directed adjacency edges and verifies lane_seam artifacts exist
"""

from __future__ import annotations

import glob
import json
import os
import sys
from typing import Any, List, Tuple

from ultimate_pipeline.utils.bootstrap import bootstrap_console

bootstrap_console()


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _iter_directed_edges(adj: Any) -> List[Tuple[str, str]]:
    """Normalize multiple adjacency formats into a directed edge list."""
    edges: List[Tuple[str, str]] = []

    if isinstance(adj, dict):
        # Format A: {"edges": [{"a": "...", "b": "..."}, ...]}
        if "edges" in adj and isinstance(adj["edges"], list):
            for e in adj["edges"]:
                if isinstance(e, dict):
                    a = e.get("a") or e.get("src") or e.get("from")
                    b = e.get("b") or e.get("dst") or e.get("to")
                    if isinstance(a, str) and isinstance(b, str):
                        edges.append((a, b))
                        edges.append((b, a))
            return edges

        # Format B/C: {tile: [neighbors...]} or {tile: {"neighbors":[...], ...}}
        for a, v in adj.items():
            if not isinstance(a, str):
                continue
            if isinstance(v, list):
                for b in v:
                    if isinstance(b, str):
                        edges.append((a, b))
            elif isinstance(v, dict):
                neigh = v.get("neighbors") or v.get("adjacent") or v.get("nbrs")
                if isinstance(neigh, list):
                    for b in neigh:
                        if isinstance(b, str):
                            edges.append((a, b))
        return edges

    return edges


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python check_seams.py <RUN_DIR>")
        return 2

    out_dir = sys.argv[1]
    seams_dir = os.path.join(out_dir, "seams")
    manifest = os.path.join(seams_dir, "seams_manifest.json")

    adj_path = os.path.join(out_dir, "tile_adjacency.json")
    adj_fallback = os.path.join(out_dir, "tile_adjacency_fallback.json")

    print("out_dir:", out_dir)
    if not os.path.isdir(out_dir):
        raise SystemExit("out_dir not found")

    if (not os.path.exists(adj_path)) and os.path.exists(adj_fallback):
        print("⚠ tile_adjacency.json missing; using fallback:", adj_fallback)
        adj_path = adj_fallback

    if not os.path.exists(adj_path):
        raise SystemExit("tile_adjacency(.json or _fallback.json) missing")

    if not os.path.exists(manifest):
        raise SystemExit("seams_manifest.json missing")

    adj = _load_json(adj_path)
    items = _load_json(manifest).get("items", [])
    edges = _iter_directed_edges(adj)

    lane_items = [it for it in items if isinstance(it, dict) and it.get("kind") == "lane_seam"]
    reports = glob.glob(os.path.join(seams_dir, "lane_seam", "*.json"))

    print("Adjacency directed edges:", len(edges))
    print("Manifest lane_seam items:", len(lane_items))
    print("lane_seam report files:", len(reports))

    if len(lane_items) == 0 or len(reports) == 0:
        raise SystemExit("No seam artifacts found → seam QA not operational.")

    print("OK: seam artifacts exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
