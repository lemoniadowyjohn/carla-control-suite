# Draft analysis plan (to pre-register before the full capture; nothing has been run)

## RQ3 — perceptual domain gap (paired)
- **Primary metric:** `[OPERATOR: choose ONE before capture]`. Candidates:
  - (a) a distribution distance between per-frame feature embeddings (a fixed, pre-registered,
    frozen feature extractor), computed **per route** and then averaged;
  - (b) a semantic-label distribution distance per route (structure-dominated);
  - (c) the paired per-frame pixel metrics already implemented (`paired_metrics.json`), aggregated
    per route.
  The choice and the extractor's sha256 are frozen before capture.
- **Unit:** the route (or scene block). The primary statistic is the mean over routes of the
  per-route auto-vs-manual distance.
- **Null (simulator noise):** the same metric between **two passes on the same map**, with identical
  settings but a different TM seed (if seeds affect rendering), on the same routes. This is the
  same-map repeat null.
- **Inference:** a paired route-level comparison of the auto-vs-manual distance against the
  same-map repeat distance, using a route-level permutation or bootstrap (resampling routes;
  `[OPERATOR: N]` replicates).
- Report:
  - routes;
  - excluded frames with reasons;
  - the pairing residuals;
  - the stratum (if policy B).
- **Spatial holdout routes are excluded from RQ3** if they are reserved for RQ5 testing, or included
  `[OPERATOR: decide]`; the decision is recorded.
- **Sensitivity:** weather arms; the junction vs non-junction strata; the camera subset.
- **Interpretation boundary:** one region and one map pair; rendering and structure are separated
  only as far as §4 of the runbook allows.

## RQ5(a) — generated → manual transfer
- **Primary:** generated→manual mIoU degradation, frozen in v1.
- **Uncertainty:**
  - v1 frozen: a bootstrap over test frames (reported, labelled anti-conservative);
  - **proposed v2** (only if adopted before training): a bootstrap over test routes / scene blocks.
- **Per seed** [7, 17, 42]; mean ± CI across seeds.
- **Per class:** IoU with pixel support; absent classes reported as absent.
- **Leakage checks:** run before training, and they must pass:
  - the manual frame hashes are not in any train/val list;
  - the class weights come from generated-train only;
  - the spatial-holdout routes are not in the train/val splits.
- **Interpretation:** degradation is attributed to the map/representation gap only to the extent that
  RQ3's pairing and the rendering controls hold.

## RQ5b
`EXTERNAL_DATA`, per `rq5b_boundary`: labelled real data gives mIoU only where labels exist;
unlabelled data gives distribution distances only. No values until real data exists.

## Forbidden
Any p-value, interval or effect size before capture; test-set tuning; replacing missing frames;
silent re-splits; post-hoc metric choice.
