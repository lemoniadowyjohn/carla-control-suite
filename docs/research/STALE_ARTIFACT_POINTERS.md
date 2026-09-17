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

## Superseded: `reports/post_audit_hardening/THESIS_ITEM14_FRECHET_DISTANCE_RECOMPUTED.md`

That report's headline local-registration Frechet-distance figures (mean 55.28m / median
35.26m / p90 128.01m, 895 matched pairs) were computed against the map-of-record pin that was
current on 2026-08-27 (`744757f3...`), a one-off invocation with no dedicated, re-runnable
script committed for it. By 2026-09-17 the pin had moved 6+ promotions past that (current pin
`370abbbbb3...`), the same staleness pattern already found and fixed in
`scripts/regen_local_registration.py`.

For the **local (manual-footprint) Frechet-distance** number, that report is **superseded** by:

- **`scripts/regen_frechet_distance.py`** — new, re-runnable script; resolves the auto-side
  XODR via `ultimate_pipeline.carla_tools.map_registry.verify_pinned_map("auto_map_of_record")`
  instead of a hardcoded path, so this staleness cannot recur silently on future promotions.
- **`reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/frechet_distance.json`** — its output,
  regenerated 2026-09-17 against the current pin.

Re-run result: mean **58.18m** / median **36.13m** / p90 **140.48m**, **894** matched pairs
(hull footprint) — close to, not identical to, the original figures; see the 2026-09-17 update
in `docs/research/THESIS_TO_CURRENT_PROGRESS.md`'s RQ2 row for the full comparison and caveats.
The original report's methodology description (crop/reproject/match/resample/Frechet-DP steps)
remains accurate; only its headline numbers are stale.

## Related context

- `docs/research/THESIS_TO_CURRENT_PROGRESS.md` — tracks which whole-map runs are current.