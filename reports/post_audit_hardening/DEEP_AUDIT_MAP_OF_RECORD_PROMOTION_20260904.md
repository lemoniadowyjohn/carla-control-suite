# Deep repo audit — map-of-record promotion, 2026-09-04

Follow-up to the user's request: "perform deep audit for whole repo, check what needs improvement
and strengthening to obtain realistic full drivable map without prior identified issues."

## Research (3 parallel Explore agents + direct verification)

1. **Gate-wiring audit**: found 5 real, unwired quality checkers (same shape as the
   `junction_integrity`/`component_reachability` gap fixed 2026-09-02) — all complete, correct,
   already used mid-pipeline or as an opt-in live-CARLA gate, but never reaching final map
   acceptance.
2. **Pipeline-stage coverage survey**: flagged 6 code passages as worth independent verification
   (not yet acted on — see WS-E, still open).
3. **Open-issues compilation**: confirmed the already-known deferrals (heading kinks, R13 CRLF
   freeze, 19 unparsed multipolygon buildings) remain correctly settled; surfaced 2 minor
   secondary items (a never-run second island-quarantine pass, the multipolygon gap) as low
   priority.

Every headline claim was independently verified by direct source reading before acting — not
taken on agent-report faith alone.

## WS-A — Wired 5 more quality gates into map acceptance (@2856364a)

`check_lane_width_continuity`, `check_lane_geometry_continuity`, `ElevationSmoothnessGate`,
`PhysicsFeasibilityChecker`, `check_elevation_missing_and_cliffs` are now called by
`scripts/measure_candidate_acceptance.py::run_gates()` and hard-fail unconditionally in
`ultimate_pipeline/quality/map_acceptance.py::build_map_acceptance()`, matching
`geometric_continuity`/`junction_integrity`'s always-on class, not the opt-in
`enrichment`/`component_reachability` class. 22 new tests, RED-verified via `git stash`.

**Why this matters**: before this fix, a candidate could have a lane narrower than a car (<1.0m),
a 45-degree slope, or a road with no elevation data at all, and `regen_map_of_record.py` would
still report `valid_for_experiments: True`.

## WS-B — Re-measured the promoted candidate against the hardened gates

Result: 4 of 5 gates passed clean. `lane_geometry_continuity` found **1 real violation**:
road 46620's right `driving` lane steps from 3.5m to 3.0m over a 0.05m laneSection (an instant
width change, not a taper).

## WS-C — Root-caused and fixed the violation (@4de0cd0c)

Traced to `stage_07_lanes.py`'s own output (present as of that pipeline stage, not introduced by a
later repair). This road was previously investigated once (`DEEP_QUALITY_SWEEP_20260817`): a
*different* lane at this same s=0.05 boundary (a sidewalk→driving type transition) was flagged and
fixed with a "skip type-mismatched comparisons" guard, which is still working correctly. The lane
found here (`-1`, driving→driving, same type on both sides) was never previously examined, since
nothing ran `check_lane_geometry_continuity` as a live gate until this pass. Only 1 of 32,267 roads
violates the tolerance (4 sibling roads share the same s=0.05 split pattern but stay within it).

Presented to the user with three options (fix now / defer / investigate further); user chose fix.

Added `ultimate_pipeline/quality/map_hygiene.py::repair_lane_width_discontinuities()`, matching the
file's established pattern (`repair_true_zseams` reusing `check_elevation_continuity` as its
detection oracle): uses `check_lane_geometry_continuity` to find genuine same-lane-id/type width
discontinuities, then nudges the **shorter** of the two bracketing laneSections' boundary-adjacent
`<width>` record by the exact residual delta — preserving any existing taper shape, minimizing how
much road length is altered, and correctly leaving lane-type-mismatch boundaries untouched (since
it only acts on issues the checker itself reports). 4 new tests, RED-verified via `git stash`
(import error confirms the function didn't exist pre-fix).

Verified directly against the real map-of-record candidate: 1 issue → 0, independently
re-confirmed via a fresh `check_lane_geometry_continuity` call on the repaired output.

## Promotion

Re-measured full acceptance on the repaired candidate: **`valid_for_experiments=True`, 0 hard-fail
reasons across all 10 structural gates** (was 1: `lane_geometry_continuity`). Promoted to
`auto_map_of_record` in `ultimate_pipeline/carla_tools/map_registry.py`
(`ingolstadt_perception_map_of_record_20260904_deepaudit.xodr`, sha256 `e281367e...`), following
the same chain-link pattern used for the two prior promotions this project (the WS1.4 junctionfix
pin is kept as a separate, non-`auto`-aliased registry entry so
`validate_thesis_claim_provenance.py`'s single-hop `supersedes_sha256` lookup can still resolve
historical claims). Updated `test_map_registry_pinning.py`'s hardcoded sha assertion.

Full local suite: 5611 passed, same 1 known pre-existing flake. All pin-related tests
(`test_map_registry_pinning.py`, `test_map_registry_verify_pinned_map.py`,
`test_validate_thesis_claim_provenance.py`, `test_planview_internal_seams_heading_only.py`) green.

## WS-D — Second island-quarantine pass: nothing to do

Ran `quarantine_island_roads()` against the new candidate: `component_sizes_before: [32267]` — a
single connected component, zero islands. The "7 residual small road components" claim from the
open-issues research agent was based on stale information (`C10_MAP_HYGIENE.md`'s own 2026-08-16
snapshot, predating the WS1.4 hygiene-glob fix from earlier this session, which already fully
resolved road-level fragmentation for this map-of-record lineage). No action needed; documented so
this stale claim isn't re-surfaced as a live TODO in a future pass.

## WS-E — Verified the 6 flagged code passages: none are real, live defects

Independently confirmed each via direct reading + tracing actual call sites (not agent-report
faith), matching this session's "verify before touching" discipline:

- **`stage_06_links.py::_geom_endpoint`/`_diagnostic_records_for_operation`** (2 items): both feed
  `_observe_planview_operation`'s `mode: "READ_ONLY_DIAGNOSTIC"` path, which deep-copies the root
  and mutates only the copy — a parse failure here degrades diagnostic-report completeness, never
  the actually-generated map.
- **`stage_05_geometry.py`'s `setattr` in the flat-elevation fallback**: `setattr` on a plain
  Python function object cannot realistically fail; even if it somehow did, `_dem_fallback_active`
  only feeds a bookkeeping list (`fallback_road_ids`) and a metadata flag, not the actual elevation
  value written (`_set_flat_elevation` runs unconditionally).
- **`stage_05_geometry.py` elevation variance on a malformed-value-filtered subset**: checked the
  real candidate directly -- 0 of 32,267 `<elevation>` elements fail to parse. The hypothesized
  "80% malformed" scenario has no real-world manifestation on this map.
- **`lane_generator.py`'s connector lane width**: false positive. `target_driving_width_m()` has
  no code path returning `None` -- every branch constructs a `LaneWidthDecision` with a clamped,
  rounded float `.width_m`.
- **`signal_enrichment.py`'s NaN-`s` duplicate signal not rejected**: already covered upstream.
  `validate_placement` (SIG-003) explicitly rejects non-finite placement attributes and the caller
  `continue`s past rejected records *before* `_build_signal` ever inserts them into the tree -- a
  NaN-`s` signal can never reach the duplicate-detection code (SIG-005) in normal pipeline flow.

No fixes needed; all 6 are either diagnostic-only, unreachable in practice, or false positives on
closer reading.

## Follow-up: wired the 3 remaining lower-stakes gates too (user-requested)

User asked "any more improvements or hardening?" after the above was done. Wired the final 3
unwired checkers from the original gate-wiring audit (`check_semantic_overlap`,
`check_randomness_entropy`, `collision_mesh`) into `run_gates()`/`build_map_acceptance()` as
**soft-info reports only** -- unlike the 5 structural gates, all 3 are self-documented by their own
authors as heuristic/diagnostic/non-fatal (`SemanticOverlapChecker`: "not necessarily wrong, but
something to review"; `collision_mesh`: "diagnostic only... unless enforced elsewhere", off by
default). Forcing these to hard-fail would impose a stricter policy than intended and would likely
make `semantic_overlap` fire on any normally-enriched real map. 16 new tests, RED-verified.
Committed @c9d1eb12.

Checked directly against the real promoted candidate: `semantic_overlap` 0 issues,
`randomness_entropy` 0.965 (healthy, well above the 0.05 floor -- confirms Ingolstadt's real,
organic street layout), `collision_mesh` 0 issues (no-op, disabled by default as designed). No
surprises; no re-promotion needed since these are soft-only and don't affect
`valid_for_experiments`.

## Final status

All 5 workstreams of the deep-audit plan closed. The map-of-record now passes every wired
structural gate cleanly (0 hard-fail reasons across 10 gates), the road-level connectivity graph
is a single component (0 islands), and the 6 speculatively-flagged code passages were run to
ground and found to be non-issues rather than left as unresolved question marks.

Unchanged from before this audit (already correctly settled, not re-opened): the 82 heading-only
planView kinks (deferred, unsafe fix confirmed 3x over), the R13 evidence bundle's CRLF drift
(git-tag-anchored freeze), 19 unparsed multipolygon buildings (0.3%, explicitly accepted), 2
medium/1 low-stakes still-unwired gates (`semantic_overlap`, `randomness_entropy`,
`collision_mesh` -- not in primary scope, genuine completeness/diagnostic checks rather than
drivability blockers), 27 isolated lane-level components (soft warning only, distinct connectivity
model from the road-level graph, already characterized in `C32_ROAD_CONNECTIVITY_CHARACTERIZATION.md`).
