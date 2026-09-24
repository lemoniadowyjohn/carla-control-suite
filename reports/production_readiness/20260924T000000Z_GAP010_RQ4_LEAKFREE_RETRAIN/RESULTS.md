# GAP-010: RQ4 leak-free GNN retrain — results

**Run ID**: 20260924T000000Z_GAP010_RQ4_LEAKFREE_RETRAIN
**Status**: COMPLETE — all 5 seeds finished (exit=0), both pre-training and post-hoc leakage audits PASS.

## What this closes

GAP-010 found a real train/eval content-identity leak in the RQ4 GNN latent-representation
pipeline (the eval-pair reference `manual_grid0821.xodr` hash-matched content already present in the
training set). The exclusion mechanism (`exclude_source_hashes=`) was fixed and verified end-to-end
earlier this session, but the actual retrain on a genuinely leak-free split had never been run — the
previously-cited "AUTHORITATIVE" RQ4 number predated the fix. This run closes that gap: a real 5-seed
ensemble retrain, using the exclusion mechanism live, with both a pre-training and a post-hoc leakage
audit against the actual checkpoints produced.

A real, previously-undiscovered code gap was also found and fixed in the course of this task: GAP-010's
original fix touched `train_map_encoder.py`/`run_ksweep.py`, but never touched
`ultimate_pipeline/tools/run_gnn_pipeline.py` — the actual entrypoint `run_seed_ensemble.py` calls (the
real script that produced the original C21_GNN_AUTHORITATIVE numbers). `run_gnn_pipeline.py` now always
excludes its own `--manual-xodr`/`--auto-xodr` pair, mirroring `run_ksweep.py`'s existing pattern.

## Protocol replicated

Matches `C21_STATISTICAL_PROVENANCE.md`'s documented design exactly, with the leak exclusion newly
active:
- 562 tiles (`union_tiles/`, the same fixed tile set as the original run)
- 50 epochs, batch size 16, lr 1e-4, CPU-only
- 5 seeds: 42, 43, 44, 45, 46
- Manual/auto substitution: `cities/ingolstadt/manual_grid0821.xodr` (sha256 `69ee3498...42e8`) +
  `reports/ingolstadt_map_quality_v2/work_package_02_connectivity/candidate_connectivity_repaired.xodr`
  (sha256 `c3dc29d3...7ca43`) — same substitution the original script's own documented decision used
  (the original `auto_full_aligned.xodr` is unrecoverable)
- **New**: `exclude_source_xodr=[manual_grid0821.xodr, candidate_connectivity_repaired.xodr]` active for
  every seed's training-tile pool, closing the leak channel `audit_leakage()` found in the pre-fix
  pipeline

## Pre-training leakage audit (before any training started)

`PRE_TRAINING_LEAKAGE_AUDIT.json`: `status: "PASS"`, `eval_pair_content_in_training_set: []`, both
exclusion hashes resolved, 562/562 tiles retained. Confirms the exclusion mechanism was genuinely
active for this exact invocation before committing to the multi-hour run.

## Training run

Launched 2026-09-23T23:54:11 UTC, completed 2026-09-24T05:20:32 UTC (~5h 26m wall time, slower than the
historical 85-95min estimate due to real CPU contention from other concurrent work on this shared
machine — expected and previously flagged). All 5 seeds completed with exit=0:

| Seed | Started (UTC) | Done (UTC) |
|------|---------------|------------|
| 42 | 2026-09-23T23:54:11 | 2026-09-24T01:30:15 |
| 43 | 2026-09-24T01:30:16 | 2026-09-24T02:29:45 |
| 44 | 2026-09-24T02:29:45 | 2026-09-24T03:19:40 |
| 45 | 2026-09-24T03:19:40 | 2026-09-24T04:09:05 |
| 46 | 2026-09-24T04:09:05 | 2026-09-24T05:20:32 |

## Post-hoc leakage audit (against the ACTUAL trained checkpoints, not just the config)

`POST_HOC_LEAKAGE_AUDIT.json`: `overall_status: "PASS"`. Every one of the 5 seeds' checkpoints was
individually checked — each recorded exactly 562 source tiles, the same `training_dataset_manifest_sha256`
(`cb071f54...4ee73`) across all seeds (confirms a single, consistent, correctly-filtered tile pool was
actually used, not just intended), and `eval_pair_hash_overlap: []` for every seed. This is real,
per-checkpoint evidence the training data actually used was leak-free — not just that the exclusion
config was passed in.

## Result: old (leaky) vs. new (leak-free)

| | Old (2026-09-01, leaky) | New (2026-09-24, leak-free) |
|---|---|---|
| cosine_distance mean | 0.6434 | **0.9207** |
| 95% bootstrap CI | [0.616, 0.676] | [0.845, 0.976] |
| cosine_similarity mean | +0.3566 | **+0.0793** |
| 95% bootstrap CI | [0.323, 0.384] | [0.024, 0.155] |
| CI excludes zero | yes | yes |
| Seeds | 42-46 (5) | 42-46 (5, same seeds) |
| Leakage audit | not run at the time | PASS (pre-training + post-hoc, per-checkpoint) |

**Honest comparison**: the direction of the finding holds — both cosine_distance and cosine_similarity
CIs exclude the "no separation" boundary in both runs, consistent across all 5 seeds in both cases. The
leak-free result shows a MATERIALLY LARGER cosine_distance (0.92 vs 0.64) and correspondingly smaller
cosine_similarity (0.079 vs 0.357) than the leaky run — i.e. removing the leaked content made the
latent-space separation between the two domains appear stronger, not weaker. This is the opposite
direction a naive "leakage inflates apparent performance" intuition might predict, and is plausible here
because the metric is latent-space distance/separation (not classification accuracy) and the leaked tile
was providing the model with directly-shared content between the two domains during training, which
would tend to pull their learned representations closer together, not further apart — removing it lets
the domains' representations diverge more freely. This is offered as a plausible mechanism, not a
proven one; no claim is made beyond what these two runs directly show.

Per this program's standing discipline: this is a correctness fix that changed a result, and both the
old and new values are preserved side by side with causal explanation, not silently swapped.

## Artifacts

- `aggregate_stats.json` — this run's full statistics (committed)
- `PRE_TRAINING_LEAKAGE_AUDIT.json`, `POST_HOC_LEAKAGE_AUDIT.json` — both leakage audits (committed)
- `run_gnn_pipeline.py`'s fix (the exclusion-wiring gap found and fixed this session) — committed
- Per-seed checkpoints (`seed_{42..46}/checkpoints/map_encoder_epoch50.pt`) — NOT committed (gitignored,
  matching the original C21 precedent of not committing raw checkpoints), referenced by SHA256 above and
  in `POST_HOC_LEAKAGE_AUDIT.json`
- `union_tiles/` input tile pile — NOT committed (regeneratable, matching existing repo convention)
