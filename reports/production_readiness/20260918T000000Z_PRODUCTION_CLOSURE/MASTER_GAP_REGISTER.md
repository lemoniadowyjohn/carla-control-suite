# Master Gap Register — Production Closure 20260918

Machine-readable version: `MASTER_GAP_REGISTER.json`. This file is kept in sync at each update.

Last updated: `2026-09-29T22:00:00Z`

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
| GAP-018 | P1 | UE4 cook readiness -- engine source access | in_progress (editor build complete; CARLA project compile 65/73 modules, blocked on Eigen+OSM2ODR) | user resolved the GitHub/Epic org-access issue; direct-dispatched Claude subagent (2026-09-29) attempted the CARLA project compile for the first time, found+fixed 2 real CARLA build-script bugs |
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
| GAP-030 | P0 | ultimate_pipeline/carla_tools/map_registry.py + scripts/cook_full_grid_tiles.py -- registry receipt missing structured frame fields (O1 regression) | **fixed** | 655671fd (branch integration/o1-o20-rebased-20260929; verify_pinned_map() now surfaces rebase_dx/rebase_dy/frame_kind/etc from norm) |
| GAP-031 | P1 | tools/tile_frame_consistency.py (O3) + full-grid tile cook evidence -- latent ~170-270m north-south tile-seam misplacement | **checker fixed + merged** (5f826559); underlying generation-time defect still open (needs policy) | direct-dispatched Claude subagent (2026-09-29), 975a7de1 merged into origin/integration/production-large-map-20260918 via 5f826559 |
| GAP-032 | P1 | tools/rq3_pairing_preflight.py (O16) -- fail-open manual/automatic parity gap | **fixed** | 078b2f40 (branch integration/o1-o20-rebased-20260929), merged into origin/integration/production-large-map-20260918 via 4d8c64b8 |
| GAP-033 | P1 | tools/rq3_dataset_manifest_verifier.py (O17) -- fail-open default pairing skip | **fixed** | 078b2f40 (branch integration/o1-o20-rebased-20260929), merged into origin/integration/production-large-map-20260918 via 4d8c64b8 |
| GAP-034 | P1 | tools/rq5_contract_audit.py (O18) -- does not implement the RQ5(b) claim-boundary rule | **fixed** | 462ddeb3 (branch fix/gap034-rq5b-claim-boundary-20260929), merged into origin/integration/production-large-map-20260918 via bd1eb569 |
| GAP-035 | P1 | ultimate_pipeline/contracts/writer_lock.py -- load() leaked raw JSONDecodeError/TypeError instead of failing closed | **fixed** | 655671fd (branch integration/o1-o20-rebased-20260929; load() now wraps json.loads/from_dict in try/except -> RuntimeError; acquire() except clauses updated to match) |
| GAP-036 | P2 | PRODUCTION_MAP_QUALITY_CONTRACT.yaml -- no executing consumer | open (needs policy) | raised as NEW-209 by hardening/v5-incremental-20260929, independently re-verified (zero .py references on either ref) and logged 2026-09-29 |
| GAP-037 | P2 | waiver model cannot separate quality deviations from integrity defects | open (needs policy) | raised as NEW-210 by hardening/v5-incremental-20260929, independently re-verified (V5's new gates never reference "waiver") and logged 2026-09-29 |
| GAP-038 | P1 | ultimate_pipeline/tiling/carla_0916_import_process_contract.py + carla_0916_large_map_contract.py -- real, tested, but completely unwired closure modules (NEW-196/197-199) |
| GAP-039 | P2 | ultimate_pipeline -- NEW-225 capture re-use identity breach | **fixed** | <pending> |
| GAP-040 | P2 | ultimate_pipeline -- NEW-226 domain-gap ignored exit-code check | **fixed** | <pending> |
| GAP-041 | P2 | ultimate_pipeline -- NEW-227 exit semantics validation | **fixed** | <pending> |
| GAP-042 | P2 | ultimate_pipeline -- NEW-228 per-tile domain-gap timeout | **fixed** | <pending> |
| GAP-043 | P2 | ultimate_pipeline -- NEW-229 reproducibility verification | **fixed** | <pending> |
| GAP-044 | P2 | ultimate_pipeline -- NEW-230 manifest verifier compliance | **fixed** | <pending> |
| GAP-045 | P2 | ultimate_pipeline -- NEW-231 quality-gate-closer pass | **fixed** | <pending> |
| GAP-046 | P2 | ultimate_pipeline -- NEW-232 run_full_domain_gap() dict-vs-integer regression | **fixed** | <pending> |
| GAP-047 | P1 | ultimate_pipeline -- NEW-233 pipeline integration contract | **fixed** | <pending> |
| GAP-048 | P2 | ultimate_pipeline -- NEW-233 pipeline integration contract | **fixed** | <pending> |

Totals: 48 tracked, 37 fixed, 3 closed (non-reproducible), 1 deferred, 5 open, 1 blocked_external, 1 in_progress.

## Active open / blocked items (2026-09-29, updated post-V5-merge)

- **GAP-026 (P1, open)**: lane-link pose-continuity is a dead signal in `lanelink_builder.py`; needs a human policy decision before any fix is dispatched.
- **GAP-031 (P1, checker fixed + merged 2026-09-29, underlying defect still open)**: tile_frame_consistency.py's dead-code status field is fixed and now genuinely gates FAIL (27/31 pairs, confirmed on the real full-grid cook); the ~170-270m north-south tile-seam misplacement itself is still unfixed in tile_fbx_generator.py -- needs a real placement-correction design, not attempted per this program's discipline. Merge independently pytest-verified on production tip: 6402 passed, 6 skipped, 0 failed.
- **GAP-032/GAP-033/GAP-034 (fixed, 2026-09-29)**: RQ3 pairing-preflight/dataset-manifest-verifier fail-open bugs and the RQ5(b) claim-boundary rule are now fixed and merged (078b2f40 + 462ddeb3, via 4d8c64b8/bd1eb569). This table and this active-items list had drifted from `MASTER_GAP_REGISTER.json` (the JSON was updated by the fixing merges but this `.md` twin was not) -- found and corrected during the V5 merge below; a real, if minor, instance of the sync gap this file's own header warns against.
- **GAP-017 (P1, blocked_external)**: live CARLA RPC handshake still fails after audio-mixer-disable probe — blocks RQ3/RQ5a capture.
- **GAP-018 (P1, in_progress)**: Epic/GitHub access resolved; UE4.26 compile running (`G:\UnrealEngine_4.26_CARLA`), `UE4Editor.exe` not yet present; cook not yet attempted.
- **GAP-008 (P1, deferred)**: two geometry-authority packages; consolidation plan only (no RQ blocked directly).
- **GAP-036 (P2, open)**: `PRODUCTION_MAP_QUALITY_CONTRACT.yaml` declares quality gates/profiles but nothing in the codebase executes it (zero `.py` references, confirmed independently on both the production tip and the V5 branch); raised as NEW-209 by the V5 hardening closure.
- **GAP-037 (P2, open)**: the waiver model (single `allows_waived` boolean + process-only required fields) has no gate-class taxonomy, so it cannot structurally distinguish a waivable quality deviation from a non-waivable identity/integrity defect; V5's own new gates are unaffected today only because they never consult the waiver system at all (confirmed independently). Raised as NEW-210 by the V5 hardening closure.

See `MASTER_GAP_REGISTER.json` for full detail per issue (proof, affected files, consequence,
fixing commit, regression test, evidence artifact, residual risk). Updated after every subagent
handback per this program's integration discipline (Section 33).

## V5 incremental hardening merge (2026-09-29)

`hardening/v5-incremental-20260929` (9 commits: D16 fail-closed run-pack finalization, D17 strict provenance, D18 CI hardening -- pinned action SHAs, least privilege, timeouts, concurrency, D19 named repo-health release gates, J09/J10 dependency-extras split with no OpenCV provider in the base layer, E24 candidate-identity pre-runtime gate) merged into `origin/integration/production-large-map-20260918` via `--no-ff` merge commit `bc90751f` (parents `fa3214fc` and `2df5d6c6`). This is a separately numbered NEW-### workstream, not this repo's own GAP-### register; recorded here because it is now production code and because its own closure self-audit raised two real gap-register-worthy findings (GAP-036 from NEW-209, GAP-037 from NEW-210).

Independently re-verified before merging (not taken on the branch's word): diffed against the *current* production tip rather than the branch's stale fork point; `writer_lock.py` -- flagged as a real conflict risk because GAP-029/GAP-035 and this branch's D16/D19 both touch writer/finalization logic -- is untouched by this branch and the merge produced zero conflicts across all 41 files; read `finalize_run_pack.py`, `run_provenance.py`, `repo_health.py` and both caller sites (`main_pipeline.py`, `run_full_domain_gap.py`) in full; independently confirmed NEW-209 and NEW-210's core claims via `git grep` before logging GAP-036/GAP-037; read the CI workflow diffs and `pyproject.toml`'s dependency-extras layout in full; ran the FULL bare `pytest -q` suite from a clean worktree after the merge commit. Production advanced again (`fa3214fc` -> `bd1eb569`, the GAP-032/033/034 fixes) while that 31-minute run was in progress; re-fetched and merged cleanly (`546a3078`) rather than force-pushing, per this program's discipline.

**Independent full-suite pytest run** (bare `pytest -q`, worktree `G:/merge-v5-hardening-20260929`, commit `bc90751f`+`959a206c`): **6634 passed, 10 skipped, 0 failed**, 1876.49s (31m16s), zero `FAILED`/`ERROR` lines. Higher than V5's own self-reported 6497 passed/9 skipped because production had already absorbed the O1-O20 campaign and GAP-030/031/035 by the time this run started; on top of V5's own +233 net-new tests. This run predates the `546a3078` re-merge of GAP-032/033/034 (production moved from `fa3214fc` to `bd1eb569` while the 31-minute run was in progress). A second full re-run was not performed; instead a targeted re-run of exactly the new/changed surface from that drift was executed on the real post-merge worktree -- `pytest tests/unit/test_o16_rq3_pairing_preflight.py tests/unit/test_o17_rq3_dataset_manifest_verifier.py tests/unit/test_rq5b_claim_boundary.py -q`: 20 passed, 0 failed; plus `python -m compileall -q ultimate_pipeline tools tests` on the full post-merge tree: clean, exit 0. See `MASTER_GAP_REGISTER.json`'s `update_2026_09_29_v5_merge.full_suite_result_20260929_v5_merge` for the full detail and reasoning on why this narrower scope was judged sufficient rather than silently skipped.

A small follow-up fix (commit `959a206c`) corrected 2 real residual defects found by direct code reading during merge review (not delegated, too trivial to round-trip): stale `ultimate_pipeline/tools/dependency_conflicts.py` module-path comments in `requirements-ci.txt`/`requirements-desktop.txt` (the real owner is `dependency_conflicts()` inside `repo_health.py`), and `pack_lint.py`'s `pack_missing` defect code missing from its own `DEFECT_CODES` tuple. Both verified via an isolated `pytest ultimate_pipeline/tests/unit/test_pack_lint.py`: 19 passed.

V5's own evidence directory (18 receipts, SHA-256 manifested) is preserved unmodified at `reports/v5_incremental_closure/20260929T160422Z/`. Two external blockers documented there and correctly not attempted here: `BLOCKED_EXTERNAL_GITHUB_PERMISSION` (D18/NEW-206 -- no `gh`/token; exact `gh api` commands recorded in `D18_NEW_206.json`) and `BLOCKED_EXTERNAL_CARLA_RUNTIME` (E24/NEW-207 -- no live CARLA 0.9.16 server available). V4 closures NEW-196..NEW-199 remain absent from the canonical branch entirely; V5 neither regressed nor advanced them. This merge does not claim the system is production ready as a whole -- the reporting agent's own verdict was `V5_CLOSED_RUNTIME_BLOCKED`.

## Historical notes (2026-09-18 discovery round)

- **GAP-006** (P0, fixed): `xodr_junction_links.py::_geom_end` returned start pose for arc/spiral/poly3 endpoints.
- **GAP-008** (P1, deferred): dual geometry-authority packages; cross-oracle agrees numerically but no shared imports prevent drift.
- **GAP-010/GAP-011**: see JSON and `reports/production_readiness/20260923_MASTER_CLOSURE_PLAN/PLAN.md` for the dependency chain.
