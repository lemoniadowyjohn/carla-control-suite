# Stale Artifact Pointers

This file provides pointers to superseded artifacts per the repo's mirror-sync policy.

## Superseded Whole-Map Metrics

`submission/results/structural_gap_run11/` is **superseded for whole-map metrics** by
`reports/production_readiness/20260915T101724Z_FRESH_DOMAIN_GAP_REGEN/` (merged 2026-09-15).

- `run_11`'s own `fit_metric_provenance` field already hints its geometry-RMSE fit was carried
  forward, not verifed.
- Several of `run_11`'s 0.0-valid-rate connectivity readings don't reproduce on the current pin.

## Full Framing and Caveats

For how to read the fresh numbers alongside the still-authoritative RQ2 local-comparison row, see
`docs/research/THESIS_TO_CURRENT_PROGRESS.md`.

## Policy Note

`submission/results/` itself is out of scope for mirror-sync modifications. Pointers are placed
outside `submission/` so that the sync pipeline can update references without touching the
submission directory structure.