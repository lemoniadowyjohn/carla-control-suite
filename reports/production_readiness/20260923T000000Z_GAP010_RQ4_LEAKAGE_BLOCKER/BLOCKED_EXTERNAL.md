# GAP-010 RQ4 leakage remediation — blocked-input record

Audited on 2026-09-23 against
`origin/integration/production-large-map-20260918` at
`d06995ec15ee07b9bfcc6671580394c3a5b03691`.

## Confirmed historical defect

GAP-010 records a real content-identity train/eval leak: the evaluation map
`cities/ingolstadt/manual_grid0821.xodr` (historical SHA-256 prefix
`69ee3498...42e8`) entered the training tile directory because the prior
provenance implementation enumerated every `*.xodr` without a source-hash
exclusion contract.  The checker must not be weakened and historical results
remain ineligible for verified research.

## Current reproducible blockers

The production commit does not contain enough governed input material to
rebuild the split, retrain, or produce an honest post-fix `audit_leakage()`
PASS:

* `cities/ingolstadt/manual_grid0821.xodr` is absent from the worktree and
  from `git lfs ls-files` (the only related tracked LFS input found is
  `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr`).
* `reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/union_tiles/` is absent.
* `reports/production_readiness/20260919_RQ4_GNN_PROVENANCE/LEAKAGE_AUDIT.json`
  is absent from the production commit.  GAP-010 references it, but the
  referenced evidence was not integrated with the code/data needed to
  reproduce it.
* The available training runtime is `torch 2.9.1+cpu`; `torch.cuda.is_available()`
  is `False` and `torch.cuda.device_count()` is `0`.

The preserved slice
`fix/rq4-gnn-provenance-leakage-v1-20260922@811008a3` was reviewed but is not
mergeable as a remedy: it adds provenance callers/tests that require
`MapTileDataset(width_mode=..., strict=...)` and corresponding graph-builder
APIs absent from this production baseline.  Cherry-picking it without its
unreviewed prerequisites makes the training entrypoint fail before a dataset
is built.  It also does not provide the missing source bytes or a retrained
checkpoint.

## Required external handoff

Provide a governed, content-addressed bundle containing:

1. the exact manual evaluation map and SHA-256;
2. the historical/replacement training-tile set and manifest;
3. affected checkpoint identities and training configuration; and
4. a viable training environment (GPU optional only if a bounded CPU retrain
   is explicitly accepted, but the input data is mandatory).

Then rebase a **self-contained** implementation that applies source-SHA
exclusion before both `MapTileDataset` construction and
`build_training_dataset_manifest()` in the trainer and K-sweep paths.  It
must rebuild the split, retrain affected checkpoints, and run
`audit_leakage()` over those actual bytes.  Until then GAP-010 remains open;
no RQ4 checkpoint or metric is promoted.
