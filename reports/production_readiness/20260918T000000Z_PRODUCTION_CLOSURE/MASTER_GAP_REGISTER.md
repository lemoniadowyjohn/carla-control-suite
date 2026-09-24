# Master Gap Register — Production Closure 20260918

Machine-readable version: `MASTER_GAP_REGISTER.json`. This file is kept in sync at each update.

Last updated: `2026-09-24T11:05:15Z`

| ID | Severity | Subsystem | Status | Fixing commit / owner |
|---|---|---|---|---|
| GAP-001 | P0 | tiling/large_map_package.py | **fixed** | c75fd8c9 (merged into integration/production-large-map-20260918) |
| GAP-002 | P0 | tiling/tile_fbx_generator.py | **fixed** | c75fd8c9 (merged into integration/production-large-map-20260918) |
| GAP-003 | P0 | main_pipeline.py / artifact authority | **fixed** | 22e3811c (merged into integration/production-large-map-20260918) |
| GAP-004 | P1 | geometry/geometry_math.py | **fixed** | 433143f7 (merged into integration/production-large-map-20260918) |
| GAP-005 | P1 | quality/check_lane_count_changes.py | **fixed** | e2befc36, merged f5333f3a and pushed to origin/integration/production-large-map-2026091... |
| GAP-006 | P0 | map_fixes/xodr_junction_links.py | **fixed** | 7d82a581 (merged into integration/production-large-map-20260918) |
| GAP-007 | P2 | tools/xodr_carla_hardener.py | **fixed** | fab0f8c7 (deleted rather than fixed, since unused; merged into integration/production-l... |
| GAP-008 | P1 | geometry authority -- architectural | deferred | afed7bcc6adcb5bd9 (found during P1 work package F) |
| GAP-009 | P1 | pipeline_stages/stage_09_tiling.py | **fixed** | c5b09591 (already on origin/integration/production-large-map-20260918) |
| GAP-010 | P0 | domain_gap_gnn / RQ4 GNN provenance | **fixed (fully closed, leak-free retrain complete)** | 4c2f0feb + fce9d794 (leak-free retrain), merged into origin/integration/production-large-map-20260918 |
| GAP-011 | P1 | integration debt -- unreconciled parallel-agent work | **fixed (a/b/c closed)** | 5 commits on fix/gap011-oc51-58-59-restoration-20260923, merged c68a1059 into origin/in... |
| GAP-012 | P2 | domain_gap/run_alignment_and_matching.py | **fixed** | f541c745 (merged 1c8caa2c into origin/integration/production-large-map-20260918) |
| GAP-013 | P2 | domain_gap/tile_grid_meta.py -- duplicate-module suspected | **closed (non-reproducible)** | Codex (initial finding, 2026-09-23), Claude subagent (final full-suite confirmation, 20... |
| GAP-014 | P2 | topology/junction_model.py -- test-pollution suspected | **closed (non-reproducible)** | Codex (initial finding, 2026-09-23), Claude subagent (final full-suite confirmation, 20... |
| GAP-015 | P3 | domain_gap_gnn -- RQ4 provenance | **closed (non-reproducible)** | unassigned; confirmed non-reproducible by coordinator, 2026-09-23 |
| GAP-016 | P2 | tests/unit/test_regen_find_final_xodr_hygiene.py -- obsolete test c... | **fixed** | 6e9fb064 (merged 1c8caa2c into origin/integration/production-large-map-20260918); a sec... |
| GAP-017 | P1 | live CARLA -- Grid0828/manual_grid0821 data-collection readiness | blocked_external | Codex (2026-09-22/23, multiple real attempts); Claude (2026-09-24, audio-mixer-disable ... |
| GAP-018 | P1 | UE4 cook readiness -- engine source access | in_progress (UE4 build) | user resolved the GitHub/Epic org-access issue directly; the build was then started and... |
| GAP-019 | P2 | domain_gap/DEM+elevation canonical sampling -- 8-issue cluster (Pac... | **fixed (7/8, 1 by design)** | fix/dem-elevation-canonical-sampling-v2-20260923, merged c68a1059 into origin/integrati... |
| GAP-020 | P2 | pipeline_stages/stage_09_positional_semantics.py + tiling -- scope-... | **fixed (split; store.py via GAP-011c)** | fix/building-multipolygon-fidelity-v3-split-20260923 (2 commits: 0473b280 scope-separat... |
| GAP-021 | P0 | osm/osm_to_xodr_wrapper.py -- CRS/projection authority | **fixed (corrected root cause)** | 870c56a2 (merged into origin/integration/production-large-map-20260918) |
| GAP-022 | P2 | ultimate_pipeline/tools/final_map_readiness_gate.py -- evidence bin... | **fixed (SHA256-bound)** | e6052360/23913504 (visual half, via fix/final-readiness-evidence-binding-v4-reconciled-... |
| GAP-023 | P2 | ultimate_pipeline/config/settings.py -- mtime authority | **fixed** | b09fd6e3 (merged into origin/integration/production-large-map-20260918 via fdf91aff) |
| GAP-024 | P0 | ultimate_pipeline/contracts/writer_lock.py -- multi-agent write-own... | **fixed** | b396191f (merged into origin/integration/production-large-map-20260918) |
| GAP-025 | P1 | ultimate_pipeline/artifacts/semantic_diff.py -- mutation-detection ... | **fixed** | 252432aa (merged into origin/integration/production-large-map-20260918) |
| GAP-026 | P1 | ultimate_pipeline/lanes/lanelink_builder.py + pipeline_stages/stage... | open (needs policy) | direct-dispatched Claude subagent (2026-09-24), lane-link/FBX readiness audit -- found,... |
| GAP-027 | P0 | ultimate_pipeline/main_pipeline.py -- MainPipeline class dedent crash (GAP-020 merge regression) | **fixed** | 4ddb7ced+b86d1170 (merged into origin/integration/production-large-map-20260918) |
| GAP-028 | P2 | tests/unit/test_blender_conversion_integrity.py -- FakeBlenderRunner machine-Blender dependence | **fixed** | 8cb1cd95 (branch fix/ci-closure-blender-writerlock-20260924; renumbered from GAP-027 post-upstream-collision) |
| GAP-029 | P1 | ultimate_pipeline/contracts/writer_lock.py -- fresh-lock partial-publication reader race | **fixed** | 1bc93eef (branch fix/ci-closure-blender-writerlock-20260924; renumbered from GAP-028 post-upstream-collision) |

Totals: 29 tracked, 22 fixed, 3 closed (non-reproducible), 1 deferred, 1 open, 1 blocked_external, 1 in_progress.

## Active open / blocked items (2026-09-24)

- **GAP-026 (P1, open)**: lane-link pose-continuity is a dead signal in `lanelink_builder.py`; needs a human policy decision before any fix is dispatched.
- **GAP-017 (P1, blocked_external)**: live CARLA RPC handshake still fails after audio-mixer-disable probe — blocks RQ3/RQ5a capture.
- **GAP-018 (P1, in_progress)**: Epic/GitHub access resolved; UE4.26 compile running (`G:\UnrealEngine_4.26_CARLA`), `UE4Editor.exe` not yet present; cook not yet attempted.
- **GAP-008 (P1, deferred)**: two geometry-authority packages; consolidation plan only (no RQ blocked directly).

See `MASTER_GAP_REGISTER.json` for full detail per issue (proof, affected files, consequence,
fixing commit, regression test, evidence artifact, residual risk). Updated after every subagent
handback per this program's integration discipline (Section 33).

## Historical notes (2026-09-18 discovery round)

- **GAP-006** (P0, fixed): `xodr_junction_links.py::_geom_end` returned start pose for arc/spiral/poly3 endpoints.
- **GAP-008** (P1, deferred): dual geometry-authority packages; cross-oracle agrees numerically but no shared imports prevent drift.
- **GAP-010/GAP-011**: see JSON and `reports/production_readiness/20260923_MASTER_CLOSURE_PLAN/PLAN.md` for the dependency chain.
