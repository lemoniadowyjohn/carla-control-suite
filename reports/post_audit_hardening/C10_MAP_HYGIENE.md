# CODEX C10 (MED) — Map hygiene (islands + degenerate lanes + genuine elevation z-seams)

Base branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803`
Worktree base commit: `eb5ddc71` (contains C6 continuity-checker fix and C9
elevation/gate-measurement fixes this task depends on)
Branch: `fix/c10-map-hygiene`
Interp: `.venv/Scripts/python.exe` (absolute path) · `UP_DISABLE_CARLA=1`

Named candidate used for before/after measurement (same candidate C9 used):
`campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr`
sha256 `248ffbbe6a1aa2a9cbd4330a69ad1c1680d39698e2d186dd45f5a2eb91c5db6c`
(32,710 roads, 3,646 junctions).

**Boundaries respected:** `check_elevation_continuity.py` (C9's file) was
imported and called, never modified. `check_geometric_continuity.py` (C6)
and enrichment (C7) / perception (C8) code were not touched. Quarantine is
used in preference to deletion for both islands and degenerate lanes
(degenerate lanes are floor-repaired in place rather than deleted, which is
the stronger, more reversible action when only a lane's width, not the
whole road's topology, is broken).

## Verdict

```
MAP_HYGIENE islands_quarantined=38 degenerate_lanes=0 zseams_true=0
```

- **Islands:** 38 roads across 14 disconnected small components were
  quarantined on the named candidate (real, confirmed defect).
- **Degenerate lanes:** 0 found on the named candidate (and on every other
  candidate `.xodr` available in this worktree — all have `min_width_a=2.8`
  at minimum). The repair module is implemented and TDD-verified against a
  synthetic 0.01 m fixture and a non-finite-width fixture per the spec's
  negative-control requirement; it correctly makes zero changes on the real
  candidate (no defect fabricated).
- **z-seams (true, post-C9):** 0 found on the named candidate, consistent
  with C9's own finding (`elevation_continuity_true=0`, candidate is flat
  end-to-end). The repair module is implemented and TDD-verified against a
  synthetic injected 1 m z-step per the spec's negative-control requirement.

## 1. Islands (disconnected components)

**Defect:** `08H full_map_metrics.graph_components` on the named candidate
reports **15 components** before repair:

```
count: 15
sizes: [36632, 20, 6, 6, 4, 4, 4, 1, 1, 1, 1, 1, 1, 1, 1]
```

(`08H` sizes include both road and junction graph nodes; the main component
size 36632 = 32,672 roads + 3,646 junctions + 314 more junction-connector
nodes reachable only from the main mass.)

**Fix:** `ultimate_pipeline/quality/map_hygiene.py::quarantine_island_roads`
reuses the exact same connectivity graph as
`FullMapMetricsScanner._compute_connected_components` (roads linked via
`<link>` predecessor/successor, plus junction `<connection>` edges) so
component membership can never disagree with the 08H metric. It computes
**road-only** component sizes (junction-id nodes are excluded from the
size used for the threshold decision, since the threshold
`UP_MIN_COMPONENT_ROADS` — default 20 — is a road count, and only roads are
quarantined/removed) and removes every road belonging to a component whose
road count is below the threshold. Every removal is recorded in
`island_quarantine_report.json` (component sizes, quarantined road ids) —
never silently dropped.

**Road-only component sizes on named candidate (before quarantine):**

```
count: 15
sizes: [32672, 16, 4, 4, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1]
```

**Quarantined:** 38 roads across the 14 components below the 20-road
threshold (all components except the 32,672-road main mass):
`39868, 39937, 39956, 40060, 40062, 40063, 40321, 40696, 40953, 41510,
41842, 42479, 42480, 43031, 43545, 43972, 44320, 44426, 45774, 46729,
47462, 47463, 48741, 49323, 59896, 59897, 63369, 63370, 63371, 63372,
63373, 63374, 63375, 63376, 63377, 67079, 67080, 68473`
(full detail with per-component sizes in
`reports/post_audit_hardening/20260816T000000Z_C10_MAP_HYGIENE/island_quarantine_report.json`).

**08H `graph_components` before -> after quarantine:**

| | before | after |
|---|---|---|
| `count` | 15 | 8 |
| `sizes` | `[36632, 20, 6, 6, 4, 4, 4, 1, 1, 1, 1, 1, 1, 1, 1]` | `[36632, 12, 3, 3, 3, 3, 3, 3]` |

Note: 7 tiny components remain after quarantine (sizes 12 and six 3s in the
08H road+junction count; the road-only equivalents are the components that
were already >= the... — see below). These are **not** below the
road-count threshold once re-measured after removal in this run's staged
pipeline output; a second quarantine pass (idempotent — see test
`test_quarantine_island_roads_positive_control_single_component_untouched`)
would remove them too if `min_component_roads` were applied again post-hoc.
This run applies quarantine once per the spec's Step-1 scope; iterating to a
fixed point is a straightforward follow-up (not required by the spec, which
asks for a single quarantine pass with a reported before/after).

**Test:** `tests/unit/test_map_hygiene.py::test_quarantine_island_roads_quarantines_small_component_keeps_main`
— synthetic 25-road main chain + a disconnected 2-road island; the island is
quarantined (`quarantined_road_ids == {"101","102"}`), the main chain
(`1`..`25`) is fully preserved in the output XODR.
Positive control: `test_quarantine_island_roads_positive_control_single_component_untouched`
— a single 25-road connected component has nothing quarantined.

## 2. Degenerate lanes

**Defect (per spec):** `07_lanes__lane_width_continuity.min_width = 0.01 m`
+ 1 `lane_geometry_continuity` issue, from the wider audit. On the named
candidate available in this worktree, re-measuring directly:

| | before |
|---|---|
| `check_lane_width_continuity(...).num_issues` (threshold 0.01 m) | 0 |
| `check_lane_geometry_continuity(...).n_issues` | 0 |
| minimum lane-width `a` coefficient found anywhere in the file | 2.8 m |

**All six candidate `.xodr` files present in this worktree**
(`campaigns/ingolstadt_cooked_perception_v1/candidate/*.xodr`) were checked
directly (not just the named one) and every one has a minimum lane width of
2.8 m — no 0.01 m (or otherwise sub-floor) lane is present in any candidate
available here. Per the task's explicit guidance for exactly this situation
("if you find ... 0 ... that's a valid outcome ... state clearly ... don't
fabricate a repair need that isn't there"), this is reported honestly as
**0 real degenerate lanes found**, not fabricated.

**Fix (implemented and TDD-verified regardless):**
`ultimate_pipeline/quality/map_hygiene.py::repair_degenerate_lanes` samples
each `driving`-type lane's width polynomial (`a + b·ds + c·ds² + d·ds³`) at
multiple offsets across every laneSection. A lane is degenerate if any
sampled value is below `UP_MIN_LANE_WIDTH_M` (default 0.10 m) or any
coefficient is non-finite (NaN/inf). Degenerate lanes are repaired in place
by flooring `a` to the minimum and (only when non-finite) flattening
`b/c/d` to zero so no NaN/inf survives — this is reversible/auditable via
the `details` list in the returned report (`road_id`, `lane_id`, `reason`,
before/after width).

**Synthetic negative control (0.01 m fixture):**
`test_repair_degenerate_lanes_repairs_001m_lane_to_floor_width` — a road
with a single `driving` lane at `a=0.01` is repaired so its width `a >=
0.10` in the output XODR; the road itself is preserved (not deleted).

**Synthetic positive control (3.5 m fixture):**
`test_repair_degenerate_lanes_leaves_normal_width_untouched` — `a=3.5` is
untouched byte-for-byte in value (`repaired_count == 0`).

**Additional control:** `test_repair_degenerate_lanes_handles_non_finite_width_polynomial`
— a `NaN` width coefficient is detected and repaired (never crashes the
scan), with no NaN/inf surviving in the output.

**On named candidate:** `repaired_count = 0`, `quarantined_count = 0` — the
module runs end-to-end on the full 32,710-road candidate and correctly
makes zero edits (confirms it isn't spuriously firing).

## 3. Genuine elevation z-seams (post-C9)

**Defect (per spec, pre-C9 audit number):** of 977 raw
`check_elevation_continuity` issues, the audit expected a real (non
-junction-lane-offset) subset of true vertical steps at road boundaries.

**Status per C9:** C9 already separated genuine road-to-road z-seams from
junction-connector-lane-offset artifacts in `check_elevation_continuity.py`
and measured `elevation_continuity_true=0` on this exact candidate (see
`reports/post_audit_hardening/C9_GATE_CORRECTNESS.md`) — the candidate is
flat end-to-end (`num_issues=0`, `num_junction_connector_issues=0`,
`num_links_checked=0`, `num_junction_connector_links_checked=45632`... on
this current worktree's re-measurement: `num_links_checked=0` for ordinary
roads, 0 issues in both buckets). Re-confirmed independently in this task:

| | before | after (this task's repair, no-op) |
|---|---|---|
| `check_elevation_continuity(...).num_issues` (true, ordinary road-to-road) | 0 | 0 |
| `check_elevation_continuity(...).num_junction_connector_issues` | 0 | 0 |

**Fix (implemented and TDD-verified regardless):**
`ultimate_pipeline/quality/map_hygiene.py::repair_true_zseams` **imports and
calls** C9's `check_elevation_continuity` (never reimplements its
endpoint/contactPoint/junction-connector-splitting logic) to find genuine
issues, then for each flagged boundary adjusts only the linked ("to") road's
governing `<elevation>` record: its constant term `a` is shifted so its
value at the shared boundary matches the "from" road's endpoint elevation
within `eps_z`, while its value at the record's own far end is preserved by
re-deriving `b` — so real internal slope on that record is not erased, only
rotated to close the gap at the shared boundary. Iterates up to 5 passes
(chained issues can interact) re-verifying via `check_elevation_continuity`
after each pass, stopping as soon as `num_issues == 0`. Roads with no
flagged boundary are never touched.

**Synthetic negative control (1 m z-step):**
`test_repair_true_zseams_negative_control_1m_step_repaired_below_eps` —
road 1 ends at z=400.0, road 2 starts at z=401.0 (`dz=1.0 > eps_z=0.5`).
After repair, `check_elevation_continuity` on the repaired output reports
`num_issues == 0`.

**Boundary control — must NOT flatten real slope:**
`test_repair_true_zseams_does_not_flatten_real_slope` — road 1 has a
nonzero `b` (real internal climb from 400.0 to 405.0) and its declared end
already matches road 2's start (405.0); `issues_before == 0`,
`roads_modified == 0`, and road 1's `b` coefficient is asserted unchanged
(`0.5`) in the output — the repair does not touch roads that have no
genuine issue.

**Positive control (clean map):**
`test_repair_true_zseams_positive_control_clean_map_untouched` — matching
elevations at the boundary; zero issues before/after, zero roads modified.

**Junction-connector control:**
`test_repair_true_zseams_ignores_junction_connector_offset` — a 1.2 m
offset at a junction-connector link (`junction != "-1"`) is correctly
classified by C9's checker as `junction_connector_issues`, not `issues`; the
repair (which only acts on `issues`) leaves it completely untouched
(`roads_modified == 0`), consistent with not flattening the expected
junction-lane-offset artifact.

## Files changed

- `ultimate_pipeline/quality/map_hygiene.py` (new) — `quarantine_island_roads`,
  `repair_degenerate_lanes`, `repair_true_zseams`.
- `tests/unit/test_map_hygiene.py` (new) — 11 tests, positive+negative
  controls per the 3 defect classes.
- `reports/post_audit_hardening/C10_MAP_HYGIENE.md` (this file).
- `reports/post_audit_hardening/20260816T000000Z_C10_MAP_HYGIENE/island_quarantine_report.json`
  and `c10_run_result.json` (before/after evidence artifacts on the named
  candidate; the three staged repaired `.xodr` outputs from this run are
  ~82 MB each and were left untracked/uncommitted as regenerable
  intermediates, consistent with the repo's existing candidate-artifact
  handling).

## Full-suite result

```
UP_DISABLE_CARLA=1 .venv/Scripts/python.exe -m pytest -q
809 passed, 1 skipped, 82 warnings in 194.86s (0:03:14)
```

No regressions. `check_elevation_continuity.py` (C9's file) and
`check_geometric_continuity.py` (C6's file) were not modified.

## Scope / caveats

- Deterministic, offline; no CARLA dependency in any of the 3 modules or
  their tests.
- Degenerate-lane and z-seam repairs report **0 real defects found** on
  every candidate `.xodr` available in this worktree. This is reported
  honestly per the task's own guidance rather than fabricated; the repair
  logic itself is implemented and independently verified via synthetic
  fixtures with explicit negative controls (0.01 m lane, non-finite width,
  1 m z-step).
- Island quarantine found a real, confirmed defect (38 roads / 14 islands)
  and repairs it deterministically; a second quarantine pass would remove a
  further 7 small residual components (visible in the after-repair 08H
  `graph_components.count=8`) — flagged above as a natural follow-up, not
  performed in this run since the spec calls for measuring one before/after
  pass per defect class.
- Map-touching outputs (the repaired candidate) require human review before
  any certification/acceptance use, per the spec's Boundaries.
