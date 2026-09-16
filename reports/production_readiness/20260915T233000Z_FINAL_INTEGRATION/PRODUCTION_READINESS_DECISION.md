# Production Readiness Decision

**Date:** 2026-09-15T23:30:00Z
**Integration branch:** `integration/production-readiness-v2` @ `6f76f37f` (base, no merges yet)
**Map-of-record:** `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798` — VERIFIED, no accidental change

## Component Statuses

| Component | Status | Evidence |
|-----------|--------|----------|
| OpenDRIVE generation | VERIFIED | 60 tests + oracle 7e-07 |
| geometry | VERIFIED | 180 primitive tests, 0 fallback |
| topology | VERIFIED | 3561 junctions, 0 invalid |
| lanes | VERIFIED | lane continuity/width/lanelink PASS |
| DEM/elevation | PARTIALLY_VERIFIED | CRS PASS, DEM parity BLOCKED |
| regulatory semantics | NOT_TESTED | Not in this integration scope |
| classical domain gap | PARTIALLY_VERIFIED | 11 perturbations PASS, historical superseded, full map BLOCKED |
| GNN domain gap | PARTIALLY_VERIFIED | graph semantics PASS, leakage 0, collapse 9.2/12, Munich BLOCKED |
| FBX visual generation | PARTIALLY_VERIFIED | offline asset ready, UE not verified |
| UE import/cook | BLOCKED | Unreal not available |
| CARLA runtime | BLOCKED | CARLA server not available |
| manual-map runtime | BLOCKED | Grid0821/0828 blocked |
| perception capture | BLOCKED | CARLA blocked |
| cross-domain model training | BLOCKED | perception blocked |
| reproducibility/CI | PARTIALLY_VERIFIED | integration CI fixed, 1 P1 DEM provenance |

## Dependency-Aware Merge Order

1. `fix/geometry-crs-dem-correctness-v1-20260915` @ `bc6381b2` (geometry/CRS, no map mutation, 60+4 tests)
2. `audit/geometry-topology-oracle-v2-20260915` @ `46208a38` (read-only oracle, no code to merge, evidence only)
3. `audit/dem-crs-elevation-v2` @ `7f6d8efa` (forensic, read-only, evidence only)
4. `audit/domain-gap-gnn-scientific-v2` @ `d7f740ac` (read-only, with KDTree scalability fix for per-tile)
5. `chore/production-engineering-shell-v2-20260915` @ `a323a923` + `audit/evidence-integrity-v2` @ `3f7f6f5c` (CI/provenance hardening)
6. `fix/large-map-offline-hardening-v1-20260915` @ `540b5c5f` (tiling/FBX, but duplicate OC-1 content excluded — cherry-pick only tiling)

Semantic conflicts: none — OC-1 touches geometry/dem, oracle is read-only, DEM audit is read-only, domain-gap touches domain_gap/*, evidence-integrity touches artifact_locator (stale) — no overlapping production code.

## Verification Performed

- `pytest --collect-only` — 200+ tests collected, no collection errors after pRange/freeze fixes
- `git diff 6f76f37f..bc6381b2 --stat` — 6 code files, no map-of-record in diff
- `sha256sum campaigns/.../ingolstadt_perception_map_of_record_20260905_202847.xodr` — `2ca342d8` matches pinned
- Domain-gap reports: historical `0.0` correctly superseded by `1.0` (verified via independent recomputation)
- GNN: leakage 0, effective rank 9.2, not collapsed
- CI: `if: always()` removed, `integration/**` now triggers, 60 tests PASS

## Decision

**CONDITIONAL** — not global PASS.

- **VERIFIED for:** OpenDRIVE generation, geometry, topology, lanes (offline, no CARLA needed)
- **PARTIALLY_VERIFIED for:** DEM/elevation (CRS verified, raster parity blocked), classical/GNN domain-gap (within-map held-out verified, cross-city blocked), FBX offline asset, reproducibility/CI (1 P1)
- **BLOCKED for:** UE import/cook, CARLA runtime, manual-map runtime, perception capture, cross-domain training (all require CARLA/UE/runtime not available on this host)

No P0 open. 2 P1 open (DEM raster provenance, canonical diagnostics wrapper deferred).

**Next admissible task:** Independent review of UE backend and CARLA Grid0821/0828 RCA on host with CARLA 0.9.16 + UE, plus DEM raster vendoring to close provenance P1.

## Evidence Location

`reports/production_readiness/20260915T233000Z_FINAL_INTEGRATION/` — `FINAL_INTEGRATION_MATRIX.json`, `PRODUCTION_READINESS_DECISION.md`
