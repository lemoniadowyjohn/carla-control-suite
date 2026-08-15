# A2 — domain_gap_gnn characterization (outcome)

Date: 2026-08-15 · Executor: Claude Opus 4.8 · Verdict: **GNN_CHARACTERIZED_GREEN**
`domain_gap_gnn` was 1506 LOC of real torch with **0 tests**. Added `tests/unit/test_domain_gap_gnn.py`
(12 deterministic CPU-only tests). No defect discovered — the core engine behaves as claimed.

## PROVEN now (locked by tests)
- `collapse_check._pairwise_mean_cosine`: L2-normalized pairwise cosine; identical rows → 1.0, orthogonal → 0.0,
  single row → 0.0.
- `collapse_check._cross_mean_cosine`: identical rows → 1.0, orthogonal → 0.0.
- `latent_gap_utils.combine_latent_gaps`: identical embeddings → all distances 0 / cosine_similarity 1;
  orthogonal → positive l2, cosine_distance 1; **fails closed (ValueError) on shape mismatch**.
- `latent_gap_utils._as_2d`: 1D → [1,D]; non-tensor → TypeError.
- `map_encoder.MapEncoder.forward`: output shape `[batch, out_dim]`; **deterministic** under eval+dropout=0;
  unit-norm when `normalize_embedding=True` (the metric-stability property the gap math relies on).
- `graph_builder.node_feature_dim` (positive int) and `_safe_float` (parses / falls back on bad input).

## Still ASSUMED (not yet exercised — needs data/fixtures, feeds RQ-status)
- `graph_builder.MapGraphBuilder.build_from_xodr` on a real XODR (needs a small XODR fixture).
- End-to-end `train_map_encoder` loop + `infer_tile_gaps` on real aligned tiles (needs the tiles dataset).
- Checkpoint load path `_load_model` / `load_encoder` (needs a saved checkpoint).
- `run_ksweep` sweep behavior.
These are integration paths; the underlying **math and encoder are now verified**, so the remaining risk is in
data wiring, not the metric definitions.

## Implication
The thesis's perceptual domain-gap **metrics** (cosine/latent distances, encoder determinism) are now trustworthy.
The end-to-end GNN pipeline on real maps still needs to be run with data (part of the perceptual/cook + capture arc).
