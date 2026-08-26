# C29 — building `cornerGlobal` frame mismatch: FIXED (canonical regen path)

Both root-cause bugs identified in `C29_building_frame_root_cause.md` are fixed via TDD. **The already-pinned
map `69b1f520` is NOT modified by this task** — see "Pinned-map remediation" below for the decision this leaves
for the user.

## Fix 1 — `ultimate_pipeline/enrichment/osm_polygon_loader.py`
`PROJ_STRING` changed from `+proj=tmerc +lat_0=<gps.lat_min> +lon_0=<gps.lon_min> ...` (a GPS-bbox-corner
origin) to bare `+proj=tmerc +datum=WGS84 +units=m +no_defs` — the same global frame Osm2Odr uses for road
geometry (matches `ultimate_pipeline.domain_gap.local_registration.BARE_TMERC_DEFAULT`). Unused `SETTINGS`
import removed. TDD: `tests/unit/test_osm_polygon_loader_frame.py` (3 tests) — asserts no `lat_0`/`lon_0` in the
proj string, cross-checks against `local_registration`'s bare-tmerc expansion, and confirms a known lat/lon now
projects to global-magnitude coordinates.

## Fix 2 — `scripts/regen_map_of_record.py::_rebase_to_local`
Now also shifts `.//object/outline/cornerGlobal` `x`/`y` (not `z`) by the **same** `(dx, dy)` computed from
road `planView/geometry` bounds. TDD: `tests/unit/test_regen_rebase_buildings.py` (3 tests) — a synthetic XODR
with both road geometry and a building object confirms identical shift, `z` untouched, and the road-only
(no-building) path still works unchanged.

## End-to-end verification (offline, against the REAL pinned data — no live regen run)
Using the real pinned Overpass JSON (`ingolstadt_buildings_overpass.json`) through the **fixed** loader, then
applying the pinned map's own real header offset `(dx=832671.676, dy=5458671.104)`:

| | before fix | after fix |
|---|---|---|
| building/road centroid offset | **7,665.0 m** | **1,558.8 m** |
| building bbox (local, rebased) | n/a (never rebased) | `x[6120, 10738] y[6350, 9782]` |
| road bbox (local) | `x[0, 13267] y[0, 14071]` | (unchanged) |

**80% reduction**, and — critically — the building bbox now sits **properly inside** the road bbox (was
floating almost entirely outside it before). The residual 1,559 m is not evidence of a remaining bug: it's the
expected gap between the whole road network's centroid (includes rural map fringes) and the urban building
cluster's centroid. Independent cross-check: the corrected building bbox (`x[6120,10738] y[6350,9782]`) nearly
matches Grid0828's own footprint at auto-local coordinates (`x[6155,10906] y[6427,9875]`, from
`local_registration.json`) — the buildings now land in the same urban core the manual reference map covers,
which is exactly what a correct fix should produce.

## Regression
619/619 unit tests pass (full suite); no regression in the existing SUMO-guard or building/osm test suites.

## Pinned-map remediation (`69b1f520`) — left to the user, not decided here
The already-pinned map's buildings still carry the pre-fix ~7,665 m offset. Options (unchanged from the
original C29 spec):
- **(a) Leave as-is, documented** (this report is that documentation).
- **(b) Surgical patch** — re-write `69b1f520`'s existing `cornerGlobal` in place using the now-known correction
  `(dx=832671.676-<building's original global x mean base>, ...)`; produces a new sha, needs explicit review.
- **(c) Full re-regen** through the now-fixed canonical path (`scripts/regen_map_of_record.py`) — cleanest, but
  costs a regen cycle and a live-CARLA drivability re-check.

Machine-readable end-to-end numbers reproduced above are computable via the fixed loader + the pinned map's own
header offset; no new JSON artifact was generated for this narrowly-scoped verification.
