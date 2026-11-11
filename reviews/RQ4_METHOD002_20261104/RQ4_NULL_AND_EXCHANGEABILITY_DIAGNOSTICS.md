# RQ4 null and exchangeability diagnostics (to run BEFORE unblinding the domain contrast)

These diagnostics use only **label-blind** or **within-domain** data. Their outputs fix B, k and the
NOT_TESTABLE decision **before** the auto-vs-manual statistic is computed. Nothing here has been run.

## D1. Receptive-field buffer (structural, no labels)
- Encoder depth L = 3 GCN layers, so the receptive field is 3 lane-graph hops
  (`map_encoder.py:62-64`).
- For each candidate B, report the fraction of nodes surviving a 3-hop boundary buffer, per map.
  Discard any B where either map keeps < `[OPERATOR]`% of its nodes.
- Report the length distribution of boundary-crossing lanes (they motivate clipping vs exclusion).

## D2. Spatial dependence (within-domain)
- For each map separately, compute unit embeddings for candidate B, and the correlogram of
  embedding similarity versus cell distance.
- Choose the cluster size k as the smallest k for which the correlation between neighbouring
  **clusters** is below `[OPERATOR]`.
- If no admissible k achieves this, the result is NOT_TESTABLE (critique M10).

## D3. Null calibration (type-I error)
- Split each map's clusters into two spatially interleaved pseudo-domains (a checkerboard of
  clusters).
- Run the full primary pipeline (same B, k, buffer and statistic), with permutations, many times
  over random checkerboard phases.
- The empirical rejection rate at α must be ≤ α + `[OPERATOR tolerance]`. If not, dependence
  remains, so increase k or declare NOT_TESTABLE.

## D4. Metric sanity (synthetic, no map data)
- Two synthetic samples on the unit sphere with **equal means and different spread**: the
  Euclidean α = 1 energy distance and the Gaussian MMD must detect them, and the cosine "energy"
  (= ‖μ_A − μ_M‖²) must not. This documents the M2 blind spot.
- Two samples with a **mean shift only**: all three detect it.
- Identical samples: all statistics ≈ 0.

## D5. Seed handling
- Confirm that the same sign-flips are applied to all seeds.
- Report the per-seed statistics and their spread; a single seed driving the average is flagged.

## D6. Exchangeability caveats (documented, not testable)
- The maps are deterministic artefacts; exchangeability is a modelling assumption about the
  representations of a place, not a property of a randomized design.
- Systematic coverage differences (one map lacks roads the other has) break exchangeability within
  a cell. Report per-cell node-count ratios, and exclude cells outside `[OPERATOR]` ratio bounds as
  a sensitivity analysis.

## D7. Minimum units
- Report n_c. If `2^(−n_c) > α`, the run is NOT_TESTABLE regardless of S_obs.
