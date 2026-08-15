# CODEX A2 (HIGH) — domain_gap_gnn characterization + verification (1506 LOC, 0 tests)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: ./.venv/Scripts/python.exe · UP_DISABLE_CARLA=1
MODEL: Codex 5.x HIGH (torch reasoning). Independent of A1/A3/A4.

## Problem
`ultimate_pipeline/domain_gap_gnn/` is real torch (GNN encoder, collapse check, latent-gap metrics) with ZERO
tests. It underpins research/thesis claims, so unverified code here is a direct overclaiming risk.

## Goal
Deterministic characterization tests that pin current behavior + confirm the train/infer paths RUN — WITHOUT a
real dataset and WITHOUT changing any algorithm.

## Steps
1. Inventory the public surface: `graph_builder.py`, `map_encoder.py`, `collapse_check.py`
   (`_pairwise_mean_cosine`, `_cross_mean_cosine`), `latent_gap_metrics.py`, `latent_gap_runner.py`,
   `map_tile_dataset.py`, `train_map_encoder.py`, `infer_tile_gaps.py`.
2. Add deterministic tests (fixed torch seed, tiny synthetic graphs, e.g. 20 nodes / 40 edges):
   - graph_builder: known node/edge tensor shapes + dtypes from a synthetic map dict;
   - map_encoder.forward: output embedding shape + determinism (same input→same output);
   - collapse_check: cosine helpers return values in [-1,1]; identical embeddings→~1.0; orthogonal→~0.0;
   - latent_gap_metrics: known value on a tiny fixture.
3. Smoke: run train_map_encoder / infer on a 20-node fixture for 1–2 steps → completes, produces a checkpoint /
   metric dict (mark slow/integration).
4. Findings report: what is now PROVEN vs still ASSUMED (feeds project RQ-status).

## Boundaries
- Tests + report ONLY. No algorithm/architecture change (ESCALATE_TO_CLAUDE if a test reveals a real bug).
- Keep tests fast + CPU-only + seeded; no external data/network.

## Deliverables / git
tests/unit/test_domain_gap_gnn_*.py; report reports/post_audit_hardening/A2_GNN_CHARACTERIZATION.md.
Atomic commits; push; local==remote; full suite green (+ new tests).
Verdict: GNN_CHARACTERIZED_GREEN | PARTIAL | BLOCKED_NEEDS_DECISION.
