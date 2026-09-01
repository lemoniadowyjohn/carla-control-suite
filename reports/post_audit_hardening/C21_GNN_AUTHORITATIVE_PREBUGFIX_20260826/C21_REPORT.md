# C21 — GNN latent gap: PROTOTYPE → AUTHORITATIVE. DONE.

> **SUPERSEDED 2026-09-01.** This run trained on a defective lane-connectivity graph:
> `graph_builder.py::MapGraphBuilder.build_from_xodr()` resolved lane-link edges to the source
> lane's own laneSection instead of the successor's actual location, so 99.8% of edges (972/974,
> measured on these exact training tiles) were self-loops rather than real connectivity (fixed at
> `92cf6178`). The retrained, current authoritative evidence — including a control test that
> isolates this bug's effect from an unrelated auto-map substitution — is at
> `reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/C21_REPORT.md`. This directory is preserved
> unmodified for audit history; do not cite the cosine numbers below going forward.

Both follow-up items from `C18_GNN_LATENT_GAP_REPORT.md`'s "Follow-up to reach AUTHORITATIVE" are
cleared: (1) one-sided/OOD training resolved by training on the **union** of both maps' tiles, and
(2) single-run-only resolved by a **5-seed ensemble** with a bootstrap 95% CI that **excludes zero**
(no-gap) — the bar the original C21 prompt itself set for AUTHORITATIVE.

## Setup
- **Grid0828 tiled**: 33 tiles (`TileExtractor.tile`, `tile_size=500.0, strict_semantics=False` —
  identical parameters to the auto map's regen; reused the offline, CARLA-free tiler directly rather
  than the full `stage_09_tiling` pipeline stage, whose tile-QA batch runner depends on live CARLA,
  currently broken — unrelated to GNN training data prep).
- **Union tile pool**: 529 auto + 33 manual = **562 tiles**.
- **5 independent training runs**, seeds 42/43/44/45/46, 50 epochs each, batch 16, lr 1e-4, CPU,
  `torch_deterministic=true`. One code change required: `run_gnn_pipeline.py` hardcoded `--seed 42`;
  parameterized (TDD, `tests/unit/test_run_gnn_pipeline_seed.py`).

## Per-seed results
| seed | epochs | final_loss | cosine_distance | cosine_similarity |
|---|---|---|---|---|
| 42 | 50 | 2.4036 | 1.1267 | −0.1267 |
| 43 | 50 | 2.4245 | 1.3281 | −0.3281 |
| 44 | 50 | 2.3727 | 1.1663 | −0.1663 |
| 45 | 50 | 2.3778 | 1.1112 | −0.1112 |
| 46 | 50 | 2.3670 | 1.0362 | −0.0362 |

All 5 runs `COMPLETE`, exit 0, zero errors across ~80 minutes total wall-clock.

## Aggregate (5-seed bootstrap, n=20000 resamples)
| metric | mean | std | 95% bootstrap CI |
|---|---|---|---|
| cosine_distance | **1.1537** | 0.1083 | **[1.0803, 1.2476]** |
| cosine_similarity | **−0.1537** | 0.1083 | **[−0.2445, −0.0803]** |

**CI excludes cosine_similarity = 0 (no-gap)** — direction and magnitude are consistent across all 5
independent seeds (no sign flips; range 1.04–1.33 for cosine_distance).

## Cross-validation against RQ1
The union-trained encoder's embeddings span **whole-map** tile coverage on the auto side (529 tiles,
full city) against **footprint-only** coverage on the manual side (33 tiles, Grid0828's extent) — an
asymmetric comparison closer in spirit to RQ1's whole-map scores than the footprint-matched local
ones. Current RQ1 numbers (`C14_RQ1_STRUCTURAL_GAP/local_registration.json`, hull footprint):

| aspect | value | scale |
|---|---|---|
| lane_width_gap | 0.042 | small — maps agree |
| curvature_gap / wasserstein | 0.22 / 0.075 | small–moderate |
| building_density_gap | 0.41 | moderate |
| road_length / junction / road_count ratio | 2.7–3.8× | **large** |

`cosine_distance ≈ 1.15` is a substantial fraction of cosine distance's [0, 2] range — in relative
magnitude this tracks much closer to the **large** road-network-completeness/building-density
findings than to the small lane-width agreement. **Qualitative reading**: the GNN's learned
separation is dominated by genuine structural/density differences, not contradicted by the one
aspect where the maps agree. This is a directional, not a formal statistical, correlation — no
per-tile paired data exists to compute an actual correlation coefficient, and the reasoning is
offered as corroborating context, not an independent proof.

## Thesis-tables + honesty-gate integration
`tools/export_thesis_tables.py::_gnn_row` now reads `aggregate_stats.json` first (falls back to the
old single-run `C18_GNN_LATENT_GAP` PROTOTYPE path if absent — preserves that behavior exactly, TDD
`tests/unit/test_export_thesis_tables.py`, 3 new tests incl. the CI-includes-zero → BOUNDED branch).
Cites the artifact's real sha256 (independently re-verifiable, not left `UNPINNED`).

Re-ran both honesty gates against the real regenerated `rq_tables.json`:
- `audit_thesis_topic_contract.py` — clean.
- `validate_thesis_claim_provenance.py` — **`ok=True`**, GNN claim `provenance=PASS via=direct_hash:aggregate_stats.json`
  (was `UNPINNED` before the sha256 fix).

648/648 full unit suite green.

## Verdict
`RQ3_GNN_UPGRADED cosine_distance_mean=1.1537 ci=[1.0803,1.2476] status=AUTHORITATIVE corroborates_rq1=yes(qualitative,directional)`
