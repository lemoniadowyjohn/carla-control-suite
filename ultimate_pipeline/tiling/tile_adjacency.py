#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tile adjacency utilities.

Builds an adjacency graph between tiles based on their (i, j) indices
inferred from filenames 'tile_i_j.xodr'.

Graph format (JSON):
{
  "tile_0_0.xodr": {"index": [0, 0], "neighbors": ["tile_0_1.xodr", "tile_1_0.xodr"]},
  ...
}
"""

from __future__ import annotations

import os
import json
from typing import Dict, List, Tuple, Optional, Union


class TileAdjacency:
    """
    Build/load adjacency graph between tiles based on (i,j) indices.
    """

    _GRAPH_CACHE: Dict[str, Dict[str, Dict]] = {}

    @staticmethod
    def _parse_index(name: str) -> Optional[Tuple[int, int]]:
        """
        'tile_2_3.xodr' -> (2, 3)
        """
        base = os.path.basename(name)
        if not base.startswith("tile_"):
            return None

        core = os.path.splitext(base)[0]          # tile_2_3
        parts = core.split("_")                   # ["tile", "2", "3"]
        if len(parts) != 3:
            return None

        try:
            return int(parts[1]), int(parts[2])
        except ValueError:
            return None

    @staticmethod
    def build_graph(tile_paths: List[str]) -> Dict[str, Dict]:
        """
        Build adjacency graph using 4-neighborhood (N/S/E/W) on tile indices.
        """
        index_map: Dict[Tuple[int, int], str] = {}
        for p in tile_paths:
            ij = TileAdjacency._parse_index(p)
            if ij is not None:
                index_map[ij] = os.path.basename(p)

        graph: Dict[str, Dict] = {}

        for (i, j), name in index_map.items():
            neighbors: List[str] = []
            for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nb = (i + di, j + dj)
                if nb in index_map:
                    neighbors.append(index_map[nb])

            graph[name] = {"index": [i, j], "neighbors": neighbors}

        return graph

    @staticmethod
    def save_graph(graph: Dict[str, Dict], out_path: str) -> None:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(graph, f, indent=2)

    @staticmethod
    def load_graph(graph_path: str, *, use_cache: bool = True) -> Dict[str, Dict]:
        """
        Load adjacency graph JSON from disk.
        """
        graph_path = os.path.abspath(graph_path)

        if use_cache and graph_path in TileAdjacency._GRAPH_CACHE:
            return TileAdjacency._GRAPH_CACHE[graph_path]

        with open(graph_path, "r", encoding="utf-8") as f:
            graph = json.load(f)

        if not isinstance(graph, dict):
            graph = {}

        TileAdjacency._GRAPH_CACHE[graph_path] = graph
        return graph

    @staticmethod
    def are_adjacent(
        prev_tile_path: str,
        next_tile_path: str,
        graph: Union[str, Dict[str, Dict]],
    ) -> bool:
        """
        Check whether next tile is adjacent to prev tile according to a saved graph.

        Args:
            prev_tile_path: path or filename of previous tile
            next_tile_path: path or filename of next tile
            graph: either a graph dict, or a path to tile_adjacency.json

        Returns:
            True if adjacent, False otherwise.
        """
        prev_name = os.path.basename(prev_tile_path)
        next_name = os.path.basename(next_tile_path)

        if isinstance(graph, str):
            g = TileAdjacency.load_graph(graph)
        else:
            g = graph

        if not isinstance(g, dict):
            return False

        # Missing keys? Treat as not adjacent (safe default).
        if prev_name not in g and next_name not in g:
            return False

        # Undirected check (graph should be symmetric, but don't assume).
        prev_neighbors = g.get(prev_name, {}).get("neighbors", []) if isinstance(g.get(prev_name, {}), dict) else []
        next_neighbors = g.get(next_name, {}).get("neighbors", []) if isinstance(g.get(next_name, {}), dict) else []

        return (next_name in prev_neighbors) or (prev_name in next_neighbors)
