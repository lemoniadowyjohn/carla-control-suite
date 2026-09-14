# Codex PROMPT II: reduce the residual building/road coordinate-frame offset

## Context

`ultimate_pipeline/enrichment/osm_polygon_loader.py` projects OSM building
footprints into the same tmerc frame as the road network's `<geoReference>`.
Commit `64e0d03c` (2026-08-26, tracked as `project_c29_building_frame_fix` in
repo memory) fixed a coordinate-frame bug where buildings used a *different*
tmerc origin (`+lat_0=<gps.lat_min> +lon_0=<gps.lon_min>`) than roads, causing a
7665m building/road centroid offset. That fix reduced the offset to ~1559m and
was described as fixed "on the canonical regen path only."

**Verified today (2026-09-14) directly against the current pinned map**
(`campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr`):
road centroid (mean of all 197397 `planView/geometry` start points) is
`(7195.61, 6796.20)`; building centroid (mean of all 35859 `cornerGlobal`
points across 5682 `<object type="building">` elements) is `(7831.90,
8232.93)` — a residual offset of **1571.3m**, consistent with the C29 fix
still holding (not regressed, not the ~6.5km figure an unrelated stale report
cited from an older, pre-C29 candidate — disregard that older number, it does
not describe the current pinned map).

**This residual offset is real and unexplained.** 1571m is far too large to be
floating-point/projection noise. The C29 fix commit message frames it as
"fixed" but the number never reached zero, and nobody has since investigated
*why* a `>1.5km` gap remains between buildings and roads in the same frame.

## Task

1. Reproduce the 1571.3m measurement above independently (do not trust this
   document's number blindly — recompute it against the current pinned map,
   and note if it drifts, which would itself be a signal something else
   changed).
2. Root-cause the residual offset. Candidate hypotheses to check (not
   exhaustive — investigate for real, don't just pick one and stop):
   - A remaining asymmetry between how `osm_polygon_loader.py` projects
     buildings and how the road network's own OSM-to-XODR conversion (whatever
     produces the `<geoReference>` and the base road coordinates) computes its
     origin -- e.g. one uses the OSM source file's raw lat/lon bounds and the
     other uses a slightly different reference point (map center vs. a corner,
     or a stale cached bbox).
   - `scripts/regen_map_of_record.py`'s `_rebase_to_local` step (mentioned in
     the C29 comment as needing extension to also shift `cornerGlobal` points)
     — check whether it fully/correctly rebases building corners in lockstep
     with road geometry, or whether a subset of buildings are rebased
     differently (e.g. based on stale bounds captured before some other stage
     ran).
   - Any building-specific filtering/clipping step that could introduce a
     systematic post-projection shift only for buildings near tile/campaign
     boundaries.
3. Fix the root cause with a real code change (not a manual coordinate patch
   to the pinned map's data). Verify the fix by regenerating buildings for the
   current pinned map (or an equivalent regen-path candidate) and re-measuring
   the centroid offset — it should drop substantially, ideally to sub-meter
   noise. If it cannot reach near-zero, explain precisely why (e.g. buildings
   and roads are legitimately sourced from different OSM extracts with
   slightly different coverage, which would bias a naive centroid comparison
   even with a correct shared frame) rather than declaring success on a
   partial reduction.
4. Add a regression test that would have caught the original 7665m bug AND
   would catch a reintroduction of a >10m-scale offset (pick a real,
   evidence-based threshold, not an arbitrary one) between building and road
   centroids on a real or realistic fixture map.

## Constraints (match this session's established conventions)

- Verify every claim against real pinned-map data before trusting it — this
  document's own 1571.3m number is a starting point, not gospel.
- New commits only, never amend. Never force-push. Never skip hooks.
- Do not promote anything to `auto_map_of_record` or mutate the frozen
  map-of-record. Work against a copy/regen artifact.
- Full test suite via bare `pytest` (not a manually typed path list —
  `pytest.ini`'s `testpaths` covers several directories a manual list misses)
  must stay green: 0 failures.
- If the fix has any nontrivial effect on already-placed building geometry in
  a real regenerated candidate, report the before/after magnitude explicitly
  in your evidence packet (matching the standard this session's other fixes
  set: quantify real-map impact, don't just claim "fixed").
- Push your branch and report status; do not merge into `integration/session-batch1-20260912`
  yourself.
