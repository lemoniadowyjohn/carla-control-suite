# Line/Arc Canonical Evaluator — Production Integration Report (I01)

**Date:** 2026-07-29
**Branch:** `deepseek-observability-integration-verification` (HEAD `faa20bb5`)
**Scope:** Make `opendrive_geometry/` the single production authority for read-only Line/Arc geometry evaluation, per prompt I01.

## 1. Canonical package resolved

`opendrive_geometry/` at the repository root (`model.py`, `primitives.py`, `evaluator.py`, `errors.py`) is the sole package resolved by every bare `import opendrive_geometry` / `from opendrive_geometry...` statement in the codebase — verified by grepping every import site repository-wide.

A lookalike package exists at `ultimate_pipeline/opendrive_geometry/` with an incompatible, different API (local-frame convention: `s` normalized to `[0,1]`, pose field named `h` instead of the OpenDRIVE-standard `hdg`). It is **never** imported via the bare name — only via its fully-qualified path `ultimate_pipeline.opendrive_geometry`, exclusively from test files (`test_geometry_evaluators.py`) and from `reports/geometry_structure_discovery.md`, which already documents it as **INACTIVE — zero production callers, zero tests**, recommended for deletion. There is no live import ambiguity.

**Result: no `BLOCKED_IMPORT_AMBIGUITY`.**

## 2. Façade

`opendrive_geometry/evaluator.py` already implements the required façade exactly as specified: `RangePolicy(STRICT/CLAMP/EXTRAPOLATE)`, `EvaluationPolicy(range_policy, arc_linearization_epsilon, include_endpoint=True)`, and `LineArcEvaluator` with `pose_at`, `endpoint`, `sample`, `curvature_at`, `bounds`. This predates this session (found in the working tree at session start). It also contains a `ParamPoly3Evaluator` from a separate, later batch — untouched by this work, out of I01 scope.

## 3. Consumers migrated (10 files, 3 groups)

| File | Group | Status |
|---|---|---|
| `ultimate_pipeline/domain_gap/elevation_gap.py` | A | pre-existing at session start |
| `ultimate_pipeline/domain_gap/geo_alignment.py` | A | pre-existing at session start |
| `ultimate_pipeline/quality/check_dem_full_coverage.py` | A | pre-existing at session start |
| `ultimate_pipeline/quality/check_geometric_continuity.py` | B | pre-existing at session start (Line/Arc only; Spiral/Poly3/ParamPoly3 dispatch untouched — see §4) |
| `ultimate_pipeline/tile_validation/geometry_seam_checker.py` | B | pre-existing at session start |
| `ultimate_pipeline/geometry/lane_seam_checker.py` | B | pre-existing at session start |
| `ultimate_pipeline/visualization/lane_overlay.py` | C | pre-existing at session start |
| `ultimate_pipeline/visualization/heatmap_generator.py` | C | pre-existing at session start |
| `ultimate_pipeline/visualization/map_plotter.py` | C | **migrated this session** |
| `ultimate_pipeline/visualization/map_diff.py` | C | **migrated this session** |

For the two files migrated this session: only the `line`/`arc` branches of each `_sample_geometry` function were replaced with calls to a module-level `LineArcEvaluator(EvaluationPolicy(range_policy=RangePolicy.CLAMP))` instance (matching the precedent set by `lane_overlay.py`/`heatmap_generator.py`), preserving the original sampling loop structure, function signatures, and (in `map_plotter.py`) the untouched `spiral` branch.

## 4. Mixed primitive behavior preserved (Section 4)

`check_geometric_continuity.py` delegates only `_pose_line`/`_pose_arc` to the canonical `LineArcEvaluator`; `_pose_spiral_numeric`, `_pose_poly3`, and paramPoly3 dispatch remain separate (paramPoly3 already delegates to the canonical `ParamPoly3Evaluator`, added in an earlier, separate batch — not touched here). `tests/unit/test_geometric_continuity_migration.py` already contains `TestMixedChain` (3 tests) and `TestOtherPrimitivesUnchanged` (13 tests) proving non-Line/Arc results are unaffected. All 16 pass.

## 5. Compatibility wrappers retained (Section 6)

**None needed.** Every helper function replaced during migration (`_sample_geometry`, `_pose_line`/`_pose_arc`, `_sample_line`/`_sample_arc`, `_endpoint`) is a module-private, underscore-prefixed function called only from within its own file. A repository-wide grep for each name found zero external or dynamic (`getattr`/`importlib`) callers. Since nothing outside these 10 files could break, no temporary compatibility shim was required for any migration, this session's or pre-existing.

## 6. Inline formulas remaining (out of I01 scope)

See `reports/remaining_inline_geometry_implementations.json` for the full, structured list. Summary:

1. `ultimate_pipeline/geometry/geometry_math.py` — `GeometryCalculator._integrate_line()`/`_integrate_arc()`, EPS=1e-9 — not in Groups A/B/C.
2. `ultimate_pipeline/topology/junction_connector_rebuild.py` — `_arc_endpoint()` (lines 225-239), local-frame formula, EPS=1e-12 — not in Groups A/B/C.
3. `ultimate_pipeline/tile_validation/lane_seam_checker.py` — `_sample_geometry()` (line 70) — a **distinct file** from the already-migrated `ultimate_pipeline/geometry/lane_seam_checker.py`; discovered during this session's repo-wide audit; not in Groups A/B/C.
4. `submission/infrastructure/ultimate_pipeline/*` — a full mirror of `ultimate_pipeline/`. Confirmed **stale**: its copy of `check_geometric_continuity.py` has no canonical-evaluator imports at all, unlike the root copy. Per `reports/geometry_structure_discovery.md` §8, this mirror must not be edited directly — it is refreshed by a separate submission/export process.

## 7. Expected differences

- **`map_plotter.py` / `map_diff.py`:** golden-output comparison (6 and 5 representative line/arc/near-zero-curvature cases respectively, captured before and after migration) shows **`max_dx = max_dy = 0.0`** in every case — bit-for-bit identical output. `opendrive_geometry/cross_compare_implementations.py` independently confirms **`map_plotter: ALL OK`** and **`map_diff: ALL OK`** (0.00e+00 across all 20 benchmark cases). This is because both files' original inline formulas already matched the canonical math; the migration is a behavior-preserving refactor for these sampled points.
  - As a side effect, this migration silently fixes two known bugs already flagged in `reports/geometry_structure_discovery.md` (map_plotter sentinel-radius risk at exact zero curvature, map_diff's separately-computed line/arc paths at the near-zero-curvature boundary). This is confirmed by `tests/opendrive_geometry/test_existing_implementations.py::TestMapPlotterNoBugs` / `::TestMapDiffNoBugs` — five tests that were already present in the working tree (written in anticipation of this exact migration) and now pass against the migrated code.
- **Other files** (`geometry_calculator`, the `local_frame` reference snapshot used by the benchmark, `junction_connector_rebuild`, out of I01 scope): the cross-comparison benchmark shows small, pre-existing, already-documented floating-point/EPS-policy differences (~5e-9 to 5e-11 rad heading at the 1e-9-vs-1e-12 near-zero-curvature boundary, ~7e-15 to 2.8e-14 in x/y) that exactly match the table already published in `opendrive_geometry/FOUNDATION-01A_INTEGRATION_PROPOSAL.md`. These are unrelated to this session's changes — they belong to files this migration does not touch.

## 8. Unexpected differences

None found.

## 9. Semantic hashes before/after

Both migrated functions are structurally read-only: a grep for `.write(`, `SubElement`, `.set(`, `.remove(` in `map_plotter.py` and `map_diff.py` found only benign list-append calls, no XML tree mutation, before and after migration. Confirmed empirically:

| Fixture | Geometries | SHA-256 before | SHA-256 after | Result |
|---|---|---|---|---|
| `external/esmini/resources/xodr/straight_500m.xodr` | 1 (line) | `5361b789...` | `5361b789...` | unchanged |
| `external/esmini/resources/xodr/curves.xodr` | 13 (line+arc mix) | `46df896b...` | `46df896b...` | unchanged |

Road count, junction count, geometry attributes, lane content, laneLinks, elevation, signals, and objects: unaffected — neither migrated function reads or touches anything outside `planView/geometry` elements, and does so read-only.

## 10. Focused test result

```
python -m pytest ultimate_pipeline/tests/unit/test_opendrive_geometry_line_arc.py \
  ultimate_pipeline/tests/unit/test_elevation_gap.py \
  ultimate_pipeline/tests/unit/test_geo_alignment_rigid_scale_lock.py \
  ultimate_pipeline/domain_gap/tests/test_geo_alignment.py -q
```
**120 passed, 0 failed.**

`python -m pytest tests/opendrive_geometry -q` — **2202 passed, 78 skipped, 0 failed** (with `__pycache__` cleared; see note below).

**Note on a caching artifact:** the first run of `tests/opendrive_geometry` showed 5 failures in `TestMapPlotterDetectedBugs`/`TestMapDiffDetectedBugs` — classes that do not exist anywhere in the current source (confirmed by grep). The `__pycache__/test_existing_implementations.cpython-312.pyc` predated the current source's mtime and was stale. Deleting `tests/opendrive_geometry/__pycache__` and re-running with `-B -p no:cacheprovider` produced a clean 2202/0.

## 11. Cross-comparison benchmark

`python opendrive_geometry/cross_compare_implementations.py` — `map_plotter`, `map_diff`, `canonical`, and `geometry_seam_checker` (already migrated) all report **ALL OK**. Script's overall verdict ("Some disagreements found") is driven entirely by out-of-scope files (§6, §7) — none of the disagreements involve this session's changes.

## 12. Non-CARLA test result

```
python -m pytest -m "not carla" -q
```
**367 passed, 1 skipped, 0 failed** (152.98s; `testpaths = ultimate_pipeline/tests, tests/unit` per `pytest.ini`).

`python -m compileall opendrive_geometry ultimate_pipeline tests -q` — clean, no errors.

## 13. Rollback commit

**There is none.** `git ls-files` confirms zero commits ever touched `opendrive_geometry/`, any of the 10 consumer files listed in §3, or `tests/unit/test_geometric_continuity_migration.py` — the entire I01 feature (canonical package, façade, and all 10 consumer migrations, both pre-existing and this session's) exists **only as uncommitted working-tree content** on top of HEAD `faa20bb5`. "Rollback," if ever needed, means discarding these untracked files / the in-place edits to `map_plotter.py` and `map_diff.py` (also untracked) — not `git revert` of any prior commit. This should be committed deliberately as a first commit for the feature; per this prompt's instructions, no commit was made in this session.

**Note:** during this session, an external process (not this agent) added an unused import line (`from opendrive_geometry.primitives import evaluate_line, evaluate_arc`) to `map_plotter.py`. It is dead code (the migration uses `LineArcEvaluator.pose_at`, not these functions directly) and was left in place per instruction; it does not affect behavior or the hash/golden-output results above.

## 14. Completion checklist (per I01 "Completion requires")

- [x] One active Line/Arc authority: `opendrive_geometry/evaluator.py::LineArcEvaluator`, used by all 10 Group A/B/C consumers.
- [x] No XODR mutation: confirmed structurally (§9) and empirically (hash-unchanged on 2 fixtures).
- [x] No unreviewed output change: all deltas in §7 are explained; zero unexplained differences (§8).
- [x] No junction, LaneLink, elevation-fitting, or CARLA changes: this session's diff touches only `ultimate_pipeline/visualization/map_plotter.py` and `ultimate_pipeline/visualization/map_diff.py`, plus these three new report files.

**Stopping here for independent review, per I01's final instruction. No commit was made.**
