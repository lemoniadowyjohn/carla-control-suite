# Statistical null and sampling plan (forward-looking; nothing here has been run)

| RQ | Quantity | Sampling unit | Null / control | Uncertainty | Minimum to claim |
|---|---|---|---|---|---|
| RQ1 | canonical structural hash per run (id-free sorted tuples of road geometry, lanes and links) | full pipeline run on the same pinned inputs | none needed: identity is binary; any difference is a counterexample | report k identical of N; N ≥ 3 per stage boundary (01, 06, 07) | "structurally identical in N/N runs at stages 01/06/07" |
| RQ2 | lane_width_gap, curvature_gap, density ratios | spatial tiles inside the footprint (e.g. 250 m), not whole maps | (a) split-half within the auto map; (b) split-half within the manual map; (c) the same metrics on two independently authored manual maps, if available | tile-block bootstrap (resample tiles; 2,000 replicates) | gap > upper 95% of the within-map null, reported for **both** hull and bbox footprints, with and without junction connectors |
| RQ2 | completeness vs convention | matched centre-line segments (spatial matching, e.g. ≤ 3 m Hausdorff) | segmentation-invariant totals (lane-km, merged-junction count) | tile-block bootstrap | the "completeness" wording is allowed only if the length-weighted unmatched auto lane-km exceeds the convention-only expectation |
| RQ3 | per-route perceptual metric (e.g. feature-embedding distance, detection mAP difference) | **route** (or scene block of ≥ N s), paired auto vs manual at anchor-registered positions | the same metric between two passes on the **same** map (sim-noise null) | route-level paired bootstrap or permutation | gap > the same-map null; holdout anchors' registration error reported |
| RQ4 | cosine distance between domain embeddings | tile, then map/region | (a) within-domain distances (manual vs manual tiles; auto vs auto disjoint subsets); (b) **permutation test** of domain labels over tiles | report seed variability (5 values) separately from tile-level bootstrap or permutation p-value | permutation p < α with the null distribution shown; a multi-region claim needs ≥ 2 independent regions |
| RQ5a | mIoU on manual-map captures for a model trained on auto-map captures | route / scene block | train-on-manual, test-on-manual (in-domain ceiling); train-on-auto, test-on-auto | route-block bootstrap; seeds × routes reported separately | degradation with CI over routes; absent classes reported as absent |
| RQ5b | real-world shift | real sequences | in-domain sim reference | sequence-block bootstrap | needs a real dataset; until then NOT_RUN |

**General rules:**
- Do not bootstrap correlated frames.
- Do not pool seeds with maps.
- Pre-register α and the metric before running.
- Keep every historical value, and state the interpretation boundary next to it.
