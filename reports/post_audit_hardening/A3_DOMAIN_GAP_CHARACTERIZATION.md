# A3 domain_gap metric characterization - outcome

Date: 2026-08-15
Executor: Codex
Verdict: **DG_CHARACTERIZED_GREEN (core + aggregator)**

Added `tests/unit/test_domain_gap_metrics.py` (9 deterministic offline tests). No defect discovered.

## Tests

Targeted gate:

```text
tests/unit/test_domain_gap_metrics.py ......... [100%]
9 passed, 3 warnings
```

Full-suite gate:

```text
683 passed, 49 warnings in 63.39s
```

## Premise correction (like A1)
The audit's "domain_gap = 2 tests" undercounted: `connectivity_gap`, `curvature_gap`, and `elevation_gap`
already have tests. The genuinely-untested, high-value core is the **aggregator** (the headline composite number)
plus untested pure helpers of `topology_gap` / `geometry_gap`. Those are what A3 locks.

## PROVEN now (locked by tests)
- `DomainGapAggregator.aggregate` - the academic composite contract:
  - identical maps (rmse=0, kl=0) -> **composite 0.0**;
  - composite **clamped to [0,1]** (large rmse -> 1.0);
  - **disabled component excluded** from composite (geometry disabled -> curvature-only);
  - no normalized components -> composite `None` with a reason;
  - `semantic`/`elevation` are **reported in components but excluded** from the composite (as documented);
  - `_norm(value, ref)` clamps to 1.0 and returns None when value is None or ref ≤ 0.
- `topology_gap._norm_diff` (|a-b|/max(1,max(a,b))) and `_safe_int` (parse/fallback).
- `geometry_gap._safe_float` (parse/fallback) and `_estimate_hausdorff_time` (0 at n=0; monotonic increasing).

## Still ASSUMED (needs XODR fixtures; feeds RQ-status)
The XODR-path metric entrypoints are not yet exercised end-to-end:
`structural_gap.analyze_xodr`, `semantic_gap.compute`, `topology_gap.compute`, `geometry_gap.compute`,
`curvature_gap.compute` on real/synthetic XODR pairs (identical -> gap about 0; single perturbation -> right metric moves
in the right direction). These require a small synthetic-XODR fixture harness (a natural follow-up, and what B4
will exercise on the real auto-vs-manual pair).

## Implication
The **composite aggregation contract** (the number the thesis reports as "the domain gap") is now verified: it is
bounded, 0=identical, and provably ignores disabled/missing components, so it cannot silently inflate from a
half-populated run. The per-metric XODR computations remain to be characterized with fixtures.
