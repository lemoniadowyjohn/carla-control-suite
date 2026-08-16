# C9 Tail-Gate Positive/Negative Controls

**Branch:** `fix/c9-tail-gate-controls`
**Worktree:** `worktrees/c9-tail-gate-controls` (rooted at `eb5ddc71`)
**Date:** 2026-08-16
**Scope:** Add positive + negative unit-test controls for the 13 checkers flagged in
`reports/post_audit_hardening/C9_GATE_CORRECTNESS.md` as having **no dedicated unit
tests at all**. Test-only change — no checker implementation was modified.

**New file:** `tests/unit/test_c9_tail_gate_controls.py` (35 tests total: 13 positive
controls, 15 negative controls, plus 7 additional controls for checkers that expose
more than one distinct code path/behavior worth separately proving — see table).

## Verdict

```
C9_TAIL_CONTROLS_ADDED covered=13/13 defects_found=0
```

All 13 flagged checkers now have at least one positive control (clean fixture -> no
issue) and at least one negative control (same fixture + one deliberate defect ->
issue flagged), and every checker passed both on the first real run — no checker
needed a weakened assertion to pass, and none was found to be silently broken.

## Per-checker coverage table

| # | Checker (`ultimate_pipeline/quality/...`) | Covered | Positive control fixture | Negative control fixture (injected defect) | Notes |
|---|---|---|---|---|---|
| 1 | `check_dem_coverage.py` | Y | `check_dem_coverage_with_sampler`: 2-road XODR, sampler returns `(100.0, True)` for every point -> `ok=True`, `valid_ratio=1.0` | Sampler returns `(None, False)` for every point -> `ok=False`, `valid_ratio=0.0`. Plus a 3rd control: `check_dem_coverage()` (the real CRS-aware entry point) with a real flat GeoTIFF but **no `<geoReference>`** in the XODR header -> fails closed with `reason="no_georeference"`, exercised directly since it is the actual behavior gating pipeline runs | Used the `_with_sampler` variant for the core threshold logic since the CRS/rasterio path needs a real georeferenced DEM; added a 3rd test hitting the real `check_dem_coverage()` fail-closed path with an actual GeoTIFF (no CRS, to avoid a local PROJ/pyproj database version conflict — see Environment note) |
| 2 | `check_dem_full_coverage.py` | Y | Sampler returns `(100.0, True)` for every point -> `ok=True`, `coverage_ratio=1.0` | Sampler returns `(None, False)` for every point -> `ok=False`, `coverage_ratio=0.0`, `uncovered_examples` populated | Function unconditionally opens the DEM tif even in sampler mode, so a real (tiny, CRS-less) GeoTIFF fixture is created via `rasterio` in `tmp_path` |
| 3 | `check_determinism.py` | Y | Two structurally identical 2-road XODR files -> `deterministic=True`, `hash_a==hash_b` | Second file's road-2 length changed from 10.0 to 12.5 (> the 0.1m compare tolerance) -> `deterministic=False`, `hash_a != hash_b`, `total_road_length` reported in `differences` | |
| 4 | `check_drivability_smoke.py` | Y (partial, documented) | `CARLA_AVAILABLE` monkeypatched to `False` -> non-blocking `ok=True` skip pass | Nonexistent XODR path -> `ok=False`, explicit `"not found"` error | Real `carla` Python bindings ARE importable in this venv, so a true "spawns + ticks" happy-path control would require a live CARLA server (out of scope, offline-only task). Verified from source that `os.path.exists(xodr_path)` is checked **before** `carla.Client(...)` is constructed, so the negative control never attempts a network connection. See "Partial coverage" section below |
| 5 | `check_elevation_missing_and_cliffs.py` | Y | Two roads, matching z=100 at the link boundary -> `ok=True`, `zero_ratio=0.0`, `max_link_dz=0.0` | Two controls: (a) road 1 ends z=100, successor road 2 starts z=500 (400m cliff) -> `ok=False`, `max_link_dz≈400.0`; (b) a road with no `<elevationProfile>` at all -> `zero_ratio=1.0` exceeds `max_zero_ratio` -> `ok=False` | Both catastrophic patterns the checker's docstring claims to detect (missing elevation, cliffs) are separately exercised |
| 6 | `check_elevation_profile.py` | Y | Gentle grade (`b=0.05`, threshold `0.2`) -> `invalid_found=False`, `spikes=[]` | Two controls: (a) steep grade `b=0.9` > threshold -> non-empty `spikes` list with `grade≈0.9`; (b) non-finite `a="nan"` coefficient -> `invalid_found=True` | Function returns `(report, invalid_found)`; `invalid_found` tracks parse/finite-ness, NOT grade spikes, which live per-road in `report["roads"][i]["spikes"]`. Both signals are independently covered rather than conflating them |
| 7 | `check_elevation_seams.py` | Y | Single flat 50m road, sampled every 5m -> `ok=True`, `max_jump=0.0` | Same road with a 2nd `<elevation>` record injecting a 20m step at s=25 -> `ok=False`, `max_jump≈20.0` (verified this exceeds both `max_jump_m` and the `p95`+`bad_fraction` failure paths) | This checker samples *within* a single road's own elevation polynomial (not cross-road), confirmed by re-reading the sampling loop before writing fixtures |
| 8 | `check_lane_geometry_continuity.py` | Y | Two-laneSection road, lane width 3.5m -> 3.5m across the boundary -> `ok=True`, `n_issues=0` | Same road, width jumps 3.5m -> 6.0m across the boundary (exceeds default `lane_width_eps=0.10`) -> `ok=False`, `type="lane_width"` issue recorded | C10 may touch this file's *implementation*; this test only calls the public function and does not depend on internal repair logic |
| 9 | `check_lane_link_targets_exist.py` | Y | Lane -1 in section 0 has `<successor id="-1"/>`, which exists in section 1 -> `ok=True`, `num_issues=0` | Same fixture but successor points at id `-2`, which does not exist in the next laneSection -> `ok=False`, 1 issue, `direction="successor"`, `target_lane_id=-2` | |
| 10 | `check_lane_width_continuity.py` | Y | Two-laneSection road, width 3.5m -> 3.5m -> `ok=True`, `num_issues=0` | Two controls: (a) width `a=0.0` (<= `min_width`) -> flagged `type="nonpositive_width"`; (b) width jumps 3.5 -> 6.0 across the boundary (> `max_jump=1.0`) -> flagged `type="width_jump"` | Both defect classes named in the checker's own docstring ("non-positive widths" and "sudden width jumps") are independently covered. C10 may touch this file's implementation; test only calls the public function |
| 11 | `check_origin_sanity.py` | Y | Two roads near (0,0)/(100,100) -> centroid well under the 50,000m warn threshold -> `ok=True`, no warnings | Road placed at (1,000,000, 1,000,000) — simulating an un-subtracted raw UTM easting/northing bug — exceeds `fail_distance_m=500,000` -> `ok=False`, warning text `"exceeds fail threshold"` | |
| 12 | `check_post_tiling_integrity.py` | Y | Two linked roads, unique IDs, consistent link/contactPoint pairing -> `ok=True`, `issues=[]` | Two controls: (a) two `<road id="1">` elements -> flagged `type="duplicate_road_ids"`; (b) road 1's successor points at nonexistent road id `99` -> flagged `type="orphan_road_link"` | This checker delegates seam-endpoint sanity to C6's `check_geometric_continuity` (out of scope to depend on/modify per task boundaries). Controls instead target this module's own direct logic (duplicate-ID and orphan-link detection), which is unaffected by C6's concurrent edits and keeps this test decoupled from the sibling C10/C6 work |
| 13 | `check_xodr_schema.py` | Y | `check_xml_uniqueness`: unique road ids + unique (road, laneSection, side, laneId) tuples -> `issues=[]`. `validate_xodr_schema` with `xsd_path=None` (the actual call pattern used everywhere in the pipeline, e.g. `crash_safe_length_repair.py`) -> `(True, None)` | Three controls: (a) duplicate road id -> 1 issue containing `"Duplicate road id"`; (b) duplicate lane id within the same road/laneSection/side -> 1 issue containing `"Duplicate lane id"`; (c) a real minimal XSD requiring a `<header>` child, validated against an XODR file missing `<header>` -> `(False, <error message>)`, plus a positive counterpart with `<header/>` present -> `(True, None)` | Went beyond the `xsd_path=None` skip-path to also exercise the real `lxml` XMLSchema validation branch, since that is the actual "schema" claim in the module name |

## `CHECKER_DEFECT_FOUND` items

**None.** All 13 checkers behaved correctly against both their positive and negative
control fixtures on the first real test run — no checker required a weakened
assertion, a workaround, or was found to silently pass a genuine defect.

## Partial-coverage note: `check_drivability_smoke.py`

This checker is fundamentally CARLA-runtime-dependent (spawns a vehicle, ticks the
world, checks routing) — its true "happy path" cannot be exercised offline without a
live CARLA server, which is out of scope for this task (`UP_DISABLE_CARLA=1`, no live
data/CARLA). Two deterministic, offline-reachable branches were covered instead:

1. **Positive-ish control:** `CARLA_AVAILABLE=False` (monkeypatched) proves the gate
   is *non-blocking* when the CARLA Python API itself is absent — `ok=True` with a
   "skipped" warning, not a silent hard failure.
2. **Negative control:** a nonexistent XODR path fails closed (`ok=False`) with an
   explicit error message, deterministically, before any network call is attempted
   (confirmed from source: `os.path.exists(xodr_path)` at line 103 precedes
   `carla.Client(host, port)` at line 113).

A true CARLA-server-backed spawn/tick positive control is recommended as a follow-up
integration test (not a unit test) once a live CARLA harness is available in this
repo's test infrastructure — out of scope here.

## Environment note

`check_dem_coverage.py` / `check_dem_full_coverage.py` fixtures use **CRS-less**
GeoTIFFs (no `crs=` argument passed to `rasterio.open(..., 'w', ...)`). Attempting to
write a GeoTIFF with an explicit CRS (e.g. `EPSG:32632`) in this venv raises
`rasterio.errors.CRSError` due to a PROJ database version mismatch between rasterio's
bundled PROJ and this environment's `pyproj` installation
(`DATABASE.LAYOUT.VERSION.MINOR = 4` vs required `>= 6`). This is a local environment
quirk, not a checker defect, and does not affect coverage: `check_dem_full_coverage`'s
sampler-injected path and `check_dem_coverage_with_sampler` are both CRS-agnostic, and
the one control that needed the real CRS-aware `check_dem_coverage()` entry point
(`test_check_dem_coverage_missing_georeference_fails_closed`) only needs the **XODR**
header to lack `<geoReference>` — it never reaches DEM CRS transformation.

## Full offline suite result

Command: `UP_DISABLE_CARLA=1 <venv>\python.exe -m pytest` from inside the worktree.

```
6 failed, 2901 passed, 79 skipped, 84 warnings in 90.63s
```

All 35 new tests in `tests/unit/test_c9_tail_gate_controls.py` pass. The 6 failures
are pre-existing and unrelated to this change (confirmed present on a run prior to
adding the new test file, in unrelated modules never touched by this task):

- `tests/quality/test_ingolstadt_coordinate_verification.py::TestCoordinateCandidateHashes::test_actual_reprojection_hash`
- `tests/quality/test_ingolstadt_coordinate_verification.py::TestCoordinateCandidateHashes::test_alignment_transform_only_hash`
- `tests/quality/test_ingolstadt_coordinate_verification.py::TestCoordinateCandidateHashes::test_correct_georeference_hash`
- `tests/quality/test_ingolstadt_coordinate_verification.py::TestCoordinateCandidateHashes::test_metadata_only_hash`
  (all four: SHA256 hash-pinned fixture assertions that no longer match candidate
  file content — unrelated coordinate/georeference candidate regression, not a
  quality-gate checker)
- `tests/test_r13_c0r_tag_freeze.py::test_r13p_manifest_sorted_hashes_match_no_provisional`
  (SHA256 mismatch against a manifest-pinned report file)
- `tests/test_stage_i_integrity.py::test_T19_idempotent_re_enrich`
  (`FileNotFoundError: [WinError 2]` from `subprocess.run([PY, "stage_i1_crosswalk_writer.py"], ...)`
  — looks like a Windows-path/subprocess environment issue unrelated to this task)

None of these touch any of the 13 checkers in scope, `check_geometric_continuity.py`
(C6), `check_elevation_continuity.py`/`elevation_summary.py`/`full_map_metrics.py`
(C9, already fixed), or `perception/` (C8).
