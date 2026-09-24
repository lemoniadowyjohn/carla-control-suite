# Changelog

## 2026-09-24 documentation sync

- Corrected README RQ4 status: no longer citable as AUTHORITATIVE until a leak-free retrain reproduces the pre-GAP-010 numbers (aligns with `docs/research/THESIS_TO_CURRENT_PROGRESS.md`).
- Synced `MASTER_GAP_REGISTER.md` with `MASTER_GAP_REGISTER.json` (26 tracked issues including GAP-016/017/018; GAP-023 marked fixed after merge of `b09fd6e3`).
- Added gitignore rules for transient TILE_BASED_FBX probe reruns and local recovery/staging scratch scripts.

## 2026-09-18..2026-09-23 production-closure push

- Reconciled GAP-011 integration debt: restored and merged OC-35/38/39/40/41/42/43/46/51/58/59, RQ3 paired-capture contract, Semantic Organizer, and artifact-transaction packages onto `integration/production-large-map-20260918`.
- Closed or fixed most P0/P1 production gaps: final-artifact authority (GAP-003), junction endpoint geometry (GAP-006), RQ4 GNN train/eval leakage mechanism (GAP-010 fix, retrain still `BLOCKED_EXTERNAL`), OSM `proj_string` authority (GAP-021), perception evidence binding (GAP-022), writer-lock race (GAP-024), `semantic_diff` parent-vs-candidate mutation detect (GAP-025), mtime-authority guards (GAP-012/GAP-023).
- Re-verified RQ1 determinism and RQ2 local structural-gap numbers against the current map-of-record pin; RQ2 confirmed closed, RQ1 claim boundary unchanged with an open post-enrichment scope gap.
- Formalized GAP-017 (CARLA RPC handshake still fails after audio-mixer probe), GAP-018 (cook readiness), GAP-023 (settings mtime authority), GAP-026 (lane-link pose-continuity dead signal — needs a human policy decision).
- Master gap register and closure plan live under `reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/` and `reports/production_readiness/20260923_MASTER_CLOSURE_PLAN/`.

## 2026-09-06 stabilization

- Added thesis-immutable RQ1-RQ5 contract and provenance-bearing research table schema.
- Added canonical `up` CLI, scoped output handling, package wheel smoke coverage, and repository health packets.
- Added separate offline GitHub gates and self-hosted CARLA runtime workflow.
- Preserved R13 historical evidence while documenting cross-platform hash portability handling.
- Kept RQ3 and RQ5 explicitly deferred pending runtime and external-data evidence.
