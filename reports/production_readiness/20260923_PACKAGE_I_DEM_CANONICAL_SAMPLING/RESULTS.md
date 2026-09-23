# Package I -- DEM/Elevation Canonical-Sampling Fix Cluster: Results

**Branch:** `fix/dem-elevation-canonical-sampling-v2-20260923`
(started from WIP checkpoint `a070aab9` on
`fix/dem-elevation-canonical-sampling-v1-20260921`, rebased cleanly -- no
conflicts -- onto `origin/integration/production-large-map-20260918` @
`77b6bbfe`)

**Scope note:** the WIP checkpoint's own commit message explicitly flagged it
as "NOT VERIFIED, NOT TESTED". This session verified every claim against
real code and real tests rather than trusting the checkpoint message, and
found the WIP was in a genuinely broken state: the DEM provenance module
had a real `IndentationError` and would not even import, and the
`elevation_gap.py`/`elevation_importer.py` canonical-kernel migrations each
had a distinct crash/correctness regression that were only caught by
writing and running new curved-geometry regression tests (see "Additional
bugs found and fixed" below). None of the 8 issues below were treated as
fixed without a passing, curved-geometry-fixture-based test that would fail
under the pre-fix code.

## Per-issue status

### 1. `check_dem_coverage.py`'s `_get_road_sample_points()` heading-approximated sampling
**Status: FIXED AND VERIFIED.**
Now delegates to `ultimate_pipeline/geometry/opendrive_geometry_kernel.pose_at_s()`
/`endpoint()` for every sample (start/mid/end and evenly-spaced s-values along
multi-geometry roads), instead of extrapolating from the first geometry's
start heading. Verified with an independent-formula arc fixture (curvature
`k=0.05`, length 10m) in
`ultimate_pipeline/tests/unit/test_dem_canonical_sampling.py::test_get_road_sample_points_arc_matches_canonical_curve_not_straight_line`
and `::test_get_road_sample_points_single_sample_uses_canonical_start_pose` --
sampled coordinates match the true arc position to 1e-6m and diverge from the
old straight-line approximation by >0.5m, proving the fixture actually
exercises the fix.

### 2. `check_dem_full_coverage.py` silently ignoring spiral/poly3/paramPoly3
**Status: FIXED AND VERIFIED** (plus one additional real bug found and fixed
along the way -- see below).
`_sample_geometry_canonical()` now delegates to `pose_at_s()` for
spiral/poly3/paramPoly3 geometries that previously produced `prim=None` ->
zero samples (a false-green: a paramPoly3-only road would silently pass
coverage with 0 real evidence). Verified with a paramPoly3 fixture
(`x=10p, y=5p^2`) in
`test_check_dem_full_coverage_samples_parampoly3_instead_of_skipping` --
asserts `total_samples > 0` and that sampled points trace the true
parametric curve (`y == 0.05*x^2`), not zero/degenerate points.

**Additional bug found while verifying this fix:** `check_dem_full_coverage.py`'s
`ET.iterparse` loop called `el.clear()` unconditionally on every element's
`end` event, including primitive children (`<line>`/`<arc>`/`<paramPoly3>`
etc.). Since a primitive child's own `end` event fires *before* its parent
`<geometry>`'s `end` event, this wiped the primitive's attributes (e.g.
`arc`'s `curvature`, or all 8 paramPoly3 coefficients) before the geometry
handler could read them. This bug **pre-dates the WIP** (the `arc` curvature
read was already present in the base code) but was never caught because no
existing test exercised a real curved primitive through
`check_dem_full_coverage()` -- only straight `<line/>` fixtures existed. In
production this meant `check_dem_full_coverage()` silently treated every
`arc` road as if `curvature=0.0` (straight-line sampling) for the entire
lifetime of that function. Fixed by excluding primitive-tag elements from
the per-element `.clear()` call (`check_dem_full_coverage.py`, the loop
bottom) -- they are still freed once their parent `<geometry>` is cleared.

### 3. rasterio unavailable producing a false green
**Status: FIXED AND VERIFIED** (was already fixed correctly in the WIP
checkpoint; re-verified here).
`check_dem_coverage()` now sets `report["ok"] = False`,
`report["reason"] = "rasterio_unavailable"` on `ImportError`, instead of only
appending a warning and returning `ok=True`. Verified in
`test_check_dem_coverage_rasterio_unavailable_fails_closed` by forcing
`sys.modules["rasterio"] = None` (Python's documented way to force an
`ImportError` for an already-installed module) and asserting the fail-closed
report.

### 4. `_safe_float` defaulting malformed attributes to 0.0 in production sampling
**Status: FIXED AND VERIFIED.**
This was **not** addressed in the WIP checkpoint -- `_safe_float` (default
0.0 on any parse failure) was still used both for `road_len` and as the
fallback coordinate source in every `except Exception:` branch of
`_get_road_sample_points()`, meaning a malformed `length`/`x`/`y` attribute
would previously inject a phantom sample at a fabricated coordinate (often
effectively `(0, 0)`) instead of being rejected. Fixed by: (a) removing
`_safe_float` entirely from `check_dem_coverage.py` (it is now dead code,
deleted), (b) strict `float()` parsing with `math.isfinite()` checks for
`road_len` and per-geometry `length`, skipping the whole road/remaining
samples with a warning on failure, and (c) every geometry-sample exception
path now skips the point (appends nothing) instead of falling back to a
`_safe_float`-defaulted coordinate. A `warnings: Optional[List[str]]`
parameter was added to `_get_road_sample_points()` and wired into both
`check_dem_coverage()` and `check_dem_coverage_with_sampler()`'s
`report["warnings"]` so skipped roads/points are visible in the report, not
silent. Verified with
`test_get_road_sample_points_malformed_length_skips_road_not_zero` and
`test_get_road_sample_points_malformed_geometry_attribute_skips_point`.

### 5. `ElevationImporter`'s endpoint computation using straight-line approximation
**Status: FIXED AND VERIFIED** (the WIP's attempted fix was actually broken
-- see below -- and is now genuinely fixed).
`apply_dem()`'s linear-grade endpoint computation now calls
`opendrive_geometry_kernel.endpoint()` on the road's last geometry instead of
`x0 + length*cos(hdg) / y0 + length*sin(hdg)` (which ignored curvature
entirely on curved roads). Verified with an arc-road fixture and a
position-dependent elevation sampler (`z = 0.1*x`) in
`test_apply_dem_linear_grade_uses_canonical_arc_endpoint`: the computed grade
coefficient matches the value derivable from the TRUE curved endpoint
x-coordinate (not the straight-line-extrapolated one, which differs by
>1e-3 in this fixture).

**Bug found while verifying this fix:** the WIP's own endpoint-refactor
introduced a `NameError: name 'hdg' is not defined` that crashed
`apply_dem()` with `linear_grade=True` on **every** road, curved or
straight -- a hard regression, not merely "incomplete." The original code
defined a local `hdg` variable (`hdg = float(gl.get("hdg", "0"))`) while
computing the straight-line endpoint, which was then reused a few lines
later to build sampling-neighborhood candidates
(`_try_neighborhood(x_end, y_end, hdg, eps)`). The WIP's replacement block
called the canonical kernel's `endpoint()` (which returns `pose.heading`)
but never captured it into a variable, so `hdg` was undefined in the normal
(non-exception) path. This is proven by 13 pre-existing tests in
`test_elevation_fallback_policy.py` /
`test_elevation_importer_structure_roads.py` / `test_elevation_grade_clamp.py`
that failed with exactly this `NameError` before the fix and pass after it.
Fixed by capturing `pose.heading` into `hdg_end` and using it consistently
(both success and fallback paths).

### 6. `ElevationGap._sample_geometry_points()` duplicate incomplete evaluator
**Status: FIXED AND VERIFIED** (the WIP's fix was correct in intent but had
a critical regression -- see below -- now genuinely fixed).
`_sample_geometry_points()` now delegates to `pose_at_s()` for all primitive
types instead of its own hand-rolled arc/paramPoly3-only sampler (which
silently mishandled line/spiral/poly3). Verified with an arc fixture in
`test_sample_geometry_points_arc_matches_canonical_curve`.

**Bug found while verifying this fix (the most serious bug found this
session):** the WIP's canonical-kernel delegation computed
`x0 = geom.x + offset_x` / `y0 = geom.y + offset_y` (correctly including the
XODR header offset) but then **never used `x0`/`y0` in the success path** --
it appended `(pose.x, pose.y)` directly from `pose_at_s()`, which evaluates
in the geometry's own offset-less local frame. The header offset was only
applied in the `except Exception:` fallback branch, which normally never
fires. This means the offset was **silently dropped** on every
successfully-canonical-sampled point -- a frame-alignment bug of exactly
the kind flagged as a known hazard in this repo's own memory
(`feedback_population_centroid_not_frame_metric.md`). It broke a
**pre-existing** regression test,
`test_elevation_gap_matches_with_header_offset` (result: two XODRs
representing the SAME physical road, one with an unapplied header offset,
no longer matched -- `matched_count` went from `1` to `0`,
`disabled` flipped `True`). Fixed by adding the offset back onto
`pose_at_s()`'s result (`pose.x + offset_x, pose.y + offset_y`). Re-verified
with the original test (now passing) plus new regression tests
`test_sample_geometry_points_applies_header_offset` and
`test_elevation_gap_end_to_end_matches_with_header_offset`.

Also reverted an unrelated, unverified, out-of-scope change bundled into the
same WIP checkpoint: `_effective_header_offset_xy()`'s magnitude-based
"already-baked-in offset" heuristic was replaced with "read the offset
as-is" in the WIP, with no test coverage for the new behavior and no mention
in the WIP's own commit message. It broke 2 pre-existing regression tests
(`test_effective_header_offset_global_geom_suppresses_offset`,
`test_effective_header_offset_no_geometry_suppresses_offset`). This is not
one of the 8 documented issues, so it was reverted to the original,
tested heuristic rather than adjudicated here.

### 7. `dem_provenance.py` accepting declared CRS/bounds without verifying against the actual raster
**Status: FIXED AND VERIFIED** (the WIP checkpoint did not actually
implement verification -- it only recorded observed values side by side
with no comparison -- and additionally could not run at all; see below).
Added `_compare_declared_vs_observed()` (CRS via pyproj authority-code
normalization, bounds/no_data/resolution via numeric tolerance) and wired it
into two places: (a) `record_dem_provenance(..., verify_against_raster=True)`
now populates `record._provenance_mismatches` (empty list = verified clean,
not merely "not checked"), and (b) a new standalone
`verify_dem_provenance_against_raster(record, path=None)` function that
re-opens the raster and checks a previously-saved record against it,
mirroring the existing hash-based `verify_dem_provenance()`. Wired
`dem_identity_record()` (the one real production call site) to pass
`verify_against_raster=True` and fail closed
(`ok=False, reason="provenance_mismatch"`) on any mismatch. Verified with
4 new tests covering a clean match, a deliberately wrong declared CRS, a
deliberately wrong declared bounds via the standalone API, and a
rasterio-unavailable fail-closed path.

**Bugs found while fixing this (blocking, not merely incomplete):** the WIP
checkpoint's `ultimate_pipeline/dem/dem_provenance.py` had a real
`IndentationError` (`record = DEMProvenance(` was left at column 0, outside
the function body) -- **the entire module failed to import**, meaning
`dem_identity.py` (which imports from it) and its test file
(`test_p07_elv_lan_invariants.py`) were both broken. Additionally,
`record_dem_provenance()`'s new `extra` parameter was passed into
`DEMProvenance(...)` and `DEMProvenance.from_dict(...)` even though the
dataclass had no `extra` field defined -- every call to
`record_dem_provenance()` (including with no new arguments at all) would
have raised `TypeError: unexpected keyword argument 'extra'` once the
indentation bug was fixed, breaking all 4 pre-existing
`TestDemProvenance` tests. Both fixed (indentation corrected; `extra` added
as a real dataclass field, included in `to_dict`/`from_dict`).

### 8. No real vertical-datum truth (inferred from horizontal CRS instead)
**Status: STILL OPEN, with an honest partial mitigation.**
The production vertical datum (`DEM_DATUM = "EGM2008 (Copernicus DEM
geoid-referenced heights)"` in `ultimate_pipeline/tools/phase_f1_dem_provenance.py`)
remains a hardcoded, provider-asserted string, not independently derived
from the DEM file. This is a genuinely hard problem: the overwhelmingly
common case for real DEM sources (including Copernicus GLO-30) is a plain
2D projected/geographic CRS whose heights are referenced to a geoid *by
provider documentation convention only* -- the vertical datum is not
encoded in the raster's CRS metadata at all, so there is no file-derived
ground truth to check the declared string against in the common case.

What was added: `record_dem_provenance(verify_against_raster=True)` now
opportunistically cross-checks against a **compound CRS**'s vertical
sub-CRS when one is present (rare in practice) and flags a mismatch if it
disagrees with the declared value, or fills in the declared value if none
was given. More importantly, every provenance record now carries an honest
`_vertical_datum_source` field -- `"declared_unverified"` for the common
case (plain CRS, no independent check was possible) vs.
`"compound_crs_verified"` (an actual file-derived cross-check occurred) --
surfaced through `dem_identity_record()`'s `vertical_datum_source` field.
This makes the current epistemic state visible in every report instead of
silently implying verification happened, but it does **not** and cannot,
without an external authoritative source of vertical-datum ground truth,
turn the declared string into verified fact for the common (non-compound
CRS) case. Verified with
`test_record_dem_provenance_vertical_datum_source_reports_unverified_for_plain_crs`.

## Summary table

| # | Issue | Status |
|---|-------|--------|
| 1 | check_dem_coverage.py heading-approx sampling | Fixed and verified |
| 2 | check_dem_full_coverage.py skips spiral/poly3/paramPoly3 | Fixed and verified (+ 1 bonus bug: iterparse clear-order wiping arc curvature) |
| 3 | rasterio unavailable false green | Fixed and verified (was already correct in WIP) |
| 4 | `_safe_float` silent 0.0 defaults | Fixed and verified (WIP had not addressed this) |
| 5 | ElevationImporter straight-line endpoint | Fixed and verified (WIP's attempt had a crashing `NameError` regression) |
| 6 | ElevationGap duplicate incomplete evaluator | Fixed and verified (WIP's attempt silently dropped the header offset -- critical regression) |
| 7 | dem_provenance.py unverified declared CRS/bounds | Fixed and verified (WIP module didn't even import; verification logic was also not actually implemented) |
| 8 | No real vertical-datum truth | Still open -- honestly surfaced as unverified rather than fixed; fundamentally requires external ground truth not present in most DEM files |

## Additional (non-listed) bugs found and fixed this session

1. `check_dem_full_coverage.py`: `ET.iterparse`'s per-element `.clear()`
   wiped primitive-child attributes (arc `curvature`, all paramPoly3
   coefficients) before the parent `<geometry>` handler read them --
   pre-existing, not introduced by the WIP, uncaught because no curved-arc
   test previously exercised this function.
2. `elevation_importer.py`: WIP-introduced `NameError: name 'hdg' is not
   defined`, crashing `apply_dem(linear_grade=True)` on every road.
3. `elevation_gap.py`: WIP-introduced silent header-offset drop in
   `_sample_geometry_points()`'s canonical-kernel success path -- a
   frame-alignment bug that broke road matching for any XODR pair using a
   non-trivial header offset.
4. `dem_provenance.py`: WIP-introduced `IndentationError` (module failed to
   import at all) and a `TypeError`-on-every-call bug (`extra` kwarg with
   no matching dataclass field).
5. Reverted an unrelated, untested, test-breaking change to
   `_effective_header_offset_xy()`'s heuristic bundled into the same WIP
   checkpoint (out of scope for the 8 documented issues; see issue 6 above).

## Test evidence

New regression test file:
`ultimate_pipeline/tests/unit/test_dem_canonical_sampling.py` -- 16 tests,
all passing, each using a curved-geometry (arc or paramPoly3) XODR fixture
compared against an independently-computed closed-form expected position
(not merely "the code calls the canonical kernel").

Full bare `pytest` run from repo root (testpaths spans all 12 directories
per `pytest.ini`, 5974 items collected): **see companion note in this
directory / commit message for the final pass/fail counts** -- captured
after the run completed, per this repo's verification-before-completion
convention.

All previously-existing tests touching the 5 changed files (
`test_elevation_gap.py` (16), `test_p07_elv_lan_invariants.py` (21 incl.
seam fixer/lane invariants), `test_dem_f1.py` (16),
`tests/unit/test_c9_tail_gate_controls.py` (36 incl. 11 non-DEM checkers),
`test_elevation_fallback_policy.py`, `test_elevation_importer_structure_roads.py`,
`test_elevation_quality_gates_nan.py`, `tests/unit/test_elevation_grade_clamp.py`)
pass after these fixes.

## Files changed

- `ultimate_pipeline/quality/check_dem_coverage.py`
- `ultimate_pipeline/quality/check_dem_full_coverage.py`
- `ultimate_pipeline/enrichment/elevation_importer.py`
- `ultimate_pipeline/domain_gap/elevation_gap.py`
- `ultimate_pipeline/dem/dem_provenance.py`
- `ultimate_pipeline/dem/dem_identity.py` (new: wires `verify_against_raster=True`
  and fails closed on provenance mismatch)
- `ultimate_pipeline/tests/unit/test_dem_canonical_sampling.py` (new)

Not touched: `submission/infrastructure/ultimate_pipeline/...` mirror copies
of `check_dem_coverage.py`/`check_dem_full_coverage.py` -- per
`reports/post_audit_hardening/MIRROR_DRIFT_ADJUDICATION.md`, that tree is a
frozen thesis snapshot and none of these files are in the
`CRITICAL_MIRRORED_FILES` sync allow-list.
