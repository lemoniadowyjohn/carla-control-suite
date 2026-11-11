# RQ4 pre-registration — DRAFT v3 (2026-11-05; not frozen, not run)

- **Supersedes:** the statistic, randomization and controls sections of `RQ4_PREREGISTRATION_DRAFT.md`
  (v2, same folder) and of the published `docs/reviews/SCI_CORRECT003_20261104/RQ4_STATISTICAL_EVALUATION_SPEC.md`
  (`e8218cf9`). Both stay unchanged as history.
- **Responds to:** GM-1R, `G:/audit/GEMINI_RQ4_METHOD003_20261105/REVIEW_v2.md`, verdict
  `METHOD_NOT_ACCEPTED_FOR_PREREGISTRATION`, with four conditions (traceability in section 9).
- **Author:** Claude. This is **not** self-accepted. A non-Claude re-review (v3 review) is required
  before freezing. No result, p-value, α or threshold is chosen here; `[OPERATOR]` fields are left
  for the operator.

## 1. Question, hypotheses, scope
- **Q:** Within one region (Ingolstadt), are the GNN embeddings of the auto-generated map and of the
  manual map at the **same places** differently distributed, beyond what composition (road mix,
  segmentation) explains?
- **Unit:** a spatial unit u (section 3) encoded as its own subgraph.
  a_u = the auto embedding; m_u = the manual embedding.
- **H₀^flip (primary randomization null), stated exactly (GM-1R §4.2):**
  - (i) for every unit u, the pair (a_u, m_u) is exchangeable: (a_u, m_u) =ᵈ (m_u, a_u);
  - (ii) the pairs are independent across the **randomization units** (blocks, section 5).
  Under (i) and (ii), the 2^B block sign flips are equally likely, and the test is exact.
  H₀^flip is a statement about the two maps' representations at each location. It is **not** "no
  spatial correspondence" (that is a different null; section 5.3).
- **H₁:** the joint law of {a_u} differs from that of {m_u}.
- **Scope:** inference is conditional on this region, this map pair and these checkpoints. There is
  no population claim (`RQ4_INFERENCE_LIMITS.md`). A non-rejection is not evidence of similarity.

## 2. Data identity and pre-run blockers (any unmet → STOP; the result is NOT_RUN)
| Item | Requirement | Current state |
|---|---|---|
| Map pair | `[OPERATOR]`: historical Grid0821 (sha256 `69ee3498…72c42e8`) + candidate_connectivity_repaired (`c3dc29d3…995a7ca43`), or Grid0828 (`5eaece23…`) + the map-of-record (`370abbbb…`) | decision pending |
| Checkpoints | 5 seeds (42–46), located and identified by **sha256** | **BLOCKER:** the recorded path `G:\gap010-rq4-retrain-20260924\…` does not exist (verified 2026-11-05). Task CX-RQ4INV must find them by md5. If they are not found, a retrain under a new frozen protocol is required, and the historical 0.9207 cannot be re-examined with them. |
| Training tiles (562) | located, with a manifest and hashes | unknown (CX-RQ4INV) |
| Graph schema | `graph_schema_hash(width_mode)`, `normalize_embedding`, edge policy (`no_edge_when_junction_mediated`) recorded; training width mode confirmed (default `legacy`) | unrecorded |
| Spatial leakage | overlap of every training tile with the evaluation region; tiles over `[OPERATOR]`% overlap must be excluded from training, or the result is labelled `SPATIALLY_LEAKED` | unchecked (CX-RQ4INV) |
| Code SHA | the exact evaluation code commit | — |

## 3. Units and buffer
- **Grid cells** of side L `[OPERATOR, chosen in D2 before unblinding]`, restricted to the co-covered
  footprint.
- **Encoding:** each unit's graph-induced subgraph is encoded separately (the same scale as the
  training tiles).
- **Buffer:** nodes within **3 lane-graph hops** (GCN depth) of the unit boundary are excluded.
  Lanes crossing the boundary are `[OPERATOR: clipped | excluded]`; report the count.
- **Eligible:** both maps have ≥ `[OPERATOR: N_min]` nodes after the buffer. Report exclusions by
  reason.

## 4. Statistic (GM-1R condition 1)
- **Primary:** energy distance with the **Euclidean chord distance, α = 1**:
  `E = 2·E‖A−M′‖ − E‖A−A′‖ − E‖M−M′‖`, between the sets {a_u} and {m_u}. It is characteristic for
  distributions with a finite first moment (GM-1R §3.2–3.3).
- **Normalization (pre-registered; the operator confirms):** the default is **L2-normalized** unit
  embeddings, since the chord distance on the sphere is bounded, so the moment condition holds
  automatically. The raw-embedding analysis is a labelled sensitivity analysis (report max ‖z‖).
  The choice must not be changed after unblinding.
- **Seeds:** E is computed per seed under the **same** block flips and averaged:
  S = mean_seed E_seed.
- **Descriptive only:** cosine "energy" (= ‖μ_A − μ_M‖², a mean shift; GM-1R §3.4) and the
  historical whole-map cosine distance. **Never a primary or a confirmatory test.**
- **Secondary** (with Holm correction across the secondary family): Gaussian-kernel MMD² (bandwidth
  = the label-blind median pairwise chord distance, fixed before unblinding); a held-out linear
  domain probe on spatially disjoint block splits.

## 5. Randomization and dependence (GM-1R condition 2)
5.1 **Primary: block sign flips.**
- Partition the eligible units into B spatial blocks of side ≥ the autocorrelation range r̂
  estimated in D2 (label-blind).
- All units in a block flip together; randomize over the 2^B block signs (enumerate exactly if
  B ≤ 20; else `[OPERATOR: ≥ 9,999]` draws).
- p = (1 + #{S_perm ≥ S_obs}) / (1 + N_perm).
- **Report U, B, U_eff, the block size and the construction rule.**

5.2 **Sensitivity:** a table over ≥ 3 block sizes (r̂, 1.5·r̂, 2·r̂), plus a spatial block bootstrap of
S.

5.3 **Different null, labelled as such:** toroidal-shift / random rigid-transform ("spin") null of
**no spatial correspondence** between the two maps. Report it separately; never as a substitute for
H₀^flip.

5.4 **NOT_TESTABLE** if any of:
- `2^(−B) > α`;
- D2 cannot find a block size at which neighbouring blocks are below the dependence tolerance;
- D3 calibration fails;
- any mandatory control (section 6) fails to run.
If dependence cannot be removed, the sign-flip p-value is reported as **descriptive only**.

## 6. Composition controls (GM-1R condition 3; GM-1R §7.2 definitions)
**Composition covariates per unit** (computed from the XODR, label-blind):
- node count;
- lane count distribution;
- road type mix (where available);
- junction degree;
- connector vs ordinary road share;
- **U-turn connector share** (GAP-080: about 3,900 in the auto map);
- unit area;
- total lane length.

| Control | Status | Pre-registered form | Pass / interpretation |
|---|---|---|---|
| **C1** post-stratification | mandatory | strata from the covariates (quantile bins `[OPERATOR]`); E per stratum, fixed weights = the manual map's composition | report unweighted and matched results side by side; if the effect vanishes, it is composition-driven |
| **C2** composition-only baseline | mandatory | cross-fitted model ĝ(c) predicting z from the covariates (5-fold); test the residuals z − ĝ(c) | the observed S must exceed the composition-only null |
| **C3** composition-preserving surrogates | mandatory | B_s = `[OPERATOR: 1,000]` auto-map surrogates per unit: degree-preserving edge swaps on the lane graph, keeping class counts and unit sizes | S_obs above the 95th percentile of the surrogate null |
| **C4** composition dose-response (positive control) | mandatory | matched local geometry with deliberately changed composition (duplicate a road class; uniform lane-count change) | the statistic must respond; no response = an insensitive metric |
| **C5** pooling ablation | mandatory | pooling (mean as trained; mean + sd; max; node-cloud energy distance on {h_v}) | the effect only under mean pooling = a pooling artefact. **Primary pooling = mean (as trained).** |
| **C8** matched pairs | mandatory | match units on the covariates (optimal transport); paired statistic on matched units | report the matched U and |SMD| before and after (target < 0.1) |
| **C10** split-half end-to-end null | mandatory | the full pipeline on two disjoint halves of each map (and two same-generator regenerations, if available) | S_obs outside the split-half null |
| **C11** balance table | mandatory reporting | per-covariate means and distributions, auto vs manual, with standardized differences, U, U_eff | without adequate balance or adjustment, no structural claim |
| C6, C7, C9 | sensitivity | equal-, node- and area-weighted aggregation; unit-definition grid; within-stratum permutation | reported |

Also kept from v2:
- identity control (map vs itself → 0);
- shuffled-feature control;
- collapse check (effective dimension; the existing collapse guard must not be COLLAPSED).

## 7. Pre-unblinding sequence (GM-1R condition 4)
1. The data-identity blockers (section 2) are cleared and recorded.
2. Label-blind diagnostics are run:
   - D1: buffer survival per L;
   - D2: the correlogram and r̂, which choose L and the block size;
   - D3: the checkerboard-null type-I calibration;
   - D4: synthetic metric sanity, already shown numerically (cosine-energy = mean shift);
   - D7: B and the attainable p.
3. The operator fills every `[OPERATOR]` field.
4. A non-Claude v3 review returns ACCEPTED.
5. This file plus a JSON twin are committed append-only and hashed.
6. Only then is the auto-vs-manual contrast computed.

## 8. Reporting
- Report: S_obs; p or NOT_TESTABLE with the reason; per-seed E; U, B, U_eff; every control's
  result; C11; the exclusions; and Holm-adjusted secondaries.
- The historical 0.9207 [0.845, 0.976] stays unchanged, labelled "descriptive: five-seed
  whole-map cosine distance".
- The thesis-era K=1000 p<0.001 stays REPORTED_NOT_REPRODUCED.

## 9. Traceability to GM-1R
| GM-1R condition | Where addressed |
|---|---|
| 1. Euclidean chord, α = 1 primary; cosine descriptive; normalization pre-registered; moment check | §4 |
| 2. Exact H₀^flip; block flips / spatial nulls under dependence; block size pre-registered; U_eff | §1, §5 |
| 3. C1–C4 + C5, C8, C10 implemented; C11 balance mandatory | §6 |
| 4. Label-blind diagnostics run and the operator freezes parameters before unblinding | §7 |
| (§2 finding) GM-1 §3 withdrawn | acknowledged: v3 never relies on cosine "negative type" |
