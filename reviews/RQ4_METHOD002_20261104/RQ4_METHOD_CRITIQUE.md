# RQ4-METHOD-002 — Method critique (2026-11-04)

**Type:** read-only methodological review. No experiment was run, no p-value was computed, and no
historical metric was changed. **Author note:** Claude wrote the published spec under review
(`docs/reviews/SCI_CORRECT003_20261104/RQ4_STATISTICAL_EVALUATION_SPEC.md` @ `e8218cf9`), so this
critique is **not** independent acceptance of either that spec or the new draft.

**Identity checks (contract §1):**
- repository `E:/wt/repair-map-realism-p0-837a8504`;
- remote `lemoniadowyjohn/carla-control-suite`;
- HEAD `1a36b560a69286841d4c42973cf00258a38f56c1`;
- 4 pre-existing untracked files, no tracked changes;
- docs branch `origin/docs/arch-x8-x9-review-20261104` = `e8218cf9419380835d4cbe45edde7f90ab54129f`.

**Verdicts:**
- the **published spec (`e8218cf9`): `NEEDS_METHOD_CHANGE`** (M2 below);
- the **new draft (`RQ4_PREREGISTRATION_DRAFT.md`): `METHOD_READY_FOR_EXTERNAL_REVIEW`**, with the
  pre-run data checks listed there.

## What the historical RQ4 number actually is (source facts, GITHUB_VERIFIED code @ `1a36b560`)

- **Evaluation** (`ultimate_pipeline/domain_gap_gnn/latent_gap_runner.py:128-145`): the **whole**
  manual map (`manual_grid0821.xodr`) and the **whole** auto map (`candidate_connectivity_repaired.xodr`)
  are each built as one graph (`MapGraphBuilder.build_from_xodr`) and encoded as a batch of one
  (`Batch.from_data_list([g])`). Then `combine_latent_gaps(z_m, z_a)` returns the cosine distance
  between **two vectors** (`latent_gap_utils.py:29-63`).
- **Encoder** (`map_encoder.py:62-94`): 3 × `GCNConv` with ReLU, dropout and residuals, then
  `global_mean_pool` over **all nodes of the map**, then a projection and an optional normalization.
  The receptive field is **3 hops** in the lane graph.
- **Training:** 562 union tiles, NT-Xent (temperature 0.5 default, `gnn_provenance.py:576`), 50
  epochs, 5 seeds.
- **Graph:** nodes are lanes; edges come from lane and road predecessor/successor links. Junction-
  mediated lane links get **no edge** (`graph_builder.py:55-58`).

## Findings

**M1 (fundamental): the historical metric has n = 1 per seed.** Each seed yields one distance
between two pooled vectors. The 5-seed interval [0.845, 0.976] describes **training stochasticity
of a single distance**. There is no sampling distribution over places or maps, so no inferential
statement about "separation" can be derived from it. Status: descriptive only. This is consistent
with the shared contract.

**M2 (published spec is wrong): cosine "energy distance" tests only the mean difference.**
- For L2-normalized vectors, `1 − cos(x, y) = ½‖x − y‖²`, a **squared** Euclidean distance.
- Energy distance `E = 2E d(X, Y) − E d(X, X′) − E d(Y, Y′)` characterizes equality of distributions
  only for `d = ‖·‖^α` with `0 < α < 2`.
- At α = 2: E‖X−Y‖² = tr Σ_X + tr Σ_Y + ‖μ_X − μ_Y‖², and E‖X−X′‖² = 2 tr Σ_X. So
  `E = 2‖μ_X − μ_Y‖²`, and with the ½ factor, **`E_cos = ‖μ_A − μ_M‖²`**.
- The published statistic therefore tests **H0: equal mean embeddings**, and has **no power**
  against domains that differ in spread, modality or shape but share a mean.

**Fix:**
- energy distance with **Euclidean α = 1** on the (normalized) embeddings, which is consistent
  against all alternatives with finite first moments; or
- **MMD with a characteristic kernel** (a Gaussian kernel, with the bandwidth fixed before
  unblinding).

One of them must be pre-registered as primary. A mean-difference test may be kept as an explicitly
labelled secondary test ("mean shift only").

**M3: exchangeability of deterministic representations.**
- The two maps are fixed artefacts, and no random label assignment generated them. A
  label-permutation test is therefore valid only **under a modelling assumption**: for each spatial
  unit, the auto and manual representations of that place are exchangeable.
- The p-value is conditional on that assumption, on the region and on the encoder checkpoint.
- Spatial blocking does **not** make units independent. The GCN mixes information over 3 lane-graph
  **hops**, not metres. Lane nodes are entire lanes and can be kilometres long (e.g. road 49556 is
  4.48 km in the RQ3 crop), so a node can span several blocks.
- **Consequence:** blocks must be **graph-induced subgraphs encoded separately**, as tiles are in
  training, not pooled slices of a whole-map embedding. The buffer must be defined in **hops**:
  exclude nodes within 3 hops of a unit boundary, or encode each unit's subgraph on its own.

**M4: training-tile vs evaluation-map mismatch.** The encoder is trained on tiles but evaluated
on whole maps. Mean pooling over a whole map is a different input scale and composition from a
tile. A tile- or cluster-level evaluation (M3) also removes this mismatch.

**M5: composition confounding through mean pooling.**
- `global_mean_pool` weights every lane node equally. The auto map contains many short connector
  lanes (3,949 U-turn connector roads in the 2026-09-16 map-of-record; per-direction twin roads).
- Any embedding difference may therefore reflect **segmentation and authoring convention**, not
  network structure.
- Required controls:
  - feature ablation (drop length and count-like features);
  - node-composition-matched subsampling;
  - the analysis repeated with junction connectors excluded;
  - a sensitivity check with length-weighted pooling (analysis only; the pooling the encoder was
    trained with is unchanged).

**M6: leakage beyond content hashes.**
- GAP-010 excludes the eval maps by content SHA. It does not exclude **spatially overlapping**
  training tiles from *other* maps of the same area. Grid0821 and Grid0828 are both manual
  Ingolstadt grids, and their overlap with the training tiles is unverified.
- Required pre-run check: the geographic footprint of each of the 562 tiles vs the evaluation area.
  Tiles that overlap by more than a pre-registered fraction are excluded, or reported separately.
  Graph normalization statistics are fitted on the training split only.

**M7: schema identity.** These are currently unrecorded or partial:
- width mode: not recorded; the default is `legacy` (`graph_builder.py:309`);
- `graph_schema_hash`;
- `normalize_embedding`;
- the edge policy;
- checkpoint identity: md5 only, sha256 is required.
All must be fixed and hashed before a run.

**M8: the thesis-era K=1000 permutation p<0.001** (`docs/research/THESIS_TO_CURRENT_PROGRESS.md:14`)
is REPORTED_NOT_REPRODUCED. Its unit and statistic are undocumented, and it predates the 2026-09-01
graph-builder fix and GAP-010. It must not be cited as support for 0.921 or for the new design.

**M9: seeds.** "The fraction of seeds with p < α" (published spec §5) is not a valid aggregate
inference. **Fix:** compute the statistic per seed under the **same** permutation of units, average
over seeds, and use the permutation distribution of the seed-averaged statistic. That gives one
test, and its seed robustness is reported descriptively.

**M10: when no valid p-value exists.** With paired sign-flips over n_c independent cluster units,
the smallest attainable p-value is 2^(−n_c). If 2^(−n_c) > α, or the pre-run dependence diagnostic
shows correlation at the largest admissible cluster size, the result is **NOT_TESTABLE**. That is
reported as such, never as "not significant" or as a pass.
