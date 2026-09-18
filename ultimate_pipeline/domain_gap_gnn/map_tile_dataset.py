#!/usr/bin/env python3
# ultimate_pipeline/domain_gap_gnn/map_tile_dataset.py

from __future__ import annotations

import os
from typing import List, Optional

from torch.utils.data import Dataset
from torch_geometric.data import Data

from .graph_builder import MapGraphBuilder


class MapTileDataset(Dataset):
    """
    Dataset of OpenDRIVE tiles converted to lane-level graphs.

    Design goals:
    - Deterministic loading (no augmentation, no randomness)
    - Robust to invalid / degenerate tiles
    - Suitable for self-supervised or contrastive learning
    - Suitable for reproducible latent-space analysis

    Notes:
    - Graph construction is delegated to MapGraphBuilder
    - Invalid tiles are filtered at initialization time
    """

    def __init__(self, tiles_dir: str, *, strict: bool = False):
        """
        Args:
            tiles_dir:
                Directory containing .xodr tile files.
            strict:
                If True, raise an error when an invalid tile is encountered.
                If False (default), invalid tiles are skipped.
        """
        self.tiles_dir = tiles_dir
        self.strict = strict

        all_files = sorted(
            f for f in os.listdir(tiles_dir) if f.endswith(".xodr")
        )

        self.files: List[str] = []
        self._skipped: List[str] = []

        # Pre-validate graphs to ensure stable dataset length
        for fname in all_files:
            path = os.path.join(tiles_dir, fname)
            g = MapGraphBuilder.build_from_xodr(path)

            if g is None:
                if strict:
                    raise RuntimeError(f"Failed to build graph for {path}")
                self._skipped.append(fname)
                continue

            self.files.append(fname)

        if not self.files:
            raise RuntimeError(
                f"No valid XODR graphs found in directory: {tiles_dir}"
            )

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, idx: int) -> Data:
        fname = self.files[idx]
        xodr_path = os.path.join(self.tiles_dir, fname)

        g = MapGraphBuilder.build_from_xodr(xodr_path)
        if g is None:
            # This should never happen due to pre-validation
            raise RuntimeError(
                f"Graph build failed at access time for {xodr_path}"
            )

        return g

    # --------------------------------------------------
    # Introspection helpers (useful for logging & thesis)
    # --------------------------------------------------

    @property
    def num_tiles(self) -> int:
        """Number of valid tiles in the dataset."""
        return len(self.files)

    @property
    def skipped_tiles(self) -> List[str]:
        """List of tiles skipped due to graph construction failure."""
        return list(self._skipped)

    def summary(self) -> dict:
        """Return a lightweight dataset summary."""
        return {
            "tiles_dir": self.tiles_dir,
            "num_valid_tiles": len(self.files),
            "num_skipped_tiles": len(self._skipped),
            "strict_mode": self.strict,
        }
