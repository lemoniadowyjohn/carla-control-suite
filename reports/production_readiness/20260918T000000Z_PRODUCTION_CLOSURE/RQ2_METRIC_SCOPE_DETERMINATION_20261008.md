# RQ2 metric-scope determination — the 3 "potentially stale" metrics (2026-10-08)

Resolves the open question from the RQ2 staleness review: were whole-map/per-tile
curvature KL and alignment quality covered by `rq2_metric_authority.py
--validate-only`, and if not, what is the honest resolution?

**Determination: all three are OUT OF RQ2 SCOPE by contract. They were correctly
not covered, and the correct action is to record them as out-of-scope — not to
re-run them and not to "refresh" them.**

## 1. Were they covered by the 18/18 validate-only checks? No.

`build_validation_report` assembles its checks from exactly two sources:

* `FROZEN_CITATIONS` — 17 hardcoded citations, each a named number from the
  thesis progress record, checked with a fail-closed `kind` matcher
  (`exact` / `round` / `prefix` / `suffix`);
* one appended aggregate check `frozen_results.metrics_and_pair`, which compares
  the frozen `RQ2_RESULTS.json` `pair` plus the `metrics` and `support` subtrees
  of both scopes, at `FROZEN_RESULTS_ATOL = 1e-9`.

17 + 1 = the 18. The 17 citations cover pair identity (2), manual_hull metrics
(6), Fréchet (4), hull support (2), whole_map road-length ratio (1) and
whole_map support lengths (2).

None of the three appears as a citation, and none is present in the `metrics`
subtree the aggregate check walks — so the aggregate check could not have caught
them either.

Scope-by-scope:

| metric | covered? | why |
|---|---|---|
| whole-map curvature KL | no | `compute_whole_map` emits only `road_count_ratio`, `road_length_ratio`, `junction_ratio`, `building_density_gap` (hardcoded `None`), `connectivity_gap`, `semantic_object_gap`. There is no curvature field in the whole_map scope at all. `curvature_gap` IS checked, but only under `manual_hull`. |
| per-tile curvature KL | no | The module has no per-tile scope. Its `scope_policy` is explicit: "manual_hull and whole_map metrics are computed independently and never averaged or mixed." |
| alignment quality | no | Not a metric the module computes at all. `compute_local_registration` performs the alignment but emits no alignment-quality figure. |

## 2. Why they cannot be produced "the same way validate-only does"

They belong to a **disjoint code path**. This is stated twice in the thesis
progress record, lines 124-136 and 162-165:

> `ultimate_pipeline/domain_gap/local_registration.py` (the module this script
> calls) is a self-contained implementation with its own convex-hull footprint
> crop, its own curvature-gap calculation, and its own coordinate-frame handling
> — it does not import or call `GeoAligner` or `CurvatureGap`, the two modules
> whose bugs were fixed this session. Those fixes live in the *whole-map* pipeline
> (`ultimate_pipeline/run_full_domain_gap.py` and friends), not this one.

`--validate-only` runs `local_registration` + `frechet_gap` only. Running it can
never produce curvature KL or alignment quality, because the code that produces
them is not on that path. Re-deriving them means running
`run_full_domain_gap.py`, which is a different pipeline with different inputs —
i.e. exactly what the thesis record calls "a methodology change, not a re-run".

## 3. Contract verdict: out of scope

`research/thesis_rq_contract.yaml`, `research_questions.RQ2.valid_metrics`
(lines 20-30) lists exactly ten metrics:

    lane_width_gap, curvature_gap, curvature_wasserstein_gap,
    road_count_ratio, road_length_ratio, junction_ratio,
    building_density_gap, frechet_distance,
    connectivity_gap, semantic_object_gap

This is a **1:1 match** with `rq2_metric_authority.py`'s `VALID_METRICS`, which
is strong evidence the module is correctly scoped and that validate-only's
surface is the intended one.

The contract's `aliases` map (lines 31-46) resolves legacy and scope-prefixed
names onto that set — `local_curvature_gap -> curvature_gap`,
`local_curvature_wasserstein_gap -> curvature_wasserstein_gap`,
`whole_map_construction_layers_excluded_from_local_gap -> semantic_object_gap`.

Decisively:

* **curvature KL has no entry and no alias.** The contract's curvature metrics
  are `curvature_gap` and `curvature_wasserstein_gap` — the latter is a
  Wasserstein distance, not a KL divergence. KL is a different statistic and is
  not a sanctioned substitute.
* **alignment quality has no entry and no alias.**
* **no per-tile metric has an entry or alias.** RQ2 is defined as a question
  about whole and hull-footprint structure, not per-tile decomposition.

## 4. Last recorded values (2026-09-15 run, pin since superseded)

From `reports/production_readiness/20260915T101724Z_FRESH_DOMAIN_GAP_REGEN/summary.json`:

| metric | value |
|---|---|
| `curvature_kl_divergence` | 0.0030586158645774116 |
| `geometry_rmse` | 85.31957130654521 m |
| `geometry_hausdorff` | 6968.602685650037 m |
| per-tile | `N/A` — never computed |

These are whole-map **context** figures from the `run_full_domain_gap.py` sweep,
not RQ2 results, and they were computed against a pin that is now superseded.

## 5. Resolution

1. Record all three as **out of RQ2 scope**, not as stale RQ2 metrics. They are
   whole-map context from a separate sweep.
2. **Per-tile is not "stale" — it has no value to go stale.** It was never
   produced even once (`UP_SKIP_TILE_ALIGNMENT=1`, `per_tile_status=skipped`;
   `num_tile_pairs`/`tile_count_auto`/`tile_count_manual` are all `"N/A"` in the
   historical summary). Describing it as stale implies a prior result exists.
3. No fix, no port of `GeoAligner`/`CurvatureGap` into `local_registration.py`.
   The thesis record already flags that as unattempted and out of scope, and it
   should stay that way unless the contract is amended first.
4. If a whole-map curvature-KL figure is ever needed for the thesis narrative,
   it must be regenerated by `run_full_domain_gap.py` against the current pin
   and labelled whole-map context, never presented as an RQ2 metric.

## 6. Adjacent finding — the per-tile tiling subprocess (separate issue)

The historical skip reason for per-tile ("the per-tile auto-tiling subprocess
reliably exceeds its hardcoded timeout") was **already root-caused and fixed**,
twice, in `ultimate_pipeline/tiling/tile_extractor.py`:

* **TIL-PERF-001** (line 324-336): replaced an `O(tiles x roads)` candidate scan
  with per-cell AABB bucketing.
* **PERF** (line 661-670): hoisted road-bounds computation out of the per-tile
  loop, eliminating "~25M redundant hashes ... ~32s for a single full pass of
  the hash alone, i.e. ~7 hours if repeated per tile".

The remaining mechanism is `run_full_domain_gap.py::_auto_generate_aligned_manual_tiles`,
which shells out to `python -m ultimate_pipeline.tools.tile_manual_xodr_windows`
under a **hardcoded** `_TILE_ALIGNMENT_SUBPROCESS_TIMEOUT_SEC = 600`
(line 1837), justified in-comment by 3x headroom over a measured 195.2 s.

That is legitimate CPU-bound work, not a debug hook: the tiler is pure stdlib,
spawns no children of its own, and its import cost is 37 MB / 0.6 s.

**Correction to an earlier hypothesis:** this is *not* the same process as the
Stage-7 mystery child reported by HH1. That one was spawned from
`ultimate_pipeline/pipeline_stages/stage_07_lanes.py`; this one is spawned from
`run_full_domain_gap.py`. They share only a shape (a subprocess doing heavy
whole-map CPU work while the parent blocks), not an identity. See
`docs/runtime/PACKAGED_CARLA_CONFIG_MODIFICATIONS.md` sibling investigation for
the Stage-7 side, whose only subprocess is the CARLA smoke-load suite.

**Residual issue worth a decision (not changed here):** if the 600 s ceiling is
exceeded, `subprocess.run` kills the tiler and the helper returns `None`, and
downstream treats a missing tiles dir as "skip per-tile gaps, not a hard error"
(line 4366-4367). A timeout is therefore indistinguishable from "never
requested" in the resulting report. Making the timeout environment-configurable
would let a slower machine finish rather than silently drop the metric; that is a
production behaviour change and is left for the owner to approve.
