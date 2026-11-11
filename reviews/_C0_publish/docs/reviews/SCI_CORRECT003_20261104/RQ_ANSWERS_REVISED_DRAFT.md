# Research questions: revised answers (DRAFT, 2026-11-04)

This draft revises `docs/research/RQ_ANSWERS_20261104.md` (committed at `1a36b560`, sha256
`a59f337f…`). It is meant to be published as a **new** file, with the old one kept. No historical
value is changed; corrected wording is marked **[corrected]**.

Provenance classes: GITHUB_VERIFIED, LOCAL_REPRODUCED, REPORTED_NOT_REPRODUCED, NOT_RUN, SUPERSEDED.

| RQ | Status | Answer (bounded) |
|---|---|---|
| RQ1 | **BOUNDED** | See below. Raw generation, normalization, structural signature and full-pipeline determinism are four separate claims. |
| RQ2 | **BOUNDED** | Hull and bbox results differ materially; "completeness" is not established. |
| RQ3 | **NOT_MEASURED** | No paired capture exists. |
| RQ4 | **BOUNDED** | 0.921 [0.845, 0.976] is seed variability for one named map pair, not evidence of separation. |
| RQ5a | **NOT_MEASURED** | Depends on RQ3 captures. |
| RQ5b | **DEFERRED (external data)** | No real-world dataset. |

## RQ1: determinism of OSM → OpenDRIVE
1. **Raw generation (Osm2Odr), structural:** 3 conversions of the pinned OSM gave identical
   aggregate signatures (32,920 roads, 3,717 junctions, total length 1,498,527.59 m) and 3 different
   byte hashes (`C15_RQ4_DOMAIN_RANDOMIZATION.json` `determinism_arm`). GITHUB_VERIFIED (summary);
   the 3 XODRs are **not published** (gitignored). **[corrected]** An aggregate signature (counts and
   total length) is necessary but not sufficient for topology/geometry identity.
2. **Timestamp normalization:** the normalizer is verified on string fixtures
   (`tests/unit/test_exp_osm_to_xodr_determinism_normalized.py`, 5 passed, 1 skipped).
   GITHUB_VERIFIED. That only timestamps differ between the 3 real outputs is
   REPORTED_NOT_REPRODUCED here, because the files are unavailable.
3. **Full pipeline and post-enrichment determinism:** NOT_RUN.
4. **[corrected]** Run `20261007_214826_524342` is **not** RQ1 evidence. Its input was the
   2026-09-16 map-of-record XODR (`INPUT_XODR` sha256 `370abbbb…`), so it is a post-processing
   (regeneration) experiment on an existing XODR, not an OSM conversion.
5. Natural domain randomization does not occur at the Osm2Odr stage (3 runs). Unchanged, with
   scope (1).

## RQ2: structural gap, auto map-of-record (`370abbbb…`) vs Grid0828 (`5eaece23…`)
Source: `reports/production_readiness/20260923_RQ2_REVERIFICATION/local_registration.json`.
GITHUB_VERIFIED.

| Measurement | Convex hull (default) | Bounding box | Whole map |
|---|---|---|---|
| lane_width_gap | **0.0597** | 0.0614 | 0.0415 |
| curvature_gap | **0.2206** | 0.2248 | 0.0931 |
| curvature Wasserstein gap | 0.0752 | 0.0743 | — |
| road-length ratio (auto / manual) | **2.683** (143,606.1 / 53,525.3 m) | **4.488** | — |
| road count (auto / manual) | 3,536 / 993 = 3.561 | 6,076 / 993 | 32,267 auto |

- **[corrected]** The 2026-11-04 text said "inside the hull … lane_width_gap 0.042, curvature_gap
  0.093". Those are the **whole-map** values; the hull values are 0.0597 and 0.2206.
- **[corrected]** The higher road length and count of the auto map are **not** independently shown
  to be completeness. *Hypothesis (untested):* Osm2Odr segmentation, per-direction twin roads and
  connector counts can inflate the counts. For scale: the map-of-record contains **3,949 U-turn
  connector roads** (`uturn_count.py`, ARCH-X8-X9), and GAP-080 counts **3,947 U-turn laneLinks** in
  the re-processed stage-05 file. Calling it "completeness" needs matched centre-line
  correspondence and segmentation-invariant measures.
- Junction-area metrics in the auto map are affected by GAP-070 and GAP-080 (lane-level
  discontinuities). Report RQ2 with and without junction connectors.
- The historical pin `…20260819_160350.xodr` is SUPERSEDED (replaced 2026-09-17).

## RQ3: NOT_MEASURED
The code and the auto-map crop exist (crop sha256 `b2bc2712…`, LOCAL_REPRODUCED). Missing:
- CARLA runtime (GAP-077);
- surveyed anchors (3 fit + 2 holdout);
- the trust root for admission.
No number exists, and none is implied.

## RQ4: learned latent separation (GNN)
- **Map pair [corrected]:** historical **Grid0821** (`cities/ingolstadt/manual_grid0821.xodr`, sha256
  prefix `69ee3498`) vs **candidate_connectivity_repaired** (sha256 prefix `c3dc29d3`). This is **not**
  the RQ2 pair.
- **Value:** cosine distance mean 0.921, percentile-bootstrap 95% interval [0.845, 0.976] over
  **5 training seeds** (0.905, 0.775, 0.967, 0.963, 0.994; std 0.088). GITHUB_VERIFIED (JSON);
  checkpoints are local (G:).
- **[corrected] Interpretation:** this interval describes **training-seed variability** for one map
  pair. It is not geographic uncertainty and not a test of separation. "CI excludes zero" carries no
  separation meaning on its own.
- **[corrected] Null tests:** a thesis-era K=1000 permutation test (p<0.001) is reported in
  `docs/research/THESIS_TO_CURRENT_PROGRESS.md:14`.
  - Its status is REPORTED_NOT_REPRODUCED: the permutation unit and the statistic are undocumented.
  - It predates the 2026-09-01 graph-builder fix and the GAP-010 leak fix, so it does **not** apply
    to the 0.921 leak-free retrain.
  - **No null exists for the leak-free retrain.** A separation claim waits for the design in
    `RQ4_STATISTICAL_EVALUATION_SPEC.md`.
- **Representation limits:**
  - junction-mediated edges are omitted (`graph_builder.py:55-57`);
  - *Hypothesis (inferred from defaults, unrecorded):* training used width mode `legacy`.
- 0.643 [0.616, 0.676] stays SUPERSEDED (GAP-010 train/eval leak).

## RQ5: NOT_MEASURED (RQ5a) / DEFERRED (RQ5b)
RQ5a needs the RQ3 captures. RQ5b needs a real-world dataset. The protocol freeze `db7155fe…` is
unchanged.
