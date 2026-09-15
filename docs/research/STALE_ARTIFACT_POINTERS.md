# Stale Artifact Pointers

This file notes artifacts that are **superseded** for whole-map metrics. It does not
modify anything inside `submission/`; it only records pointers outside it.

## Superseded: `submission/results/structural_gap_run11/`

For **whole-map** domain-gap metrics, `submission/results/structural_gap_run11/` is
**superseded** by:

- **`reports/production_readiness/20260915T101724Z_FRESH_DOMAIN_GAP_REGEN/`**
  (committed via `418fd023`, merged into `integration/session-batch1-20260912` at `97c8ee81`)

Both directories are now committed in the repository:

- Superseded whole-map run:
  `submission/results/structural_gap_run11/` (unchanged, preserved)
- Superseding whole-map run:
  `reports/production_readiness/20260915T101724Z_FRESH_DOMAIN_GAP_REGEN/`
  (contains `full_report.json`, `aggregated_gap.json`, per-tile `gap_whole_*.json`,
  `summary.json`, `reproducibility_hash.json`, and the manual-tiles seeding manifest)

Use `20260915T101724Z_FRESH_DOMAIN_GAP_REGEN/` for any whole-map metric reading going
forward. The `structural_gap_run11/` directory under `submission/results/` is retained
because `submission/` is treated as frozen for mirror-sync purposes.

## Related context

- `docs/research/THESIS_TO_CURRENT_PROGRESS.md` — tracks which whole-map runs are current.