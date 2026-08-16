# C9 — Gate/checker correctness sweep: measurement-bug fixes

Base branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803`
Worktree base commit: `95a816ea3a919537e56662f65363f51b613efe89`
Interp: `.venv/Scripts/python.exe` (absolute path) · `UP_DISABLE_CARLA=1`

Named candidate used for before/after measurement:
`campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr`
sha256 `248ffbbe6a1aa2a9cbd4330a69ad1c1680d39698e2d186dd45f5a2eb91c5db6c`
(32,710 roads; 32,710 `<elevation>` records; 9,894 non-junction roads / 22,816
junction-connector roads; flat elevation profile, min=max=0.0 on this
particular candidate — a different candidate than the audit's cited
361.85–408.67 m example, which is not present in this worktree).

**Boundary respected:** `ultimate_pipeline/quality/check_geometric_continuity.py`
(C6's file) was not modified. Perception (C8) and enrichment (C7) modules were
not touched.

## Verdict

```
GATES_CORRECTED elevation_summary=OK 08H=OK elevation_continuity_true=0 g19_tol=unified
```

`elevation_continuity_true=0` is the TRUE re-measured ordinary-road (non
-junction-connector) z-seam count on the named candidate — genuinely 0
because this candidate is flat end-to-end; the fix is validated as
measuring correctly (not merely "always 0") via the injected-defect negative
controls in `tests/unit/test_gate_measurement_correctness.py`, which prove a
real 1 m z-step and a `contactPoint="end"` mismatch are both caught.

---

## 1. `diagnostics/elevation_summary.py::summarize_elevation`

**Bug:** returned no top-level `min`/`max`/`span`. The closest proxy,
`coefficient_stats.a`, reports only the raw `a` coefficient (the elevation
value at each segment's *local start*), never evaluating the cubic
`a + b·s + c·s² + d·s³` — so a sloped single-record segment (the map's
dominant encoding: one `<elevation>` record per road) silently misses the
rise across the segment.

**Fix:** added `_eval_elevation_poly` and now samples the true elevation at
segment start, segment end, and any interior extremum of the cubic (roots of
`dz/ds=0` that fall strictly inside the segment) for every `<elevation>`
record. Reports genuine top-level `min`, `max`, `span` fields, plus the
existing `coefficient_stats`.

**Before/after (synthetic sloped fixture, `a=361.85, b=0.4682` over 100 m —
the exact endpoints cited in the audit):**

| | before | after |
|---|---|---|
| top-level `min`/`max`/`span` | absent (`KeyError`) | `min=361.85, max=408.67, span=46.82` |
| `coefficient_stats.a.max` (old proxy) | `361.85` (misses the rise) | unchanged, still reported for backward compat |

**Before/after on named candidate** (`ingolstadt_perception_final.xodr`,
flat map): `min=0.0, max=0.0, span=0.0` in ~5.4 s for 32,710 roads — correctly
reports a true zero span rather than null, and would report null only for a
genuinely elevation-free map.

**Controls added:**
- Positive: sloped single-record fixture → `min≈361.85, max≈408.67` (proves it isn't null).
- Positive: flat two-road fixture (`a=380.0` everywhere) → `min==max==380.0, span==0.0` (proves it isn't spuriously wide).
- Negative/empty: no `<elevationProfile>` at all → `min/max/span` genuinely `None` (proves it doesn't fabricate numbers).

---

## 2. `08H` `full_map_metrics.FullMapMetricsScanner.scan().elevation_continuity`

**Bug:** only compared consecutive `<elevation>` records *within the same
road's* `elevationProfile`. Since the map's dominant encoding is exactly one
`<elevation>` record per road, `sect_count > 1` was essentially never true,
so `num_segments` was always `0` — a dead sub-metric that always "passes"
regardless of real elevation change between roads.

**Fix:** added a second sampling pass over road-to-road **successor** links:
for each `road/link/successor[elementType="road"]`, evaluate the source
road's elevation cubic at its end (`s=road.length`) and the target road's
cubic at its `contactPoint`-selected endpoint (defaulting to "start"), and
feed `|z_to - z_from| / road_length` into the same `elevation_variance` /
`max_elevation_gradient` accumulators the within-road loop already used. The
within-road loop is preserved unchanged (still contributes when a road does
carry multiple records).

**Before/after on named candidate:**

| | before | after |
|---|---|---|
| `num_segments` | `0` | `22816` |
| `max_gradient` | `0.0` | `0.0` (correct — candidate is flat) |
| `variance` | `0.0` | `0.0` |

**Before/after on synthetic sloped two-road fixture** (road1 `a=361.85`,
road2 `a=368.0`, both length 10, linked by successor/predecessor):
`num_segments: 0 → 1`, `max_gradient: 0.0 → 0.615` (`(368.0-361.85)/10`).

**Controls added:**
- Positive (sloped): two roads with differing elevation joined by a
  successor link → `num_segments > 0` and `max_gradient > 0`.
- Positive (flat): two roads at identical elevation joined the same way →
  `num_segments > 0` (metric is alive) but `max_gradient ≈ 0` (metric isn't
  spuriously nonzero).

---

## 3. `quality/check_elevation_continuity.py`

**Audit finding: shares C6's blind spot — YES**, prior to this fix. Two
independent defects, both mirroring exactly what C6 found and fixed in
`check_geometric_continuity.py`:

1. **contactPoint ignored.** The target road's sampled endpoint was
   hardcoded by link kind (`successor → target s=0`, `predecessor → target
   s=target.length`) regardless of the link's declared `contactPoint`
   attribute. A successor link with `contactPoint="end"` was silently
   evaluated at the wrong end of the target road.
2. **No junction-connector separation.** Every road-to-road link was
   reported into the same `issues` bucket regardless of whether either road
   was a junction connector (`junction != "-1"`). Junction connector roads
   join at lane centers (governed by `<junction><connection><laneLink>`
   and per-lane offsets), so an expected junction-lane-offset z-difference
   was indistinguishable from a genuine reference-line z-seam, polluting
   the "true" seam count exactly as C6 found for geometric continuity.

**Fix (mirrors C6's `check_geometric_continuity.py` pattern, applied only to
this file):**
- `_road_links` now also returns the link's normalized `contactPoint`
  (`"start"`/`"end"`, defaulting to `"start"` only when absent/invalid).
- The target endpoint is now `contact_point or "start"` instead of being
  implied by link kind.
- Links are classified `is_junction_connector_link` when either endpoint
  road has `junction != "-1"`, and routed into a new
  `junction_connector_issues` / `num_junction_connector_issues` /
  `num_junction_connector_links_checked` set of fields, parallel to
  `issues` / `num_issues` / `num_links_checked` — `ok` is still driven only
  by ordinary-road `issues`, matching C6's convention.
- Report docstring updated to document the endpoint-selection contract
  explicitly (this also now matches the semantics already documented, but
  never actually implemented, in
  `ultimate_pipeline/enrichment/elevation_link_offset_solver.py`, which
  claimed to follow `check_elevation_continuity` — the two modules are now
  actually consistent).

**True re-measured z-seam count on named candidate:**

| | before | after |
|---|---|---|
| `num_issues` (ordinary road-to-road) | `0` | `0` |
| `num_links_checked` | `45632` (undifferentiated) | `0` (this candidate's non-junction roads have no road-to-road elevation links; connectivity flows entirely through junction connectors) |
| `num_junction_connector_links_checked` | n/a (field didn't exist) | `45632` |
| `num_junction_connector_issues` | n/a | `0` |

The `0` is unchanged and correct here (the candidate is genuinely flat), but
the split now makes explicit that the prior "0 issues" figure was
conflating 45,632 junction-connector-link checks with 0 ordinary-road
checks — an honest reading of the old report would have been "no evidence
either way for ordinary roads," not "ordinary roads pass."

**Controls added:**
- Positive (clean): matching elevation at a plain road-to-road join → `ok=True, num_issues=0`.
- Negative (1 m z-step): plain road-to-road join with a genuine 1 m
  difference → `ok=False, num_issues=2` (both link directions — successor
  and predecessor — correctly flag the same physical seam; this
  both-directions double-report is the existing, intentional pattern shared
  with `check_geometric_continuity`, not something newly introduced here),
  `dz≈1.0` on each.
- contactPoint regression: successor link declares `contactPoint="end"`,
  target road has a nonzero `b` so its start (100.0) and end (105.0)
  genuinely differ → checker now reports `dz≈300.0` (evaluated at the
  correct end), not the wrong `dz≈305.0` a hardcoded-start evaluation would
  produce.
- Junction-connector classification: an ordinary road linked to a
  junction-connector road with a 1.2 m offset → routed into
  `junction_connector_issues` (both directions, `num=2`), `num_issues=0`
  (not double-counted into the ordinary bucket).

---

## 4. Length-invariant (G19) tolerance unification

**Bug (in `ultimate_pipeline/debug/check_s_invariants.py`, the ad-hoc
gate):**
- Used `max(s_list)` — the maximum geometry **start** `s` — instead of
  `max(s + geometry.length)`, the maximum geometry **end**. A road whose
  last geometry starts well inside the declared length but whose own
  length pushes it past the end was invisible to this check.
- Used tolerance `1e-6`, looser than the certifier's `1e-9`
  (`run_n_certify._length_invariant_evidence`, and
  `ultimate_pipeline.tools.crash_safe_length_repair.TOL_M`, which were
  already both `1e-9` and already agreed with each other).

**Fix:**
- `check_s_invariants.py` now tracks `max(s + geometry.length)` per road and
  compares against `road.length + LENGTH_INVARIANT_TOL_M`, where
  `LENGTH_INVARIANT_TOL_M = 1e-9` is a new module constant documented as the
  single source of truth, explicitly cross-referenced to
  `run_n_certify._length_invariant_evidence` and
  `crash_safe_length_repair.TOL_M`.
- Also removed a special-case that skipped the length check entirely when
  `road.length <= 0` — the certifier's `length_invariant_summary` does NOT
  exempt non-positive lengths (a non-positive declared length with any
  positive geometry extent is a genuine crash risk under CARLA's
  `s <= road->GetLength()` assert), so the ad-hoc gate should not either.
- `ultimate_pipeline/quality/map_acceptance.py::build_map_acceptance` gained
  a new `length_invariant` gate. When `reports["length_invariant"]` (a
  pre-computed evidence dict, e.g. from the certifier) is supplied it is
  trusted as-is; otherwise, when `final_xodr_path` is supplied, the gate
  computes evidence directly via
  `crash_safe_length_repair.length_invariant_summary` — the EXACT same
  helper and tolerance (`1e-9`) the certifier uses — so the acceptance gate
  and the certifier can never disagree due to a tolerance mismatch. This is
  wired into every real pipeline run already, since
  `ultimate_pipeline/main_pipeline.py` already calls `build_map_acceptance`
  with `final_xodr_path=final_out` on Step 8.

**Before/after on named candidate:**

| | ad-hoc gate (`check_s_invariants`) | certifier (`length_invariant_summary`) | acceptance gate (`build_map_acceptance`) |
|---|---|---|---|
| before | `0` violations (wrong measurement + loose tol) | `767` violations, `max_excess_m≈1.0e-8` | no length_invariant gate existed |
| after | `767` violations | `767` violations (unchanged — was already correct) | `valid_for_experiments=False`, `failed_gates=["length_invariant"]`, `length_invariant_violations=767` |

All three now agree exactly (**767**). This reproduces the class of bug the
audit described (a loose ad-hoc gate reporting `0` while the certifier
reports a large nonzero count) on this worktree's available candidate; the
audit's cited figures (0 vs 798) are from a different candidate not present
here, but the mechanism and fix are identical and now verified end-to-end.

**Controls added:**
- `length_invariant_summary` (certifier helper) flags a 1e-7 m excess (`violations==1`).
- `check_s_invariants.scan_s_invariants` now flags the SAME 1e-7 m excess AND a case where the excess comes entirely from geometry *length* (start `s` inside bounds, but `s+length` outside) that the old `max(s_list)`-only measurement could never see.
- Both the ad-hoc gate and the certifier are asserted to agree on the 1e-7 m fixture (no loose-tolerance escape).
- `build_map_acceptance` is asserted to reject the same 1e-7 m fixture via `final_xodr_path`, with `metrics.length_invariant_violations==1` and `metrics.length_invariant_tol_m==1e-9`.
- Positive control: a road whose single geometry exactly matches its declared length → `0` violations from all three (ad-hoc gate, certifier, acceptance gate).

---

## 5. Positive/negative-control mandate — status per gate touched

| Gate | Positive control | Negative control | File |
|---|---|---|---|
| `summarize_elevation` | flat-map fixture (`min==max`) | empty-map fixture (`min/max/span is None`) + sloped fixture proves it isn't stuck at null | `tests/unit/test_gate_measurement_correctness.py` |
| `full_map_metrics.elevation_continuity` | flat two-road fixture (`gradient≈0`) | sloped two-road fixture (`gradient>0`, `num_segments>0`) | same |
| `check_elevation_continuity` | clean matching-elevation fixture (`ok=True`) | injected 1 m z-step fixture (`ok=False`) + `contactPoint="end"` mismatch fixture + junction-connector classification fixture | same |
| length-invariant (`check_s_invariants` + `length_invariant_summary` + `map_acceptance`) | exact-length fixture (`0` violations, all three agree) | 1e-7 m excess fixture (`1` violation, all three agree) + end-exceeds-but-start-inside-bounds fixture | same |

**Gates still lacking any positive/negative control (out of scope for C9,
listed per the spec's mandate to report them):**
`check_dem_coverage.py`, `check_dem_full_coverage.py`,
`check_determinism.py`, `check_drivability_smoke.py`,
`check_elevation_missing_and_cliffs.py`, `check_elevation_profile.py`,
`check_elevation_seams.py`, `check_lane_geometry_continuity.py`,
`check_lane_link_targets_exist.py`, `check_lane_width_continuity.py`,
`check_origin_sanity.py`, `check_post_tiling_integrity.py`,
`check_xodr_schema.py` — none of these have a dedicated test file under
`tests/unit/` or `ultimate_pipeline/tests/unit/` as of this sweep.
`check_geometric_continuity.py` (C6) and the perception/enrichment gates
(C7/C8) are excluded per this task's Boundaries and covered by the sibling
agents' own sweeps.

---

## Files changed

- `ultimate_pipeline/diagnostics/elevation_summary.py`
- `ultimate_pipeline/quality/full_map_metrics.py`
- `ultimate_pipeline/quality/check_elevation_continuity.py`
- `ultimate_pipeline/debug/check_s_invariants.py`
- `ultimate_pipeline/quality/map_acceptance.py`
- `tests/unit/test_gate_measurement_correctness.py` (new — 15 tests, positive+negative controls per gate)
- `reports/post_audit_hardening/C9_GATE_CORRECTNESS.md` (this file)

## Full-suite result

```
UP_DISABLE_CARLA=1 .venv/Scripts/python.exe -m pytest -q
781 passed, 1 skipped, 82 warnings in 172.12s (0:02:52)
```

No regressions. `check_geometric_continuity.py` (C6's file) was not
modified; `check_geometric_continuity_migration.py` tests (24 tests) pass
unchanged.
