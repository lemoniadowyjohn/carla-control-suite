# RQ4 pre-registration DRAFT (not frozen, not run)

Status: `DRAFT`. To be frozen by hashing this file (and a JSON twin) **after** external review and
operator fixing of the bracketed `[OPERATOR]` fields, and **before** any evaluation data are
unblinded. No value below is a result.

## 1. Question and hypotheses
- **Q:** Within one region (Ingolstadt), do GNN embeddings of the auto-generated map and the manual
  map of the **same places** differ in distribution?
- **H0:** for each spatial unit u, the pair (auto_u, manual_u) of unit embeddings is exchangeable.
- **H1:** the distribution of auto unit embeddings differs from that of manual unit embeddings.
- **Scope:** inference is conditional on this region, this map pair, and these encoder checkpoints.
  No population claim (see `RQ4_INFERENCE_LIMITS.md`).

## 2. Data identity (fixed before the run)
| Item | Value |
|---|---|
| Manual map | `[OPERATOR: Grid0821 sha256 69ee3498e0e7ca748dd5e342de10493dc4ece45a6b04cc34653f5917672c42e8, or Grid0828 sha256 5eaece23…]`. Choose one and justify. The historical RQ4 used Grid0821. |
| Auto map | `[OPERATOR: candidate_connectivity_repaired sha256 c3dc29d3f570d929cbe664961446ea76fd3b8c74b0f4668ade99a67995a7ca43 (historical), or the map-of-record 370abbbb…]` |
| Region | the intersection of the two footprints (polygon recorded and hashed) |
| Encoder checkpoints | 5 seeds (42-46), identified by **sha256** (to be computed; only md5 exists today) |
| Graph schema | `graph_schema_hash(width_mode=…)`, `normalize_embedding`, the edge policy, all recorded; the width mode is pre-registered `[OPERATOR: polynomial recommended]`. If it differs from training, the checkpoints must be retrained. |
| Code SHA | the exact commit of the evaluation code |

## 3. Units
- **Unit:** a spatial cell of size B × B `[OPERATOR: B; primary choice made from the diagnostics in
  RQ4_NULL_AND_EXCHANGEABILITY_DIAGNOSTICS.md, before unblinding the domain contrast]`.
- **Unit embedding:** the encoder applied to the **graph-induced subgraph** of each map inside the
  cell. These are separate forward passes, as for the training tiles.
- **Buffer:** nodes within **3 lane-graph hops** of the cell boundary are excluded before encoding.
  Lanes crossing the boundary are clipped at the cell edge, or excluded `[OPERATOR: pick one]`.
- **Eligible units:** cells where both maps have ≥ N_min nodes after the buffer `[OPERATOR: N_min]`.
  Report the count excluded per reason.
- **Clusters for permutation:** k × k adjacent eligible cells, with k chosen by the diagnostics;
  n_c = the number of clusters.

## 4. Statistic (one primary)
- **Primary:** the energy distance with Euclidean distance (α = 1) between the sets
  {z_auto,u} and {z_manual,u}, on L2-normalized embeddings, **averaged over the 5 seeds**:
  `S = mean_seed E_1(A_seed, M_seed)`.
- **Secondary** (labelled, with Holm correction across the secondaries):
  - (a) MMD² with a Gaussian kernel, bandwidth = the median pairwise distance of the **pooled,
    label-blind** embeddings, computed once before unblinding;
  - (b) a mean-shift test `‖μ_A − μ_M‖²` (explicitly "mean shift only");
  - (c) the held-out accuracy of a linear domain probe on spatially disjoint cluster splits.
- **Not allowed:** cosine-distance energy distance as the primary statistic (it is a mean-shift
  test; see the critique, M2).

## 5. Inference
- **Permutation:** a paired sign-flip at **cluster** level. For each cluster, all its units' labels
  are swapped together with probability ½. **The same flips are applied to all 5 seeds** before
  averaging.
- **Number of permutations:** exact enumeration if n_c ≤ 20; otherwise `[OPERATOR: N_perm ≥ 9,999]`.
- **p-value:** `(1 + #{S_perm ≥ S_obs}) / (1 + N_perm)`.
- **Significance level:** `α = [OPERATOR]`, fixed here before unblinding. **This draft does not
  choose α.**
- **NOT_TESTABLE rules (any one applies):**
  - `2^(−n_c) > α`;
  - the dependence diagnostic fails at the largest admissible k;
  - the within-domain null calibration fails (empirical type-I rate above `[OPERATOR: tolerance]`);
  - any negative control fails.

## 6. Controls (must all be run and reported; see the diagnostics file)
1. Identity: each map against itself, where S must be 0.
2. Within-manual split null, and within-auto split null (pseudo-domains from disjoint clusters).
3. Same-place reproducibility: two structurally identical regenerations of the auto map, S ≈ 0.
4. Label-shuffle null calibration (the empirical type-I rate).
5. Feature ablation (length/count features removed), node-composition-matched subsampling, and
   junction connectors excluded.
6. Collapse check: effective dimension and within-domain cosine (the existing collapse guard
   verdict must not be COLLAPSED).
7. A synthetic power check: injected equal-mean / different-spread differences must be detected by
   the primary statistic and **missed** by the cosine-energy statistic (a sanity check of M2).

## 7. Leakage pre-run checks (any failure → STOP)
- the content-SHA exclusion of both evaluation maps from training (as GAP-010);
- the **spatial overlap** of each of the 562 training tiles with the evaluation region: tiles with
  overlap > `[OPERATOR]` are listed, and the run proceeds only if the checkpoints were trained
  without them, or the result is labelled "spatially leaked";
- graph normalization fitted on the training split only, with its parameters hashed.

## 8. Reporting
Report all of the following:
- S_obs, the p-value (or NOT_TESTABLE with the reason) and n_c;
- the per-seed E_1 values;
- every control result and every exclusion count;
- every secondary result, Holm-adjusted.
Historical values (0.9207 [0.845, 0.976]; superseded 0.6434) are reported unchanged as
descriptive five-seed results.

## 9. Freeze procedure
1. External review (a different model family).
2. The operator fills the `[OPERATOR]` fields.
3. This file plus a JSON twin are committed append-only; their sha256 is recorded.
4. Only then are the evaluation embeddings computed.
