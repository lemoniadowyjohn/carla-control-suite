# Codex — PROMPT GG: finish the paramPoly3 geometry-primitive blind-spot sweep

## Context

This session found and fixed the same class of bug 4 independent times: a function reads a
`<geometry>` element's position/endpoint/curvature by explicitly checking for `<arc>` (sometimes also
`<spiral>`/`<poly3>`), then silently falls through to a **straight-line extrapolation** for anything
else — which in practice means **paramPoly3**, this pipeline's dominant real geometry type (22311/32267
roads, ~69%, on the pinned map-of-record are a single paramPoly3 segment with no `<arc>` at all).

Confirmed instances, each fixed by routing through the shared, already-tested
`ultimate_pipeline/geometry/opendrive_geometry_kernel.py` (`sample()`/`endpoint()`/`pose_at_s()` — exact
for arc, analytically-derived for paramPoly3/poly3/spiral, unchanged for line), falling back to the old
straight-line approximation only when a geometry has no recognized primitive at all:

- `ultimate_pipeline/topology/structure_scanner.py` (`b01d19c8`) — curvature-anomaly diagnostic was
  blind to 69% of roads.
- `ultimate_pipeline/tile_validation/geometry_seam_checker.py` +
  `ultimate_pipeline/tile_validation/lane_seam_checker.py` (`26873ff3`) — tile-boundary continuity
  checker computed wrong seam positions, up to 5m off on a real curved example, causing both false
  discontinuity flags and false lane-match failures.
- `ultimate_pipeline/geometry/mesh_continuity_repairer.py` (`47d9c7b2`) — **the most severe**: this one
  is LIVE, default-on, unconditionally invoked from `stage_06_links.py`, and actually MUTATES x/y/hdg
  based on the miscalculated gap. 16 real, genuinely-continuous roads were being spuriously modified on
  every pipeline run before the fix (one example: an 8.9m false "gap" where the true gap was ~1
  micrometer). Read this commit's message in full — fixing the paramPoly3 math alone was NOT enough; it
  exposed a second, previously-masked bug (`scan_roads()` never advanced its `prev` element reference
  across loop iterations) that made the first attempt at this exact fix MUCH worse before it was caught
  by verifying against the real pinned map before committing (16 false positives became 6723). This is
  the precedent to follow: never trust a fix in this bug class without re-running it against the real
  map and checking the counts move the right direction, not just "the code looks right."
- Also confirmed independently by your own CC work: `roundabout_v2/core.py`'s original detector required
  literal `<arc>`/`<spiral>` tags or a topology marker, missing 100% of real roundabouts until PROMPT EE
  added OSM-spatial detection as a separate path (not a fix to the arc-only check itself, which is still
  there and still only relevant to its own narrow `TOPOLOGY_HIGH` detection path — out of scope for this
  prompt, already handled).

The remaining files below still contain a `.find("arc")` (or similar) check and have **not** been
individually verified this session. Most are probably fine (this session already confirmed
`check_carla_opendrive_compat.py`, `check_geometric_continuity.py`, `autofix_postprune_elevation.py`,
`domain_gap/curvature_gap.py`, and `domain_gap/frechet_gap.py` are all clean — they either only use the
arc check for type CLASSIFICATION/labeling with an explicit paramPoly3 branch elsewhere, or they already
have dedicated, correct paramPoly3 sampling). But this pattern has now had a false-negative rate of 4/10
on the files actually checked, including the most severe live-mutation bug found all session, so the
remaining ones need the same rigor, not a skim.

## PROMPT GG

```text
Repository: lemoniadowyjohn/carla-control-suite. Base branch: integration/session-batch1-20260912 at
or after 47d9c7b2 (has all 4 confirmed fixes above already merged). Isolated branch:
feature/parampoly3-blind-spot-sweep-v1-<date>.

TASK 1: for each of the following files, determine whether its arc-specific geometry handling does
POSITION/ENDPOINT/CURVATURE MATH that silently mishandles paramPoly3 (the buggy pattern -- matches
mesh_continuity_repairer.py/the seam checkers/structure_scanner.py before their fixes), or whether it
only uses the arc check for TYPE CLASSIFICATION with paramPoly3 already handled correctly elsewhere
(the safe pattern -- matches check_geometric_continuity.py/autofix_postprune_elevation.py). State which
category each file falls into, with the specific line numbers and reasoning, before touching anything:

  ultimate_pipeline/diagnostics/xodr_cropper_gps.py
  ultimate_pipeline/domain_gap/elevation_gap.py
  ultimate_pipeline/domain_gap/geo_alignment.py
  ultimate_pipeline/domain_gap/map_stats_xodr.py
  ultimate_pipeline/domain_gap_gnn/graph_builder.py
  ultimate_pipeline/experiments/rl_fuzzer.py
  ultimate_pipeline/geometry/lane_seam_checker.py   <- NOTE: different file from the already-fixed
                                                        tile_validation/lane_seam_checker.py; a quick
                                                        grep this session found the same arc-only
                                                        pattern here (line ~31) but it was NOT verified
                                                        or fixed -- check this one first, it's the most
                                                        suspicious given its sibling was a real bug.
  ultimate_pipeline/geometry/planview_smoother.py
  ultimate_pipeline/pipeline_stages/stage_06_links.py
  ultimate_pipeline/quality/xodr_strict_validator.py
  ultimate_pipeline/roadrunner/alignment.py
  ultimate_pipeline/tools/junction_connector_rebuild.py
  ultimate_pipeline/topology/junction_connector_rebuild.py   <- NOTE: different file from the tools/
                                                                 one above, check both independently
  ultimate_pipeline/topology/roundabout_rebuilder.py
  ultimate_pipeline/topology/roundabout_reconstructor.py
  ultimate_pipeline/topology/topology_repair.py
  ultimate_pipeline/topology/topology_validation.py
  ultimate_pipeline/visualization/curvature_drift_plot.py
  ultimate_pipeline/visualization/heatmap_generator.py
  ultimate_pipeline/visualization/lane_overlay.py
  ultimate_pipeline/visualization/map_diff.py
  ultimate_pipeline/visualization/map_plotter.py

For the visualization/ files specifically: confirm whether they're purely cosmetic (a wrong preview
image) or feed into any quality gate/report a human or downstream tool relies on for correctness
judgments -- the severity bar is different for "the debug plot looks slightly off" vs. "a gate silently
passed because its input rendering was wrong."

TASK 2: for every file confirmed to have the buggy pattern (position/endpoint/curvature math, not just
classification), fix it the same way as the 4 precedents: route through
opendrive_geometry_kernel.py's sample()/endpoint()/pose_at_s(), falling back to the old straight-line
behavior only when a geometry has no recognized primitive at all. If a file MUTATES geometry (like
mesh_continuity_repairer.py did), apply the same extra rigor: verify the fix against the real pinned
map BEFORE and AFTER, and explicitly check for the same class of second bug that surfaced there (a
stale element reference across a loop, or any other place where a "prev"/"context" object doesn't
actually correspond to the values being used to compute against it) -- do not assume a clean fix on the
first attempt is correct without that check.

TASK 3: for every file confirmed to be already-safe (classification-only or already-handles-paramPoly3),
do not touch it -- just report the confirmation with line references, matching this session's established
practice of not re-litigating things that are already correct.

TASK 4: for each buggy file that gets fixed, add regression tests following the established pattern in
this session's 4 precedent commits (a synthetic curved paramPoly3 fixture with a hand-computed true
endpoint, a negative control, RED-verified via git stash before the fix, GREEN after). For any file that
mutates real geometry, also verify the real-map before/after counts move in the expected direction
(fewer false positives, not more) the same way commit 47d9c7b2 did -- this is not optional given that
exact precedent.

TASK 5: run the full offline test suite. Confirm you're not undercounting due to a sparse checkout (see
this session's own discovery that a sparse `!**/*.xodr` pattern was making a fully-green branch look
like it had 27 failures -- state whether your worktree is sparse or full). Do not promote anything to
auto_map_of_record.

End with:
TASK_1_CLASSIFICATION: <file>: SAFE (why) | BUGGY (why), for every file listed above
TASK_2_FIXES_APPLIED: <list of files fixed, with real-map before/after numbers for any that mutate geometry>
TASK_3_CONFIRMED_SAFE: <list of files confirmed safe, unchanged>
TASK_4_NEW_TESTS: <count, and RED/GREEN confirmation method used per fix>
TASK_5_FULL_OFFLINE_TESTS: PASS | FAIL -- <sparse or non-sparse, confirmed>
MAP_OF_RECORD_MUTATED: NO
```
