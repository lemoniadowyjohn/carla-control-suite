# GAP-010 RQ4 GNN train/eval leakage — root-cause fix, complete

Branch: `fix/gap010-rq4-leakage-complete-20260923` (worktree `G:/carla-gap010-complete-20260923`,
based on `origin/integration/production-large-map-20260918` @ `5d4ea9129966faaa91a05e9ae17409db1c081286`).

## 1. Confirmed the prerequisite is real (step 1)

`ultimate_pipeline/domain_gap_gnn/gnn_provenance.py` exists on the current production
tip (landed via GAP-011's restoration, commit `c68a1059`), is importable, and
`audit_leakage()` / `build_training_dataset_manifest()` are real, callable functions
(not stubs). Confirmed directly via `python -c "from ultimate_pipeline.domain_gap_gnn
import gnn_provenance as prov; ..."` in this worktree — see `VERIFICATION.json`,
`module_importable`/`audit_leakage_callable`/`build_training_dataset_manifest_callable`.

The prior Codex attempt (`fix/rq4-leakage-complete-20260923` @ `95d63b8a`) correctly
determined this was blocked at the time (`gnn_provenance.py` absent from production,
plus `cities/ingolstadt/manual_grid0821.xodr` and the historical training-tile set
absent from *that* checkout). That blocker is now resolved for the code side; see
§3 for what's still genuinely true about the data side.

## 2. Root cause (step 2)

`build_training_dataset_manifest(tiles_dir, ...)` (pre-fix) did:

```python
names = sorted(p.name for p in tiles_dir.glob("*.xodr") if p.is_file())
```

with **zero identity check** against known eval/reference maps. Every `.xodr` file
present in `tiles_dir` — including an accidental duplicate of a held-out evaluation
map — silently became training data. `MapTileDataset` had a filename-based
`exclude_names` mechanism (for deliberately held-out *named* tiles) but nothing
content-hash-based, so a duplicate under any filename was invisible to it too.
This is exactly how GAP-010's `source_map_identity_overlap` FAIL against
`cities/ingolstadt/manual_grid0821.xodr` (sha256 `69ee3498...42e8`) happened: the
eval file's bytes ended up counted as training data with no contract preventing it.

## 3. Data-side finding (important, re-verified independently — do not skip)

The prior Codex report stated `cities/ingolstadt/manual_grid0821.xodr` and the
historical training tile set (`reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/union_tiles`)
were **absent from the production git commit**. Independently re-confirmed: **true**
— neither path is tracked by git on `origin/integration/production-large-map-20260918`
(`git ls-tree` / `git show` both fail for these paths; both are explicitly
`.gitignore`'d, lines 272 and 288). This is real governed-data-outside-git, not a
checkout mistake.

However: **both files physically exist, untracked, on this machine** (in the
F-Drive-Audit checkout at `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main`)
— `cities/ingolstadt/manual_grid0821.xodr` (63MB, sha256 `69ee3498...42e8`, exactly
matching GAP-010's citation) and `reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/union_tiles/`
(562 real `.xodr` tiles, 344MB — the tile count matches the 2026-09-19
`DATASET_MANIFEST.json`'s `tiles_present_in_this_checkout: 562` exactly). These were
copied (not committed — both remain `.gitignore`'d) into the worktree to do real,
verified work instead of stopping at "governed data absent."

**Finding on the real union_tiles set, as-is:** `audit_leakage()` run against the
real 562-tile set and the real eval file returns **PASS** — this specific candidate
production dataset does **not** currently contain the leaking duplicate. The exact
historical directory/state that produced the documented 2026-09-19 FAIL is genuinely
gone (consistent with Codex's finding) — there is no live leaking dataset on this
machine to physically purge. "Rebuilding the split" is therefore moot for this
specific real dataset; it is already clean. The fix is verified against a
deliberately reconstructed worst-case using the same real bytes (§4), which is the
scenario the checker exists to catch regardless of which specific directory
triggered it historically.

## 4. Fix (step 3) — real code changes

All four files below are on `ultimate_pipeline/domain_gap_gnn/` (the live, imported
package — `submission/infrastructure/ultimate_pipeline/domain_gap_gnn/` is an
untouched mirror per this repo's own mirror-sync policy: only the designated
CRITICAL_MIRRORED_FILES get synced there, and this isn't one of them).

- **`gnn_provenance.py`**: new `exclusion_hashes_for(paths)` helper (SHA-256 of each
  existing path, skips non-existent paths without fabricating anything);
  `build_training_dataset_manifest()` gained `exclude_source_hashes=` — any tile
  whose content hash matches is skipped entirely (never hashed into `tile_hashes`,
  never a manifest entry, never fed to the graph builder). Backward compatible
  (new kwarg, default `None`, 3-tuple return unchanged).
- **`map_tile_dataset.py`**: `MapTileDataset` gained `exclude_source_hashes=`,
  parallel to the existing filename-based `exclude_names`; a hash match is recorded
  `EXCLUDED_BY_POLICY` (`reason="source_sha_excluded"`) in the same accounting
  system used for policy exclusions, so this is enforced at actual training-data-load
  time, not just in manifest bookkeeping.
- **`train_map_encoder.py`**: new `--exclude_source_xodr` (paths, nargs="*");
  hashed via `exclusion_hashes_for()` and threaded into both
  `MapTileDataset(...)` and `build_training_dataset_manifest(...)`.
- **`run_ksweep.py`**: the run's own eval pair (`--manual_xodr`/`--auto_xodr`) is
  **always** excluded automatically — no opt-in required; `--exclude_source_xodr`
  adds further protected reference paths (e.g. a distinct historical
  `manual_grid0821.xodr`). `_list_tiles()` filters the tile pool by content hash
  **before** `nested_subsets()` ever selects a K subset, so leaking content can
  never be chosen in the first place. The same exclusion set is forwarded to the
  `train_map_encoder.py` subprocess (defense in depth — the trainer independently
  re-enforces it on the dataset it actually builds) and to
  `_expected_manifest_for_subset()` so checkpoint-identity verification on both
  sides of the reuse check stays byte-identical. The exclusion set is also recorded
  in `ksweep_report.json` (`source_sha_exclusion_contract`) for auditability.

## 5. Verification (steps 1 + 6) — real, on real data

See `VERIFICATION.json` in this directory for the full machine-readable record.
Summary:

- Eval file hash re-confirmed: `69ee3498e0e7ca748dd5e342de10493dc4ece45a6b04cc34653f5917672c42e8`
  — matches GAP-010's citation exactly.
- Real union_tiles set (562 tiles) audited as-is: **PASS** (already clean, §3).
- Reproduction: 8 real union_tiles + a literal injected copy of the real eval file
  → pre-fix `audit_leakage()` = **FAIL** (`eval_pair_content_in_training_set` lists
  the exact hash) → same directory, same bytes, fix applied
  (`exclude_source_hashes=exclusion_hashes_for([EVAL_FILE])`) →
  `audit_leakage()` = **PASS**, `MapTileDataset` accounts the leak tile as
  `EXCLUDED_BY_POLICY`/`source_sha_excluded`, manifest entry count drops by exactly
  one (9 → 8). This is not a threshold change, not edited historical evidence, and
  the checker itself (`audit_leakage()`) was not touched.
- CLI-level (not just unit-level) verification: `run_ksweep.main()` executed for
  real end-to-end (`--k_values 3 4 --training_seeds 42 --epochs 1
  --exclude_source_xodr <eval file>`) against a tiles_dir with 5 real tiles + 1
  injected leak copy — real subprocess call to `train_map_encoder.py`, real
  `MapEncoder` training, real checkpoints saved, real `compute_whole_map_latent_gap`
  metrics computed. `ksweep_report.json`'s `source_sha_exclusion_contract.excluded_hashes`
  contains the eval file's real SHA-256; the leak tile was dropped from the pool
  before any K subset was ever formed (`[ksweep] source-SHA exclusion (GAP-010):
  dropped 1 tile(s) ...`).
- Regression: `tests/unit/test_rq4_gnn_provenance.py` (39 tests),
  `ultimate_pipeline/tests/unit/test_map_tile_dataset.py` (included in the 39),
  `tests/unit/test_domain_gap_gnn.py`, `tests/unit/test_run_gnn_pipeline_seed.py`,
  `ultimate_pipeline/tests/unit/test_gnn_checkpoint_epoch_selection.py`,
  `ultimate_pipeline/tests/unit/test_latent_gap_runner.py` — all pass unmodified
  (no test was weakened or removed to make this pass). Notably
  `test_train_and_ksweep_share_canonical_config_builders` (GAP-015's originally
  failing test) passes on this clean tip — GAP-015 was already stale on
  production, matching the GAP-013/GAP-014 pattern (artifacts of the messy
  WIP-lineage branch, not the clean line); not further investigated here as it's
  out of this task's scope.
- Full bare `pytest` (all 12 `testpaths` dirs): see the top-level report handback
  for the exact final counts (run separately, evidence attached to the git commit).

## 6. Retrain feasibility (step 5) — BLOCKED_EXTERNAL for the full K-sweep specifically

**No currently-trusted RQ4 result needs to be invalidated by this fix.** The only
historical checkpoint on record (`c21_seed42_epoch50`, referenced in
`HISTORICAL_PROVENANCE_CLASSIFICATION.json`) was already labelled
`LEGACY_UNBOUND_CHECKPOINT` (no manifest, not authoritative) for independent
reasons predating this fix — the OC-51 cryptographic-provenance contract
(`gnn_provenance.py`) that would let a checkpoint claim `VERIFIED_CRYPTOGRAPHIC_PROVENANCE`
only landed 2026-09-19, and no real training run has completed under it and been
checked into evidence yet, pre- or post-fix. So this fix closes the *mechanism*
(the exclusion contract is real, wired, and independently verified above) without
needing to retroactively invalidate any RQ4 number currently cited as verified,
because none currently is.

**Full production K-sweep retrain was attempted-and-assessed, not silently
skipped.** Real timing benchmarks on this machine (CPU-only torch 2.9.1+cpu,
`torch.cuda.is_available()==False`), using real tiles from the real 562-tile set:

- `train_map_encoder.py` on 10 real tiles (spanning the real size distribution,
  0.01–7.66MB): 2 epochs → 37.8s; 7 epochs → 65.3s → marginal **5.5s/epoch at
  K=10**, ~26.8s fixed per-run overhead (dataset + manifest graph builds).
- Whole-map latent-gap graph build (real `manual_grid0821.xodr`, 49189 nodes /
  76948 edges, matching `run_ksweep.py`'s default `--manual_xodr` scale): **12.6s**
  per graph; `_compute_metrics()` needs two such builds (manual + auto) per run.

Extrapolating linearly (optimistic — larger real tiles at higher K could scale
worse than linear) to the actual production defaults (`K_VALUES = [10, 20, 30, 40,
50, 60, 72]`, `DEFAULT_TRAINING_SEEDS = [42, 43, 44]`, `epochs=50`):

```
per_run(K)  ≈ (26.8 + 50 * 5.5) * (K/10) + 25.2   [train + eval, seconds]
total       ≈ Σ_K  3 * per_run(K)
            ≈ 3 * (30.18 * (10+20+30+40+50+60+72) + 25.2*7)
            ≈ 3 * (30.18 * 282 + 176.4)
            ≈ 3 * 8687.2
            ≈ 26,061 s  ≈  7.2 hours (CPU-only, single run, this machine)
```

**~7.2 hours (likely a lower bound) for one full production K-sweep is not
practical to run to completion and independently verify within this task/session.**
Per the task's explicit instruction, this is reported as **BLOCKED_EXTERNAL** for
the full-retrain step specifically, with the precise reason and numbers above,
rather than either skipped silently or replaced with a token/toy retrain presented
as equivalent. A live CLI-level smoke test *was* run to completion (§5, K=3/4,
1 epoch, real MapEncoder/checkpoints) — that is explicitly a wiring/mechanism
verification, not a claim that it substitutes for the real K-sweep.

**What remains to fully close GAP-010 end-to-end**: launch the real
`run_ksweep.py` (production defaults) in a background/overnight job (~7+ hours,
CPU-only), then re-run `audit_leakage()` against the resulting real checkpoint's
training tile set to get a final honest PASS tied to an actual
`VERIFIED_CRYPTOGRAPHIC_PROVENANCE` checkpoint. The code and dataset-state
prerequisites for that run are now real and verified; only the CPU wall-clock
budget is the blocker.
