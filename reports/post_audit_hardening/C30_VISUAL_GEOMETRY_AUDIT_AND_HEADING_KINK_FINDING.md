# C30 — offline visual-geometry audit run for the first time; one real blind spot found and fixed (additive)

## Context
The thesis's dominant open blocker (Chapter 9, item 7) names a "layered visual-readiness
audit stack" including offline, non-CARLA connector-pose mismatch detection
(`audit_xodr_visual_geometry`). This tool exists (`ultimate_pipeline/diagnostics/
audit_xodr_visual_geometry.py`) but had never been run against any candidate — no prior
report or artifact referenced it. Ran it for the first time against the current promoted
pin, offline, no live CARLA needed.

## Raw result
```
roads=32297 junctions=3568 planview_issues=82 lane_issues=0 junction_issues=8236
```
plus (not printed to stdout, only in the JSON summary): `elevation_issue_count=77503`,
`link_gap_issue_count=18720`.

## Triage — most categories are already-understood, non-issues
Investigated each category against real distribution data before drawing any conclusion,
per this session's standing discipline (raw tool counts are not self-verifying — several
earlier findings this session turned out to be measurement artifacts, not real defects):

- **`link_gap` `non_road_link` (18,720)**: benign bookkeeping. Set whenever a road's
  predecessor/successor is a junction rather than another road — completely normal
  OpenDRIVE structure for any road terminating at an intersection, not a defect.
- **`junction_integrity` `connector_pose_mismatch` (8,236)**: **already thoroughly
  investigated and correctly classified** in `C6_CONTINUITY_CHECKER.md` earlier this
  session. 97.1% cluster within 0.01m of exactly 3.5m (one driving-lane width); the rest at
  exact multiples (7.0/10.5/14.0m). This is the expected result of junction connectors
  attaching at the 2nd/3rd/4th lane rather than the reference line — CARLA routes junction
  traffic via `<laneLink>` lane topology, not reference-line coincidence, so this is not a
  defect signal. `check_geometric_continuity.py` already excludes this class from its
  hard-fail gate for exactly this reason. No new finding here — re-confirms C6's conclusion
  independently.
- **`elevation_gap` `linked_endpoint_z_gap` (45,206 records)**: median 5.2cm, p90 23cm, only
  143/45,206 (0.3%) exceed 1m, zero exceed 5m. Small, plausible DEM-interpolation-scale
  seams at junction boundaries, not the "detached slabs" scale the thesis described.
  Corroborates the thesis's own finding that elevation was never the dominant defect driver.

## The one real finding: position-continuous heading kinks
`planview_issues=82` (`internal_geometry_discontinuity`, 48 distinct roads) turned out to be
genuinely different from everything above: **all 48 affected roads have `xy_gap ≈ 0`** (no
position gap at all) **but heading gaps from 5.1° to a full 180°** — the road centerline is
spatially continuous but its tangent direction snaps to a new angle instantly. Confirmed
**0 of the 48 are junction-connector roads** (all `junction == "-1"`, ordinary roads), so the
established lane-offset exclusion reasoning above does not apply here.

### Root cause: a real blind spot in an established, live gate
`check_geometric_continuity.py::check_planview_internal_seams` (used by both
`stage_06_links.py` and `stage_09_tiling.py`, feeding the live `UP_STRICT_QUALITY_GATES`
pipeline gate) computes `hdg_delta_rad` for every consecutive geometry pair but only ever
*uses* it to classify an already-detected position seam:
```python
if dxy <= float(eps_xy):
    continue   # <-- heading is never checked independently here
```
A pair with `dxy` under the 0.2m position threshold is skipped entirely, regardless of how
large the heading jump is. This function has existed and been live in the pipeline for a
long time; nothing before now exercised the case "position fine, heading badly discontinuous."

### Fix — purely additive, no change to existing pass/fail behavior
`check_planview_internal_seams` gained a new `eps_hdg_only_deg` parameter (default 5.0°,
chosen because the real minimum observed case is 5.1° — comfortably separates genuine kinks
from any sub-degree serialization noise) and a new `heading_only_discontinuities` /
`num_heading_only_discontinuities` field, populated exactly when position is continuous but
heading exceeds the threshold. **`ok`, `seams`, `num_seams`, `max_seam_m`, `worst_road_id`
are completely unchanged** — this function participates in a live, gate-blocking pipeline
stage (auto-repair triggering + `UP_STRICT_QUALITY_GATES`), so changing its existing
pass/fail semantics is a materially different, riskier decision than adding new diagnostic
visibility, and was deliberately not made here without explicit sign-off.

## Verification
- TDD: `tests/unit/test_planview_internal_seams_heading_only.py`, 6 tests — position-
  continuous heading kink now reported; existing `ok`/`seams`/`num_seams`/`max_seam_m` fields
  proven unaffected by the same case; small (2°) heading changes correctly not flagged;
  a genuine position seam is not double-counted into the new list; a custom threshold is
  respected; and a real-data integration test against the actual pinned map confirming
  **exactly 48 affected roads** at the default threshold — matching the manual investigation
  number exactly, independently re-derived through the fixed code path.
- Full unit suite: see commit for exact pass count, 0 regressions expected.

## What this does NOT claim
- This does not mean the map now "passes visual QA" — the thesis's own visual-failure
  description covered detached slabs, malformed junction patches, and broken surface
  continuity, evaluated by actually loading the map in CARLA. This offline finding is a much
  narrower, specific, real defect class (48 roads with a sharp centerline kink) that a live
  render would very plausibly show as a visible bend/crease, but confirming that requires the
  live-CARLA verification this session has been blocked from running throughout (GPU TDR).
- The 48 affected roads are not fixed here (no attempt made to repair their geometry) — this
  pass only makes the defect visible/measurable where it was previously silently skipped by
  the established gate.

## Follow-up root-cause characterization (offline, no fix attempted)
Broke down the 82 kink instances by the geometry-type pair at the transition:
`line->line`: 46, `poly3->line`: 19, `line->poly3`: 16, `poly3->poly3`: 1. The dominant
case (`line->line`, 46/82) is unambiguous: two consecutive raw `<line>` primitives share the
exact same start point but have genuinely different stated `hdg` values — no curve-fitting
interpretation involved, just two straight segments pointing in different directions at the
same point. Since this session's pipeline does not rewrite raw planView `<line>`/`<paramPoly3>`
geometry by default (only adds enrichment data), this is most plausibly an inherent
characteristic of Osm2Odr's own conversion output on these specific short/complex OSM ways,
not something introduced by this pipeline's own stages — not independently confirmed by
tracing Osm2Odr's own (external, C++, not in this repo) source, so held as a plausible
explanation, not a verified one.

**The pipeline already has a purpose-built fix for exactly this class**:
`PlanViewSmoother.smooth_heading_jumps(root, threshold_deg=12.0)`
(`ultimate_pipeline/pipeline_stages/stage_06_links.py:435`), gated behind
`ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING` (default `False` — part of the same "unsafe planview
mutations" family as short-segment-merge, small-geometry-merge, and curvature-only-clamp,
all off by default in the governed/production release profile). This was a deliberate
decision by prior work to keep the mutation off, not an oversight. Enabling it would need a
full pipeline regen to validate it doesn't introduce new seams/connectivity issues elsewhere
(smoothing a road's own heading can shift its endpoint pose, which the road's own link
partners assume is fixed) — a real cost/risk tradeoff, not a quick flag flip. **Deliberately
not enabled in this pass** — flagged as the natural next step if the user wants to pursue it,
not decided unilaterally, matching this session's standing discipline for "unsafe"-flagged
pipeline mutations.
