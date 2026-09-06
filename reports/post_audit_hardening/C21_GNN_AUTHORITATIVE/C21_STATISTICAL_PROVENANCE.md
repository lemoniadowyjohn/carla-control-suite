# C21 GNN latent-gap — statistical provenance & claim boundary

This documents the sampling/statistics behind `aggregate_stats.json` (the RQ4
`gnn_latent_cosine_distance` evidence). `aggregate_stats.json` itself is left
unmodified because its `sha256` is anchored in
`reports/post_audit_hardening/C19_THESIS_ASSEMBLY/rq_tables.json`
(`evidence_sha256`) and validated by `tools/validate_thesis_claim_provenance.py`;
this is an additive sidecar, not an edit to the anchored artifact.

## Training / sampling design (from `run_seed_ensemble.py`)

- **Tiles:** 562 `union_tiles` (both maps' road-network graphs combined —
  `reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/union_tiles/*.xodr`).
  Union-domain training resolves C18's one-sided-training OOD caveat.
- **Config:** 50 epochs, batch 16, lr 1e-4, CPU.
- **Seeds:** `[42, 43, 44, 45, 46]` (n = 5 independent training runs).
- **Metric:** cosine distance/similarity between the two domains' latent
  representations, computed per seed; mean + 95% bootstrap CI over the 5 seeds.

## Statistical claim boundary (auditor-added, 2026-09-06)

1. **This is an in-sample latent-separation *diagnostic*, not a held-out
   accuracy or generalization result.** The GNN is trained on the union of both
   maps' tiles and the domain separation is measured in the learned latent
   space; there is no separate held-out test split. That is appropriate for
   RQ4 ("can a latent representation support robustness analysis"), but it means
   the number must **not** be read as predictive accuracy or transfer (that is
   RQ5, which remains deferred). Because there is no train/eval split, the
   classical "tile-overlap leakage" question does not apply in the
   held-out-accuracy sense — but for the same reason the result cannot be
   promoted beyond a diagnostic.
2. **Small-sample caveat:** the 95% CI is a bootstrap over **n = 5 seeds**.
   Bootstrap CIs with n = 5 are fragile in the tails and should be read as
   indicative, not definitive. The robustness of the effect is better supported
   by the raw per-seed values — cosine_similarity `[0.382, 0.394, 0.296, 0.345,
   0.366]`, all clearly non-zero — and by the thesis's own K = 1000 permutation
   test (p < 0.001), which remains the *primary* statistical support for RQ4.
3. **Scope:** the C21 ensemble *strengthens* the thesis RQ4 result (multi-seed,
   union-domain robustness layer); it does not make RQ4 wholly new post-thesis
   work. See `docs/research/THESIS_TO_CURRENT_PROGRESS.md` (RQ4 row) and the
   `claim_boundary` on the `gnn_latent_cosine_distance` row in `rq_tables.json`.

The C21 numbers changed materially on 2026-09-01 after fixing a
graph-construction bug (lane-link edges resolved to their own lane section
instead of the successor's, making ~99.8% of training edges self-loops); the
pre-bugfix artifacts are retained separately under
`C21_GNN_AUTHORITATIVE_PREBUGFIX_20260826/`.
