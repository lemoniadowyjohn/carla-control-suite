# C26 — local registration hardening: hull footprint + building-position recovery

Repo: `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main` (worktree
`worktrees/c26-local-reg-hardening-20260826`) · Branch: `fix/c26-local-reg-hardening-20260826`
(from `fix/post-audit-phase-e-junctions-roundabouts-20260803`) · Interp:
`.venv/Scripts/python.exe` · `UP_DISABLE_CARLA=1`

Scope: `ultimate_pipeline/domain_gap/local_registration.py`, its tests
(`tests/unit/test_local_registration.py`), the RQ1 report
(`reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/C14_RQ1_REPORT.md`) and machine-readable
result (`.../local_registration.json`), and a new regeneration script
(`scripts/regen_local_registration.py`). Did **not** touch
`ultimate_pipeline/core/carla_utils.py` (owned by a concurrent session).

## Part 1 — bbox → convex hull footprint

### What changed
- `manual_geometry_convex_hull(manual_root)`: convex hull vertices of Grid0828's planView
  geometry (native CRS), generalizing the existing `manual_geometry_bbox`.
- `transform_manual_points_to_auto_local(points, ...)`: generalizes
  `transform_manual_bbox_to_auto_local` to an arbitrary point set (bbox transform is now a
  4-corner special case of this).
- `compute_local_registration(auto_xodr, manual_xodr, *, footprint="hull")`: new `footprint`
  kwarg, `"hull"` (default) or `"bbox"` (legacy, kept for side-by-side comparison).
- TDD: 5 new tests, incl. a structural guarantee test
  (`test_hull_polygon_is_subset_of_bbox_polygon_never_larger`, asserts hull area ≤ bbox area
  for an arbitrary point set) and an end-to-end synthetic test proving a road inside the bbox
  "corner" region but outside the hull is dropped by the hull crop and kept by the bbox crop.

### Before/after on the pinned Ingolstadt pair
Pinned pair (verified sha256 against the pin, unchanged from C14):
- auto: `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260819_160350.xodr`,
  sha256 `69b1f52016ebdc3e643616f86161d85789624c94d48e5caf56c53004d534de6e`
- manual: `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr`,
  sha256 `5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c`

| metric | hull (new default) | bbox (legacy, unchanged) | delta |
|---|---|---|---|
| auto roads kept | 3,539 / 32,297 (10.96%) | 6,079 / 32,297 (18.82%) | hull keeps 42% fewer roads |
| road_length ratio (auto/manual) | **2.69×** | **4.5×** | −40% |
| junction ratio (auto/manual) | **3.78×** | **6.05×** | −38% |
| road_count ratio (auto/manual) | **3.57×** | **6.12×** | −42% |
| lane_width_gap | 0.0415 | 0.0415 | unchanged |
| curvature_gap | 0.2192 | 0.2239 | ~unchanged (−2%) |

As expected structurally (hull area ≤ bbox area always), the hull footprint is strictly
tighter — 3,539 kept roads under hull vs. 6,079 under bbox, i.e. the hull crop kept a *subset*
of what the bbox crop kept (verified programmatically: hull is a shrink, never a grow).

### Does the 4.5–6× finding still hold?
**Direction: yes. Magnitude: no — it drops to ~2.7–3.8×.** The original (2026-08-21) report's
"4.5–6× road-network completeness gap" claim was based on the bbox footprint, which is
provably over-inclusive for a non-rectangular manual map like Grid0828 — its corner regions
(inside the bbox, outside the true hull) padded the auto-side road/junction counts with roads
that were never really "in Grid0828's footprint." Under the tighter, more defensible hull
footprint the ratios are materially lower: **~2.7× road length, ~3.8× junctions, ~3.6× road
count**. The qualitative finding (auto has substantially more road-network detail than the
hand-modeled Grid0828 even in the same footprint — OSM captures every service
road/driveway/footway) is unchanged and arguably *more* credible now that the over-inclusive
padding is removed. Both numbers are reported side-by-side (not silently overwritten) in
`local_registration.json`'s `hull`/`bbox` blocks and in the updated `C14_RQ1_REPORT.md`.

## Part 2 — building-position probe

### Investigation
Checked the auto map's building `<object>` elements for a recoverable per-building position.
Direct inspection of `campaigns/.../ingolstadt_perception_map_of_record_20260819_160350.xodr`
(road id `65773`, the single container road holding all 5,686 buildings) found:

- **`<outline><cornerGlobal x="…" y="…" z="…"/></outline>` present on all 5,686/5,686
  buildings** (checked programmatically, not a sample) — an absolute-position polygon outline
  per building, independent of the object's `s="0.0" t="0.0"` road-relative attachment.
- **No `<cornerRoad>` or `<cornerLocal>` children** anywhere in the auto map's building
  outlines (0/5,686). `<cornerLocal>` IS used by the *manual* Grid0828 map's buildings (road-
  relative `u`/`v` offsets from the object's own s/t anchor — a normal, per-road-anchored
  representation, confirmed by inspecting a sample building on Grid0828).
- **No `<userData>` sub-element** on any auto-map building object (0/5,686).

**Verdict: recoverable.** `cornerGlobal` is exactly the "absolute x/y" position source the
task hypothesized (in a more direct form than `userData` would have been) — it gives a full
per-building outline polygon, not just a point.

### A second bug found while wiring this up (real, previously undetected)
`cornerGlobal`'s "Global" naming is misleading: on the pinned pair, building `cornerGlobal`
coordinates are **not** in the same local frame as the road network's planView geometry.
Verified by comparing extents: road planView spans x∈[0, 13267], y∈[0, 14071]; building
`cornerGlobal` spans x∈[−32, 4284], y∈[−200, 2922] — a much smaller range that does not even
overlap correctly with where the roads actually are. Root cause, traced to
`ultimate_pipeline/enrichment/osm_polygon_loader.py`: the OSM building loader projects OSM
lon/lat through `+proj=tmerc +lat_0=<OSM-bbox lat_min> +lon_0=<OSM-bbox lon_min> +x_0=0
+y_0=0`, a **different tmerc origin** than the road network's frame (bare `+proj=tmerc`,
lat_0=lon_0=0, plus the header `<offset>`). The two origins are offset by **(+6547.35,
+6368.80) m** on the pinned pair (computed by projecting the OSM bbox's `(lon_min, lat_min)`
through the auto map's own bare-tmerc + offset pipeline — the exact value pyproj computes,
not a fitted/eyeballed number).

Without correcting for this, every building centroid lands ~6.5/6.4 km away from where it
should be, so **100% of buildings were cropped out under both hull and bbox footprints**
regardless of crop-polygon shape — this was verified as the actual (wrong) behavior before the
frame-shift fix was added. This coordinate-frame bug lives in the building-enrichment step
(`osm_polygon_loader.py` / `building_extruder.py`), not in the crop logic — flagged here as a
genuine, previously-undetected defect. **Out of scope to fix at the source for this task**
(this is RQ1 measurement code, not enrichment-pipeline surgery, and `osm_polygon_loader.py`
was noted as touched by a concurrent session per repo state) — worked around at the
measurement layer by correcting for the known shift before cropping.

### Implementation
- `building_global_centroid(obj, *, shift=(0,0))`: centroid of a building's `cornerGlobal`
  outline, with an optional `(dx, dy)` frame-correction.
- `collect_building_objects(root)`: buildings collected **map-wide** (not scoped to their
  container road) — necessary because the auto map's buildings all sit on one non-
  representative container road.
- `crop_buildings_to_polygon(buildings, polygon, *, shift=(0,0))`: keeps buildings whose
  (shifted) centroid is inside the footprint polygon.
- `building_frame_shift_to_auto_local(osm_lat_min, osm_lon_min, auto_proj4, auto_offset)`:
  recovers the `(dx, dy)` correction by projecting the OSM bbox origin through the auto map's
  own bare-tmerc + offset pipeline (mirrors how the manual map's footprint is itself
  registered).
- `compute_local_registration(..., building_frame_shift="auto")`: resolves the shift from
  `ultimate_pipeline.config.settings.SETTINGS.load_gps_bounds()` by default (matches what
  `osm_polygon_loader.py` used at generation time); accepts an explicit `(dx, dy)` override,
  `(0.0, 0.0)` to disable, or falls back to `(0.0, 0.0)` if settings/gps-bounds are
  unavailable (e.g. isolated unit tests) rather than raising.
- Kept (frame-corrected, in-footprint) buildings are re-homed onto a synthetic zero-length
  holder road in the cropped tree purely so `XODRMapStatsExtractor`'s object-count scan
  (`road.findall(".//object")`) picks them up — does not affect road-length/junction/lane
  stats.
- `local_structural_summary()`: buildings moved out of `construction_differences_excluded`
  into a new `building_density_comparison` block (real in-footprint density comparison, no
  longer force-excluded); `construction_differences_excluded` is now scoped to traffic-lights
  only (still legitimately excluded — Grid0828 models 0 traffic lights at all, a modeling-
  choice difference independent of croppability).
- TDD: 7 new tests covering centroid extraction (with/without `cornerGlobal`, with/without
  shift), map-wide collection, polygon cropping (with/without shift), the shift-derivation
  function (verified against an independent direct pyproj call in the test, not against the
  implementation's own internals), and an end-to-end synthetic in/out-of-footprint building
  crop through `compute_local_registration`.

### Building density results (frame-corrected, in-footprint)
| metric | hull | bbox |
|---|---|---|
| auto buildings kept | 3,779 / 5,686 (66.5%) | 5,232 / 5,686 (92.0%) |
| manual (Grid0828) buildings | 993 | 993 |
| auto buildings / km of road | 26.23 | 21.72 |
| manual buildings / km of road | 18.55 | 18.55 |
| `building_density_gap` | 0.414 | 0.171 |

Both maps now show comparable, plausible building density (auto ~1.2–1.4× manual per km) once
correctly cropped and frame-aligned — a real, moderate, interpretable density difference,
replacing the previous "excluded, 0 vs 993, gap capped at 1.0" placeholder that was an
artifact of the container-road attachment, not a real construction difference.

## Files changed
- `ultimate_pipeline/domain_gap/local_registration.py` — hull footprint functions, building
  recovery/crop/frame-shift functions, `compute_local_registration` gains `footprint` and
  `building_frame_shift` kwargs, `local_structural_summary` restructured.
- `tests/unit/test_local_registration.py` — 7 → 19 tests (all new tests TDD RED→GREEN; the 2
  pre-existing tests touching the changed summary/end-to-end shape were updated to match the
  new (correct) behavior, not weakened).
- `scripts/regen_local_registration.py` — new; reproducible regeneration of
  `local_registration.json` with sha256 source-file provenance and both `hull`/`bbox` blocks.
- `reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/local_registration.json` — regenerated
  via the real pipeline on the pinned pair; now has top-level `hull` and `bbox` blocks (both
  populated) plus `source_files` sha256 provenance, instead of a single bbox-only result.
- `reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/C14_RQ1_REPORT.md` — "Local
  registration" section rewritten to lead with the hull result, report bbox side-by-side,
  document the magnitude-changed-but-direction-held finding, and document the building
  recovery + frame-shift bug + updated density numbers.

## Verification
- `UP_DISABLE_CARLA=1 .venv/Scripts/python.exe -m pytest tests/unit/test_local_registration.py -q`
  → 19 passed.
- `UP_DISABLE_CARLA=1 .venv/Scripts/python.exe -m pytest -q` (full suite) → see commit message /
  session summary for the final count; run from the worktree root before committing.
- Real-pipeline run against the pinned pair (`scripts/regen_local_registration.py`) — output
  captured in `local_registration.json`, sha256-verified against the C1 pin.
