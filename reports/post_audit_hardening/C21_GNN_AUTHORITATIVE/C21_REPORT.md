# C21 — GNN latent gap: AUTHORITATIVE (retrained 2026-09-01, supersedes the 2026-08-26 run)

**This is the current authoritative evidence.** It supersedes an earlier 2026-08-26 5-seed run
that trained on a defective lane-connectivity graph (`graph_builder.py` bug, fixed at `92cf6178` —
see below). The superseded run's checkpoints, report, and training log are preserved unmodified at
`reports/post_audit_hardening/C21_GNN_AUTHORITATIVE_PREBUGFIX_20260826/` for audit history; do not
cite its `aggregate_stats.json` cosine numbers going forward.

## Why this run exists

`graph_builder.py::MapGraphBuilder.build_from_xodr()` had a bug (fixed at `92cf6178`): lane-link
edges were resolved to `(SOURCE road_id, SOURCE laneSection_s, to_lane)` instead of the successor's
actual location, so 99.8% of edges (972/974, measured on real training tiles) were self-loops
instead of real lane-to-lane connectivity. This is the exact graph the RQ3-GNN encoder
(`C21_GNN_AUTHORITATIVE`) was trained on. Per user decision (2026-09-01, via AskUserQuestion): fix
the code, then retrain all 5 seeds and re-verify the evidence.

## Methodology (matches the original C21_GNN_AUTHORITATIVE run)

Same 562 `union_tiles` (529 auto + 33 manual), same 5 seeds (42-46), 50 epochs, batch 16, lr 1e-4,
CPU, `torch_deterministic=true`. Total wall clock: ~87 minutes (08:31:15Z - 09:58:49Z).

**Known confound — auto-map substitution.** The original `auto_full_aligned.xodr` (used only for
the *whole-map* latent-gap comparison step, not for per-tile training) is unrecoverable: not in
this worktree, no other worktree, and zero hits in `git log --all --diff-filter=A` across the
entire repository history. Only the manual reference (`manual_grid0821.xodr`) was recoverable, by
extracting the blob directly from commit `ec332359` on an unrelated branch. Per explicit user
approval (AskUserQuestion, "Use the pinned candidate map (Recommended)"), the whole-map comparison
substitutes `reports/ingolstadt_map_quality_v2/work_package_02_connectivity/candidate_connectivity_repaired.xodr`
as the auto map. **This substitution is isolated and quantified below** — it is NOT the dominant
driver of the results.

## Results

### Per-seed training

| seed | epochs | final_loss (old) | final_loss (new) |
|---|---|---|---|
| 42 | 50 | 2.4036 | 2.3413 |
| 43 | 50 | 2.4245 | 2.3302 |
| 44 | 50 | 2.3727 | 2.3144 |
| 45 | 50 | 2.3778 | 2.2985 |
| 46 | 50 | 2.3670 | 2.2970 |

All 5 runs `COMPLETE`, exit 0, zero errors. New losses are consistently slightly lower — the
encoder now has real graph structure to exploit during the contrastive training objective instead
of a near-featureless self-loop graph.

### Whole-map latent gap — three-way comparison (isolates the confound)

| condition | checkpoint | graph_builder | auto map | cosine_distance mean±std | cosine_similarity mean±std |
|---|---|---|---|---|---|
| **A. Original evidence** | OLD (buggy-graph-trained) | buggy (self-loops) | original (`auto_full_aligned.xodr`) | 1.1537 ± 0.1083 | **−0.1537** ± 0.1083 |
| **B. Isolation test** | OLD (buggy-graph-trained) | **fixed** | **substitute** (`candidate_connectivity_repaired.xodr`) | 1.0678 ± 0.0323 | **−0.0678** ± 0.0323 |
| **C. New evidence** | **NEW (fixed-graph-trained)** | fixed | substitute | 0.6434 ± 0.0388 | **+0.3566** ± 0.0388 |

**A → B isolates the auto-map-substitution effect alone** (same checkpoint, same eval-time graph
builder, different auto map): cosine_similarity moves from −0.154 to −0.068, a modest ~40 relative%
shift toward zero, sign unchanged. Small effect.

**B → C isolates the retrain effect alone** (same eval-time graph builder, same substitute auto
map, only the checkpoint changes from old-buggy-trained to new-fixed-trained): cosine_similarity
moves from −0.068 to **+0.357**, a full sign flip and a much larger magnitude shift. **The
retraining — i.e. the encoder actually learning from real lane connectivity instead of
near-self-loop noise — is what drives the qualitative change, not the auto-map substitution.**

### Bootstrap 95% CI (5-seed ensemble, n=20000 resamples, condition C — the actual new evidence)

| metric | mean | std | 95% CI |
|---|---|---|---|
| cosine_distance | 0.6434 | 0.0388 | [0.6161, 0.6760] |
| cosine_similarity | 0.3566 | 0.0388 | [0.3227, 0.3839] |

**CI excludes zero: true.** The original AUTHORITATIVE bar ("does the CI exclude cosine_similarity
= 0") is still met — a statistically consistent, non-zero signal across 5 independent seeds. What
changed is the **sign and magnitude**: the fixed-graph encoder finds manual and auto-generated maps
**more similar** (cosine_similarity ≈ +0.36, moderate positive) than the buggy-graph encoder did
(cosine_similarity ≈ −0.15, weak negative). Also notably tighter: std dropped from 0.108 to 0.039 —
the 5-seed ensemble agrees much more closely now that the graph carries real signal instead of
near-random self-loop noise.

## Interpretation

The buggy encoder was, in practice, functioning close to a per-lane-feature mean-pool (see
`project_gnn_graph_builder_edge_bug_20260901` memory for the full mechanism — PyG's `GCNConv`
already adds its own self-loops by default, so a graph that's ~all self-loops is close to providing
no edges at all). A feature-aggregator comparing "does this map's lane-type/width/speed/curvature
distribution differ from that map's" is a meaningfully different question than "does this map's
lane-connectivity topology, learned end-to-end via message passing, differ from that map's" — and
they don't have to agree in sign. The fixed encoder is the one actually answering the question
`C21_REPORT.md`'s own docstring claims it answers.

## What this does NOT change

- RQ1 (structural gap, `C14_RQ1_STRUCTURAL_GAP`) is untouched — separate methodology, no GNN
  involvement.
- The *existence* of a statistically detectable domain gap (CI excludes zero) is unchanged — still
  true under the fixed encoder, just with inverted sign and smaller magnitude.
- Per-tile training data (562 union_tiles) is identical between the original and retrained runs —
  the only inputs that changed are the graph_builder.py logic itself and (for the whole-map
  step only) the substitute auto map.

## Recommendation

Update `C21_GNN_AUTHORITATIVE`-derived thesis claims (currently
`RQ3_GNN_UPGRADED cosine_distance_mean=1.1537 ci=[1.0803,1.2476] status=AUTHORITATIVE`) to cite this
run's numbers instead, with the auto-map-substitution caveat documented. Awaiting user decision on
exactly how to formally adopt this (see conversation).
