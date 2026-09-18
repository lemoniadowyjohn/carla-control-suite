# ultimate_pipeline/domain_gap/tile_reporter.py
"""
Named entry point for tile-level domain-gap pairing and aggregation logic.

Re-exports the tile-pairing and per-tile structural-gap helpers from
run_full_domain_gap so that reviewers have a stable, importable reference
to the tile-reporting boundary.

Full extraction deferred (T-MODULARIZE-RUN-FULL-DOMAIN-GAP-001).
"""

from __future__ import annotations

from ultimate_pipeline.run_full_domain_gap import (  # noqa: F401 — public re-export
    _collect_unique_tile_pairs as collect_unique_tile_pairs,
    _compute_pairing_stats as compute_pairing_stats,
    _enforced_confidence as enforced_confidence,
    _combine_per_tile_structural_gap as combine_per_tile_structural_gap,
    _ensure_pairing_schema as ensure_pairing_schema,
)

__all__ = [
    "collect_unique_tile_pairs",
    "compute_pairing_stats",
    "enforced_confidence",
    "combine_per_tile_structural_gap",
    "ensure_pairing_schema",
]
