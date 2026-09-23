#!/usr/bin/env python3
# ultimate_pipeline/domain_gap_gnn/map_tile_dataset.py

from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

from torch.utils.data import Dataset
from torch_geometric.data import Data

from .gnn_provenance import sha256_file
from .graph_builder import MapGraphBuilder


# Tile accounting statuses (OC-51 §11). Every expected tile is classified;
# nothing is silently skipped in accounted mode.
STATUS_USED = "USED"
STATUS_EXCLUDED_BY_POLICY = "EXCLUDED_BY_POLICY"
STATUS_INVALID = "INVALID"


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
    - OC-51: strict/accounted mode classifies every expected tile as
      USED / EXCLUDED_BY_POLICY / INVALID and fails closed on INVALID.
      ``strict=True`` requires ``width_mode="polynomial"`` so the
      authoritative feature definition is unambiguous.
    """

    def __init__(
        self,
        tiles_dir: str,
        *,
        strict: bool = False,
        width_mode: str = "legacy",
        exclude_names: Optional[Sequence[str]] = None,
        exclude_source_hashes: Optional[Sequence[str]] = None,
    ):
        """
        Args:
            tiles_dir:
                Directory containing .xodr tile files.
            strict:
                If True, raise an error when an invalid tile is encountered
                (RESEARCH_STRICT, fail-closed). If False (default), invalid
                tiles are skipped (LEGACY_TOLERANT).
            width_mode:
                ``"legacy"`` reproduces historical PRE_FIX features;
                ``"polynomial"`` evaluates the full lane-width function.
                Strict mode requires ``"polynomial"``.
            exclude_names:
                Tile filenames deliberately excluded from training by policy
                (e.g. held-out test tiles). Recorded as EXCLUDED_BY_POLICY,
                never silently dropped.
            exclude_source_hashes:
                GAP-010 source-identity exclusion contract: SHA-256 hashes
                (e.g. from gnn_provenance.exclusion_hashes_for()) of known
                eval/reference maps that must NEVER become training data --
                any tile whose content hash matches one of these is
                classified EXCLUDED_BY_POLICY regardless of its filename.
                This closes the gap that let a duplicate of a held-out
                evaluation map (cities/ingolstadt/manual_grid0821.xodr)
                silently enter the training set by filename alone.
        """
        if strict and width_mode == "legacy":
            raise ValueError(
                "RESEARCH_STRICT dataset mode requires width_mode='polynomial'"
            )
        self.tiles_dir = tiles_dir
        self.strict = strict
        self.width_mode = width_mode
        self._excluded = set(str(n) for n in (exclude_names or []))
        self._excluded_hashes = set(str(h) for h in (exclude_source_hashes or []))

        all_files = sorted(
            f for f in os.listdir(tiles_dir) if f.endswith(".xodr")
        )

        self.files: List[str] = []
        self._skipped: List[str] = []
        self._records: List[Dict[str, object]] = []

        # Pre-validate graphs to ensure stable dataset length
        for fname in all_files:
            if fname in self._excluded:
                self._records.append(
                    {
                        "tile": fname,
                        "status": STATUS_EXCLUDED_BY_POLICY,
                        "reason": "excluded_by_policy",
                    }
                )
                continue
            path = os.path.join(tiles_dir, fname)
            if self._excluded_hashes and sha256_file(path) in self._excluded_hashes:
                self._records.append(
                    {
                        "tile": fname,
                        "status": STATUS_EXCLUDED_BY_POLICY,
                        "reason": "source_sha_excluded",
                    }
                )
                continue
            try:
                g = MapGraphBuilder.build_from_xodr(
                    path, strict=bool(strict), width_mode=str(width_mode)
                )
            except Exception as exc:
                if strict:
                    self._records.append(
                        {
                            "tile": fname,
                            "status": STATUS_INVALID,
                            "reason": f"graph_build_failed: {exc!r}",
                        }
                    )
                    raise RuntimeError(
                        f"Failed to build graph for {path}: {exc!r}"
                    ) from exc
                self._skipped.append(fname)
                self._records.append(
                    {
                        "tile": fname,
                        "status": STATUS_INVALID,
                        "reason": "graph_build_failed_skipped_legacy_tolerant",
                    }
                )
                continue

            if g is None:
                if strict:
                    self._records.append(
                        {
                            "tile": fname,
                            "status": STATUS_INVALID,
                            "reason": "graph_build_returned_none",
                        }
                    )
                    raise RuntimeError(f"Failed to build graph for {path}")
                self._skipped.append(fname)
                self._records.append(
                    {
                        "tile": fname,
                        "status": STATUS_INVALID,
                        "reason": "graph_build_returned_none_skipped_legacy_tolerant",
                    }
                )
                continue

            self.files.append(fname)
            self._records.append(
                {
                    "tile": fname,
                    "status": STATUS_USED,
                    "reason": "",
                    "node_count": int(g.num_nodes),
                    "edge_count": int(g.edge_index.shape[1]),
                    "feature_dim": int(g.x.shape[1]) if getattr(g, "x", None) is not None else -1,
                }
            )

        if not self.files:
            raise RuntimeError(
                f"No valid XODR graphs found in directory: {tiles_dir}"
            )

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, idx: int) -> Data:
        fname = self.files[idx]
        xodr_path = os.path.join(self.tiles_dir, fname)

        g = MapGraphBuilder.build_from_xodr(
            xodr_path, strict=bool(self.strict), width_mode=str(self.width_mode)
        )
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

    @property
    def accounting(self) -> List[Dict[str, object]]:
        """Per-tile USED / EXCLUDED_BY_POLICY / INVALID records (§11)."""
        return [dict(r) for r in self._records]

    @property
    def coverage(self) -> Dict[str, object]:
        """Coverage report: valid / expected (§11)."""
        n_used = sum(1 for r in self._records if r.get("status") == STATUS_USED)
        n_excl = sum(
            1 for r in self._records if r.get("status") == STATUS_EXCLUDED_BY_POLICY
        )
        n_invalid = sum(
            1 for r in self._records if r.get("status") == STATUS_INVALID
        )
        expected = len(self._records)
        return {
            "expected": int(expected),
            "used": int(n_used),
            "excluded_by_policy": int(n_excl),
            "invalid": int(n_invalid),
            "valid_fraction": (float(n_used) / float(expected)) if expected else 0.0,
            "strict_mode": bool(self.strict),
            "width_mode": str(self.width_mode),
        }

    def summary(self) -> dict:
        """Return a lightweight dataset summary."""
        cov = self.coverage
        return {
            "tiles_dir": self.tiles_dir,
            "num_valid_tiles": len(self.files),
            "num_skipped_tiles": len(self._skipped),
            "strict_mode": self.strict,
            "width_mode": self.width_mode,
            "coverage": cov,
        }
