# RQ1 + RQ4 offline scientific-evidence close (2026-09-24, additive post-thesis only)

`submission/` frozen evidence was not touched. Machine-readable record:
`RQ4_MASTER_CLOSE_VERIFICATION.json` (this directory).

## Final verdicts

- **RQ1_BOUNDED_POST08_UNEXERCISED**
- **RQ4_CLEAN_EXTENSION_SUPPORTED**

## RQ1 — why bounded, not fully re-verified

Prior state (2026-09-23, `reports/production_readiness/20260923_RQ1_REVERIFICATION/RESULTS.md`):
two fresh runs of current code through stage 08 are raw-diverging but
timestamp+`geometryFreezeHash`-normalized identical at every stage. Stages after
08 (`xodr_validator`, enrichment, tiling, final-artifact-authority receipt) were
never reached because the fixture was a single map tile that correctly fails
stage 08 fail-closed (39 broken lanes, dangling `elementId="526"`).

This pass: the only complete-input path (full-OSM bootstrap in
`G:/carla-rq1-extended-20260924`, branch
`docs/rq1-extended-determinism-coverage-20260924`) attempted 2 full runs at
2400 s timeout each — both timed out with **0 successful runs**
(`run.txt` tail: `ERROR: determinism run timed out after 2400s`, `Only 0
successful runs`, no `determinism_thesis_table.csv`). A concurrent extended run
in the main checkout (`reports/rq1_extended_smoke_20260924`, `--timeout-per-run
1800`) was observed in flight and deliberately not disturbed. A complete
self-contained input capable of passing stage 08 exists and is pinned
(map-of-record `..._20260916_232831.xodr`, sha256 `370abbbb...`, VERIFIED via
`verify_pinned_map('auto_map_of_record')`), but no N>=3 repeated run to final
artifact receipt completed in-session. Per the task contract ("no stage after
08 may remain unexercised if RQ1 is marked fully reverified"),
**RQ1_FULLY_REVERIFIED would be false**; the honest verdict is
**RQ1_BOUNDED_POST08_UNEXERCISED**.

## RQ4 — leak-free retrain discovered, verified, recomputed

The retrain was discovered in its isolated worktree
(`G:/gap010-rq4-retrain-20260924`, branch
`fix/gap010-rq4-leakfree-retrain-20260924`, base `a4d8a973`), not restarted:
at task start 4/5 seeds were complete with seed 46 running; seed 46 finished
2026-09-24T05:20:32Z (`ensemble_stdout.log`: `=== ALL SEEDS COMPLETE ===`).

- All 5 seeds COMPLETE, exit 0, 50 epochs, 562 tiles, provenance
  `VERIFIED_CRYPTOGRAPHIC_PROVENANCE`, training seeds 42-46 bound per
  checkpoint manifest, identical training config / model config / tile
  selection / dataset manifest (`cb071f54...`) across all seeds.
- `PRE_TRAINING_LEAKAGE_AUDIT.json`: PASS, empty eval overlap,
  `exclude_source_hashes=[69ee3498...42e8, c3dc29d3...79ca43]`.
- `POST_HOC_LEAKAGE_AUDIT.json`: overall PASS, tiles-dir audit PASS, all 5
  per-seed checkpoint source-hash checks OK (562 recorded tiles each, zero
  overlap with eval hashes).
- Minor blemish (not blocking): seed_43's sidecar records `git_sha UNKNOWN`
  (dirty-worktree describe failure in that subprocess); code identity is still
  pinned by identical config/selection/manifest hashes. GAP-010 fix commit
  `8f8d0c52` is an ancestor of both the retrain base and this checkout's HEAD.
- Ensemble recomputed independently from the five actual results (canonical
  `gnn_provenance.summarize_runs`, deterministic bootstrap seed=0, n_boot=2000):
  cosine_distance mean **0.9207**, std 0.0878, 95% bootstrap CI **[0.8446,
  0.9760]**; cosine_similarity mean 0.0793, CI [0.0240, 0.1554], excludes zero.
  The retrain dir's own `aggregate_stats.json` is byte-identical to this
  recomputation (verified, not trusted blindly).
- **Material difference, reported untuned**: the old pre-fix number was mean
  0.6434 CI [0.616, 0.676]. The new mean lies far outside the old CI and vice
  versa. The qualitative finding (positive latent separation, CI excludes zero
  on every seed) reproduces cleanly and more strongly; the quantitative value
  does not reproduce and the old 0.6434 must no longer be cited.
- No new permutation test was manufactured from n=5. The thesis K=1000
  p<0.001 was computed on pre-fix lineage and is not transferred.

Split: **A** (repeated-generation structural variability) = C15 evidence —
3 Osm2Odr runs structurally identical (CV effectively 0; no numeric thesis CV
threshold exists in `research/thesis_rq_contract.yaml`, so threshold comparison
is honestly N/A), natural DR absent, explicit DR via RealismAugmentor.
**B** (latent robustness/separation) = this leak-free 5-seed ensemble.

## Pointer updates made after independent review

- `docs/research/THESIS_TO_CURRENT_PROGRESS.md`: 2026-09-24 RQ4 retrain note;
  RQ4 row now cites the clean-extension number.
- `README.md`: RQ4 research-table cell + preamble updated.
- `reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/MASTER_GAP_REGISTER.{json,md}`:
  GAP-010 retrain residual closed (was `BLOCKED_EXTERNAL`).
- `docs/research/EVIDENCE_INDEX.md`: pointers to this directory and the
  retrain worktree evidence.
- `CHANGELOG.md`: 2026-09-24 close entry.
