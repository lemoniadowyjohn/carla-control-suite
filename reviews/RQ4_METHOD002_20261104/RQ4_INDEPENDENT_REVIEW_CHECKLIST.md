# Independent review checklist for RQ4-METHOD-002 (for a different model family)

The reviewer runs these checks and records a command or derivation for each. The author (Claude)
cannot tick them.

## Facts about the historical metric
- [ ] Confirm from code at `1a36b560` that evaluation encodes each **whole** map as one graph
  (`latent_gap_runner.py:128-145`), and that the metric is a cosine distance between two vectors
  (`latent_gap_utils.py:29-63`). If this is wrong, the M1 critique must change.
- [ ] Confirm the encoder depth (3 × GCNConv) and the `global_mean_pool` (`map_encoder.py:62-94`).
- [ ] Confirm the junction-mediated edge policy (`graph_builder.py:55-58`). Check whether, on
  whole-map XODRs (which contain `<junction>`), incoming-road → connector edges exist in either
  direction. The author did **not** verify this.

## Mathematics
- [ ] Re-derive: with `d = 1 − cos = ½‖x − y‖²` on unit vectors, the energy distance equals
  `‖μ_A − μ_M‖²` (M2).
- [ ] Confirm that α = 1 Euclidean energy distance and a Gaussian-kernel MMD are characteristic
  (consistent against general alternatives), and state the conditions.
- [ ] Check that the seed-averaged statistic with shared sign-flips yields a valid permutation test
  under the stated H0.

## Design
- [ ] The buffer is defined in graph hops (3), not metres, and the unit embeddings come from
  separate subgraph encodings.
- [ ] The NOT_TESTABLE rules are complete (n_c, dependence, calibration, controls).
- [ ] The leakage checks include spatial overlap, not only content SHA.
- [ ] Composition controls are adequate for mean-pooling confounding.
- [ ] Every operator-set value (α, B, k-tolerance, N_min, overlap fraction) is a placeholder, not
  silently chosen.

## Integrity
- [ ] No p-value, threshold or result appears anywhere in the draft.
- [ ] The historical values are unchanged, and labelled descriptive.
- [ ] The published spec (`e8218cf9`) is not edited; corrections go in a new version.

Verdict options for the reviewer: `METHOD_ACCEPTED_FOR_FREEZE` / `NEEDS_METHOD_CHANGE`, with
reasons.
